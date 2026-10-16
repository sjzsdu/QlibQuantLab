# 05 · 测试与实机验证

## 1. 测试分层

| 层 | 文件 | 覆盖 |
|----|------|------|
| unit | `test_compute_stub.py`(23, +6) | +train（pickle bundle 落盘、确定性、指标注记）、predict 降序分数、model 信号标签、rule 默认、**曲线按 backtest_id 隔离**、空注入信号守卫 |
| unit | `test_worker_stage5.py`(14, 新增) | train handler 端到端（artifact/四标注/模型 trained/日志）、缺因子列失败、缺 run、**重试改链 run→当前任务**；模型信号回测成功/无 run 失败；**取消状态机**（queued CAS、running CAS、开跑前标记、progress 检查点）；**增量日志 seq 连续且终态前可见**；**`_daily_ic` 按日期分组（MultiIndex vs RangeIndex 反例）**；默认切分分区 + 短区间 400 |
| api | `test_study_api.py`(28, 新增) | 模型快照/重复表达式 400/未知算法 400、训练提交（payload 快照、默认切分、越界 400、重叠 422、并发 409、无日期 400）、删除 confirm/绑定 409、策略双信号源 422/切换/发布 confirm、回测 422/409/曲线 400、RBAC 403、跨租户 404 |
| api | `test_jobs_api.py`(11, +7) | +增量日志空切片与 next_seq、日志跨租户、取消 queued→canceled→二次 409、**retry 复制 payload + retry_of**、queued 不可重试 409、跨租户取消 404、viewer 控制 403 |
| unit | `test_simulator.py`(15, +1) | 成本口径（阶段 3 硬约束）+ **数据缺口日前值计价**（回归见 §4-10） |

**结果：`uv run pytest -q` → 304 passed, 1 skipped**（阶段 4 为 247；净增 57）。`ruff check src tests` ✓。

> pandas 以 dev extra 进开发 venv（对齐 worker 锁定的 3.0.6），容器 `--no-dev` 不受影响——见 06-risks §3。

## 2. 前端验证

```
pnpm lint ✓      pnpm typecheck ✓      pnpm build ✓（18 路由）
```

新增路由：`/models` `/models/[id]` `/strategies` `/backtests` `/backtests/[id]` `/jobs` `/jobs/[id]`；`echarts` 6.1.0 按需引入（曲线页 First Load 412 kB）。浏览器冒烟 7 页见 §3。

## 3. 实机 live smoke

脚本 `stage5_smoke.py`（纯 stdlib，对 `localhost:8000`；入库 `scripts/stage5_smoke.py`）：建模型 → 训练 succeeded → 绑模型策略 → 双信号回测 → 曲线/四标注 → 日志增量 / 取消（queued CAS + running 缓存标记）/ 重试 → 负例（RBAC/确认/绑定）。

前置：栈全绿、worker 重启加载新代码（`docker compose restart worker`，无热重载）、`qqlab-qlib-server-1` healthy、dev cn_data 就绪。

### 结果（2026-10-16）：**43 / 43 通过**

关键实测值：

| 项 | 实测 |
|----|------|
| 训练 A | `train_ic=0.1719 valid_ic=-0.0100 valid_ir=-0.0661 valid_days=482 engine=qlib`（日频口径真正生效，§4-13） |
| 训练 C（重试件，split 2010-2016/2017-2019） | `n_valid_days=726 n_valid_samples=35318`（≈48.6 标的/日 ×50 上限）✓ |
| 规则回测 | `total_return=-0.4918 sharpe=-1.089 cost_applied.commission=0.0003`；曲线 487 点，首尾 `[1000000, 508221]`——缺口日 04-29/04-30 净值持平前值（§4-10） |
| 模型回测 | `training_run_id` 注入标注 ✓（D5-8），曲线 487 点 |
| 取消 | queued CAS → canceled、终态再取消 409；running 缓存标记 → worker progress 检查点协作落终态（日志含「用户取消（progress=45% 检查点）」） |
| 重试 | 复制 payload + `retry_of` → 新任务执行成功；**run 改链当前任务 `job_status=succeeded`**（§4-12 新断言） |
| 负例 | viewer 提交/取消 403、confirm 400×2、删除绑定 409、同模型并发 409、费用缺滑点 422、缺 model_id 422、重复表达式 400、未知算法 400 —— 全过 |

轮次轨迹：第 1 轮 24/2（libgomp 缺库 + smoke 脚本重复表达式口径，§4-8/脚本修复）→ 第 2 轮 41/42（`cost_applied` 断言字段口径：实写 `metrics` 非 `data_range`）→ 第 3 轮 42/42 → 修复 §4-12/13 并加断言后 **第 4 轮 43/43**。

### 浏览器冒烟（7 页，DOM 断言；本机无可视桌面故无截图）

- `/models` 8 行 9 列 + 新建按钮；`/models/[id]` 创建时快照表 + 训练记录（重试件显示「**成功**」、valid_ir 非 0——§4-12/13 的 UI 侧复验）
- `/strategies` 10 行 8 列 + 信号源/可见性标签 + 编辑/发布动作；`/backtests` 9 行 9 列（首行 `-49.18%` 与 API 一致）
- `/backtests/[id]` ECharts canvas ✓、六指标全显（§4-11 修复后 年化 `-29.55%`、交易次数 `2,793`）、四标注 ①②③④ 全渲染、费用透传表 7 项逐值回显
- `/jobs` 20 行 9 列 + 状态筛选器 + 进度条 + 错误列（`用户取消（排队阶段）` 等）
- `/jobs/[id]` payload 快照（含 `retry_of`/`training_run_id`）+ 「每 2 秒增量拉取日志（since_seq=4）」+ 执行日志 4 条 seq 连续（`[001]…[004]`）

## 4. 测试阶段与实机调试发现并修复的问题

1. **`await session.expire_all()`**：`AsyncSession.expire_all()` 是同步方法，误加 `await` → 取消 CAS 后身份映射未失效。改为同步调用（`repositories/job.py` 两处）。
2. **日志断言口径**：progress 行格式为 `"[92%] …"`，子串 `"[%"` 永不匹配 → 断言改 `"%]"`。
3. **审计 `status_before` 被 CAS 刷掉**：`mark_canceled_if_queued` 内 `expire_all()` 后再读 `row.status` 得到新值 → cancel() 先固化 `before_status/kind/rid` 局部量再审计。
4. **422 信封 500**：`model_validator` 抛出的 `ValueError` 原样躺在 `exc.errors()[].ctx.error`，`json.dumps` 崩（阶段 5 首次触发 422 路径）→ `main.py` 序列化前字符串化 ctx。
5. **Next.js 页面非法导出**：`jobs/page.tsx` 的 `export const JOB_STATUS_META` 导致 build 失败 → 模块内私有化。
6. **`<Text type="link">` 类型错误**：本版 AntD 不接受 → 内联 `color:#1677ff` 样式。
7. **worker SyntaxError 崩溃循环（实机）**：worker 容器钉在 **Python 3.11**（qlib 依赖），阶段 5 新增的 `handlers/base → qqlab.services → qqlab.schemas` 导入链首次触达 `class PageOut[T]`（PEP 695，3.12+ 语法）→ 启动即崩；宿主 3.12 测试全绿无法发现。修复：`Generic[T]` + 架构测试 `test_no_pep695_syntax_for_worker_python311`（AST 静态守卫，commit `0765339`）。
8. **lightgbm 缺 `libgomp.so.1`（实机）**：首次真实训练失败 `libgomp.so.1: cannot open shared object file` —— 阶段 3 只做规则回测、从不触达 LightGBM，镜像一直没装 OpenMP 运行时。修复：Dockerfile `worker-base` 增 `libgomp1`；**当日 registry-1.docker.io 不可达（EOF）无法重建镜像**，实机用 `docker compose exec -u root worker apt-get install libgomp1` 热修运行容器先行冒烟（容器重建后需重新构建镜像）。
9. **`# syntax=` 指令导致构建不可用（实机）**：该指令要求联网拉取 `docker/dockerfile:1` 前端镜像，Docker Hub 不可达时构建整体失败（曾被 `| tail` 掩盖退出码）。本文件无 heredoc/`--mount`，移除指令改用内置前端；注释说明恢复条件。
10. **数据缺口假破产 → 净值永久归零（实机，最重的一个）**：首次真实回测 `total_return` 恒为 **-100%**、净值首点 1M 尾点 0。定位：dev cn_data **2019-04-29 整个 A 股横截面无行情**（48/50 缺行，仅两只指数有值；日历含该日 → 缺口日进入交易日历）；模拟器盯市口径是「当日无行情的持仓**不计市值**」→ 缺口日全部持仓计 0 → `nav ≤ 0` 触发破产底线 → 净值清零且永续（规则/模型两种信号源同日崩，无一幸免）。修复：`simulator.py` 增 `last_close` 前值计价（缺口日沿用最近有效收盘），真破产底线保留；回归测试 `test_missing_date_forward_fills_last_close_instead_of_zeroing_nav`；实机复验 total_return=-0.49（真实亏损而非 -100%），缺口日 04-29/04-30 净值持平前值 ✓。
11. **回测详情页两个指标恒显示「—」（浏览器冒烟）**：前端读 `metrics.annual_return`/`metrics.n_trades`，后端实际键名 `annualized_return`/`trade_count` → 年化收益/交易次数不渲染。修复为正确键名，实机复验显示 -29.55% / 2,793 ✓。
12. **重试后 run 永久关联旧任务（实机）**：train handler 写 `run.job_id = run.job_id or job.id` —— 重试（D5-12 复制 payload 换新 job_id）执行成功后 run 仍指向最初的（已取消）任务 → 训练记录/模型列表 join 出 `canceled`，与 metrics/artifact 矛盾。改为**无条件关联当前执行任务**（入队竞态语义不变，重试语义修正）；回归测试 `test_retry_relinks_run_to_current_job`；smoke 新增断言「重试后 run 改链当前任务」✓。（回测侧 `save_result` 本就是无条件赋值，未受影响。）
13. **`_daily_ic` 日频 IC 恒为空 → valid_ic 静默回退、valid_ir 恒 0（实机）**：调用点传 `.to_numpy()` 把 MultiIndex 剥成 RangeIndex，`groupby(level=-1)` 从「按日期」退化成「按行」（每组 1 行 < 5 全跳过）→ `daily` 恒为空 → valid_ic 静默回退 pooled、valid_ir 恒 0（旧数据留痕：`n_valid_days=0, valid_ir=0.0`）。修复：调用点改传 Series（保 MultiIndex）+ docstring 写明契约；回归测试 `test_daily_ic_groups_by_date_on_multiindex_inputs`（含 RangeIndex 反例）；dev extra 增 pandas 以便单测。实机复验：`n_valid_days=726/482`、`valid_ir=-0.0085/-0.0661`（日频口径真正生效）✓。
14. **前端 dev server `.next` 陈旧（浏览器冒烟）**：宿主跑过 `pnpm build` 覆盖绑定挂载的 `.next` → 容器内 dev server 500（ENOENT vendor-chunks）。`docker compose restart frontend` 恢复；开发约定：宿主只 lint/typecheck，构建在容器内做（或构建后重启前端容器）。
