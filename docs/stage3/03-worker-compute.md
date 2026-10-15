# 03 · Worker 计算链（镜像 / ComputePort / 模拟器 / handler / 租户边界）

## 1. 双镜像链：API 3.12 不含 qlib，worker 3.11 含 qlib

| | API（backend / migrate） | worker |
|--|--------------------------|--------|
| 基座 | `python:3.12-slim` | `python:3.11-slim`（决策 #5：pyqlib 0.9.7 cp311 wheel 齐全） |
| 构建 target | `dev` / `runtime` | `dev-worker` / `worker-runtime` |
| 依赖 | `uv sync --no-dev` | `uv sync --no-dev --extra qlib` |
| venv 卷 | `backend_venv` | `worker_venv`（**绝不共用**，解释器不同） |
| qlib | **物理不含** | 全仓唯一 import 点 |
| platform | 原生（arm64/x86 均可） | **锁 `linux/amd64`**（见下） |

**platform 锁 amd64（实测发现）**：pyqlib 0.9.7 在 PyPI 只有 `manylinux2014_x86_64` / `macosx_*_universal2` / `win_amd64` wheel，**无 linux/arm64、无 sdist** —— Apple Silicon 上 `docker build` 默认 arm64 会直接失败（`doesn't have a source distribution or wheel for the current platform`）。因此 compose 里 worker 服务带 `platform: ${WORKER_PLATFORM:-linux/amd64}`，与 qlib-server 同一约束。本机 macOS 直跑 `uv sync --all-extras` 用 universal2 wheel，不受影响。

`pyproject.toml` 的 `qlib` extra：

```toml
qlib = ["pyqlib==0.9.7", "python-socketio==4.6.1", "python-engineio==3.14.2"]
```

客户端（4.6.1/3.14.2）与 server（4.4.0/3.11.2）同 Engine.IO v3 代际；矩阵见 `docs/stage1/06 §2`。

## 2. ComputePort 双实现

```
ports/compute.py        ComputePort 协议 + CostConfig + BacktestSpec + BacktestResult
adapters/compute/
  __init__.py           build_compute(settings, storage) —— 工厂，惰性导入
  simulator.py          最小日频模拟器（纯标准库；两后端共用，口径不漂移）
  stub_compute.py       合成数据（make_synthetic_prices，seed 确定性）
  qlib_compute.py       qlib 取数（D.instruments/D.features 经 Qlib-Server）+ 模拟器
```

**职责边界**：qlib 在 `qlib_compute` 里**只做取数**；交易模拟与费用计算全部走 `simulator.py`。这样 `COMPUTE_BACKEND=qlib|stub` 切换时成本口径完全一致，不随后端漂移。

**惰性导入**：`build_compute` 只在 `worker/main.py` 被调用；`qlib_compute.py` 的 `qlib` 导入全在函数内。单测断言 `build_compute(COMPUTE_BACKEND="qlib")` 返回后 `qlib not in sys.modules` —— API 进程结构上不可能加载 qlib（架构测试 `test_api_process_never_loads_qlib_module` 二重兜底）。

**标的截断（决策 #2）**：`qlib_compute._fetch_prices` 取数时 `limit = spec.params.max_instruments or settings.QLIB_DATA_SYMBOLS`（0 = 全量）；磁盘数据保持全量，截断只作用于本次取数。

## 3. 模拟器口径（simulator.py）

硬约束（`docs/stage1/06 §4`）：

1. 费用模型 100% 由 `CostConfig` 驱动 —— 不使用任何「qlib 默认值」兜底；
2. 信号在 t 日收盘生成 → t+1 日开盘成交，杜绝前视偏差；
3. 回测结果回显 `cost_config` 副本（`metrics["cost_applied"]`）。

执行模型（**目标市值 delta**）：

```
t 日收盘：
  ranked = 信号排名前 topk
  per_slot = nav / len(ranked)
  targets = {inst: per_slot for inst in ranked}          # 新 topk 等权
  targets += {inst: 0.0 for inst in holdings - ranked}    # 被剔除持仓 → 目标 0（清仓）

t+1 日开盘（先卖后买）：
  delta = targets[inst] - holdings[inst] × open
  卖出（delta < 0）：value = min(-delta, 持仓市值)；成交价 = open × (1 - 滑点)
  买入（delta > 0）：budget = delta × scale（现金不足时等比缩放）；成交价 = open × (1 + 滑点)
  费用按成交后金额从现金扣除
```

**六类费用字段**（`_fee_detail`）：

| 字段 | 公式 | 说明 |
|------|------|------|
| `commission_rate` | `max(amount × rate, min_commission)` | 买卖双向 |
| `min_commission` | 同上（取 max） | 5 元最低佣金 |
| `slippage_value` | `open × (1 ± bp/10000)` | 买加卖减，`fixed_bp` |
| `impact_rate_per_million` | **`amount × rate`** | 冲击成本 = rate_per_million × 成交额（§4 权威口径，阶段 3 实测核对固化；不再做 /1e6 缩放） |
| `settlement_fee_rate` | `amount × rate` | 过户费 |
| `stamp_duty_sell` | `amount × rate`（仅卖出） | 印花税 |

单测 `test_every_cost_field_reduces_pnl_vs_zero_cost`：六个字段**逐一打开**，净值都低于零费用基线 —— 任何字段漏透传立即红灯。

## 4. handler 生命周期（run_job）

```
MQ payload 只带 job_id（job 行才是权威，org_id 从中取）
  → 校验 job.kind == handler.kind（不匹配 → 抛错，job 保持 queued）
  → 校验 payload.org_key：stable_uuid(org_key) == job.org_id（fail-closed）
      不一致 → mark_running → mark_failed(detail) → commit → 抛 ValidationAppError
  → mark_running（比较并交换，queued → running；attempts 自增）
  → execute(job, repo, progress)
      成功 → mark_succeeded（progress=100）
      失败 → mark_failed(str(exc)) → append_log → **显式 commit**（异常上抛会让 session rollback，失败状态必须先落库）→ re-raise
```

**org_key 注入（决策边界）**：`JobRepository.create()` 从 `OrgScope` 注入 `payload["org_key"]`（外部 org 串，如 `dev-org`），并按**注入后的 payload** 计算 `payload_hash`（`find_by_hash` 同源）。worker 用它派生数据目录（`/qlib_data/{org_key}/cn_data`）与对象存储键 —— 与 API 层 `scope.org_id` 同源，防串租户。

**ledger 归属**：`dataset_import` 与 `backtest` handler 写 `data_sources`/`data_licenses`/`datasets`/`backtests` 时 `created_by = job.created_by`（审计归属：谁入队的）。`JobLog` 不含 `TenantMixin`（只按 `org_id` + `job_id` 过滤）。

## 5. 两个 handler

### dataset_import

1. 目录校验：优先 `probe_dataset_via_qlib`（走 Qlib-Server 同一条取数路径）；worker 未装 qlib 时降级为**文件系统解析**（`calendars/day.txt` + `instruments/all.txt`）。两条路径结果同形（`instrument_count` / `start` / `end` / `via`）。数据缺失在两条路径下都是**失败**，不被掩盖。
2. 台账 seed（幂等 upsert，决策 #8）：
   - `data_sources`：1 条 `yahoo_official`（「Yahoo Finance（经 qlib 官方脚本导入）」）；
   - `data_licenses`：1 条，`redistribution_allowed=False`，`license_ref` 明示「禁止再分发原始数据」；
   - `datasets`：1 条（按 `storage_uri` 幂等；含区间/标的数快照）。
3. manifest 落对象存储：`{org}/datasets/{dataset_id}/manifest.json`（含 `verified_via`、`license_ref`、`redistribution_allowed`）。

### backtest

1. 读 `backtests` 快照（租户过滤）→ 合并 `strategy.signal_config` 与 `backtests.params`；
2. `start_date`/`end_date`：`backtests` 行优先，缺省用 `datasets` 全区间；
3. `compute.run_backtest(spec, progress)` → `BacktestResult`；
4. 回写三标注：`metrics`（含 `cost_applied` 副本）、`data_range`（区间/频率/标的数/引擎）、`limitations`（静态费用模型/未含融资融券与涨跌停/非训练模型/历史不代表未来）；
5. 曲线 CSV 上传对象存储：`{org}/backtests/{strategy_id}/curve.csv`；`curve_uri` 回写 `backtests.curve_uri`。

## 6. worker 启动探测

`COMPUTE_BACKEND=qlib` 时，worker 启动做一次 `probe_qlib_server`（socketio 握手）；失败**只告警不退出**（消费循环继续，具体任务在 `run_backtest` 里快速失败并把 job 标 `failed: qlib-server unreachable` —— 阶段 1 §7 的处置）。`COMPUTE_BACKEND=stub` 不触网。
