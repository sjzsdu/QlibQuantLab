# 05 · 测试方法

## 1. 测试分层与实测结果

```
architecture  39   qlib 隔离 5 条（白名单 / 模块级不导入 / API 进程不加载）+ 租户列 18 + 硬编码 3 + 导入边界 13
unit          87   simulator 12 / compute 15 / worker_handlers 6 / config 9 / ratelimit 4 / rbac 20 / security 15 / 其余 6
api           45   auth_flow 15 / admin_and_audit 13 / projects_and_isolation 9 / health_and_legal 8
contract      9    cache 4 / mq 2 / storage 3
integration   3    alembic 迁移
─────────────────
合计         176 passed, 1 skipped（skip = socketio 未装时的 probe 探测用例）
```

实测（交付时）：

```bash
cd backend && uv run ruff check src tests   # All checks passed!
cd backend && uv run pytest -q              # 176 passed, 1 skipped
```

## 2. 阶段 3 新增测试（38 条）

### test_simulator.py（12）

| 用例 | 断言 |
|------|------|
| `test_to_from_dict_roundtrip` | `CostConfig` 嵌套形态往返 |
| `test_from_dict_flat_shape` | API 扁平形态（`slippage_value` / `impact_rate_per_million` 顶层键）兼容 |
| `test_from_dict_none_uses_platform_defaults` | `None` → 平台默认 |
| `test_scores_ranking_is_deterministic` | 动量排名可复现、降序 |
| `test_insufficient_history_produces_nothing` | lookback 不足 → 无信号 |
| **`test_every_cost_field_reduces_pnl_vs_zero_cost`** | **六个费用字段逐一打开，净值都低于零费用基线（100% 透传的强证据）** |
| `test_zero_cost_flat_market_nav_is_constant_after_first_trade` | 零费用 + 零波动 → 建仓后净值恒等；`trade_count == 4`（首次建仓） |
| `test_metrics_include_cost_applied_copy` | 结果回显 `cost_applied`，键集精确匹配 |
| `test_metrics_shape` | 五个指标为 float；`max_drawdown <= 0` |
| `test_start_end_filtering` | 区间过滤生效 |
| `test_empty_calendar_raises` | 无行情日期 → 可读 ValueError |
| `test_invalid_topk_raises` | `topk < 1` → 可读 ValueError |

### test_compute_stub.py（15）

| 用例 | 断言 |
|------|------|
| `test_deterministic` / `test_different_seed_differs` / `test_prices_positive_and_sorted` | 合成数据确定性与合法性 |
| `test_run_backtest_result_shape` | 引擎标记 / `data_range.synthetic` / `cost_applied` 副本 / `limitations` / 曲线 key / 进度单调 |
| `test_deterministic_across_runs` | 两次运行 metrics 一致 |
| `test_curve_uploaded_when_storage_present` | 曲线真实落对象存储 |
| `test_healthcheck` | stub 恒通 |
| `test_stub_backend` / `test_invalid_backend_rejected_by_settings` / `test_valid_backends` | 工厂与配置校验 |
| **`test_qlib_backend_builds_lazily`** | **`build_compute(qlib)` 返回后 `qlib not in sys.modules`（惰性导入的结构性证据）** |
| `test_flat_init_kwargs` / `test_per_org_isolation` | `build_qlib_config` 纯函数、org 隔离、`auto_mount=False` |
| `test_probe_unreachable_server_returns_false` | 探测失败给结论不抛栈 |
| `test_qlib_env_module_importable_without_qlib` | 未装 qlib 也能 import `qlib_env`（延迟导入） |

### test_worker_handlers.py（6）

| 用例 | 断言 |
|------|------|
| **`test_creates_ledger_rows_idempotent`** | **台账三件套 1/1/1；`license_ref` 明示禁止再分发；manifest 落存储；重复跑仍 1/1/1** |
| `test_missing_data_dir_fails_job` | 数据未导入 → job failed，错误可读 |
| `test_backtest_runs_and_writes_three_annotations` | `cost_applied` 逐字段等于建回测时的 `cost_config`；`metrics`/`data_range`/`limitations` 三标注回写；曲线在存储里 |
| `test_backtest_job_without_backtest_id_fails` | 缺 `backtest_id` → failed，信息含字段名 |
| `test_kind_mismatch_rejected` | kind 不匹配发生在 `mark_running` 之前 → job 保持 queued（不误标失败） |
| `test_double_dispatch_is_skipped` | 重复消费同一条消息 → 第二次 skipped |

### architecture/test_import_boundaries.py（+5）

| 用例 | 断言 |
|------|------|
| `test_api_does_not_import_qlib` | API 相关模块不 import qlib |
| `test_qlib_import_whitelist` | qlib 只允许出现在 `worker/qlib_env.py` 与 `adapters/compute/qlib_compute.py` |
| `test_qlib_never_imported_at_module_level` | 白名单文件里 qlib 不在模块级 import |
| `test_api_process_never_loads_qlib_module` | 创建 app 后 `qlib` / `adapters.compute.qlib_compute` 不在 `sys.modules` |

## 3. 实机 smoke（A3-1 … A3-7）

> 本机 Docker daemon 可用；镜像源与 Yahoo 连通性是外部约束。若 `python:3.11-slim` / `python:3.10-slim` 拉不动，先解决 registry mirror（决策 #10 预注）。

| # | 验收项 | 命令 | 通过标准 |
|---|--------|------|----------|
| A3-1 | 默认栈全绿 | `make dev` | `docker compose ps` 全 healthy；`/api/v1/health/ready` 返回 ok |
| A3-2 | Qlib-Server 启动 | `make qlib-up` | `qlib-server` healthy（首次 Rosetta 启动 30–60s）；`rabbitmq-init` completed |
| A3-3 | 数据导入 + 三级连通 | `make qlib-data` && `make qlib-smoke` | bootstrap 打出 `instruments=N calendar_days=M`；smoke 三级全 ok |
| A3-4 | 端到端回测 | `make dataset-import-smoke` && `make backtest-smoke` | worker 日志出 `job_done`；`backtests` 行有 `metrics`/`data_range`/`limitations`/`curve_uri` |
| A3-5 | 全量测试 | `cd backend && uv run pytest -q` | 176+ passed |
| A3-6 | 架构约束 | `cd backend && uv run pytest tests/architecture -q` | qlib 隔离 5 条全绿 |
| A3-7 | compose 双 profile | `docker compose config -q && docker compose --profile qlib config -q` | 双双通过 |

smoke 脚本的输出是**结构化 JSON**（`qlib_connectivity_smoke.py`）或**带 job_id 的一行**（`enqueue_backtest_smoke.py`），便于断言与留档。

## 4. 已知 skip

| 用例 | 原因 | 影响 |
|------|------|------|
| `test_probe_unreachable_server_returns_false`（socketio 未装时） | probe 需要 `python-socketio`（worker 环境专属依赖） | API 侧测试环境跳过；worker 容器内必跑 |
