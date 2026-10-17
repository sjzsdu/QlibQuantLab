# 06 · 已知风险、验收清单与偏差说明

## 1. 已知风险（阶段 5 视角）

| # | 风险 | 影响 | 本阶段处置 | 状态 |
|---|------|------|------------|------|
| S5-1 | **stub 与 qlib 双实现口径差**：stub 合成面板 + pickle，qlib 真面板 + joblib；指标/曲线数值不可比 | 本地/测试通过 ≠ qlib 实机一致 | 单测锁 stub 行为；qlib 路径由 live smoke 实机验收（A5-3/A5-4） | ⚠️ 已知取舍 |
| S5-2 | **qlib 实机链路依赖 `qlib_data` 卷与本地 D.features 模式**（`QLIB_WORKER_CONCURRENCY=1`） | 数据缺失/卷未挂 → 训练/回测运行期失败 | payload 执行快照 + 可读错误；缺因子列 → run failed 不重试 | ⚠️ 运维依赖 |
| S5-3 | **worker AMQP 卡死不自愈**（继承 S4-4） | 任务停 queued | smoke 前 `docker compose restart worker`；阶段 6+ 评估心跳 | ⚠️ 已知 |
| S5-4 | **运行时版本口径**：model 回测取「最近一次 succeeded 带 artifact」，与提交时刻的模型状态可能漂移（提交后又有新训练成功） | 回测实际用的模型 ≠ 用户提交时看到的 | 已写死文档口径（D5-8）；`data_range.training_run_id` 记录用的是哪次训练，可审计 | ✅ 设计如此 |
| S5-5 | **活跃态训练去重只挡 queued/running**：终态后允许同模型再次训练 | 无害（新 run 新 artifact） | 设计如此，复用阶段 3 机制 | ✅ 设计如此 |
| S5-6 | **日志单页 200 条 + seq 上限**：极长任务需多轮自排空；`limit` 上限 500 | 首屏日志分多请求 | next_seq 循环天然排空；终态前可拉完 | ✅ 设计如此 |
| S5-7 | **2s 轮询非推送**：状态变化感知延迟 ≤2s，多标签页同时轮询放大约 2 倍 QPS | 实时性略低 | D5-11 决策「不做 SSE」；单机规模可接受 | ✅ 设计如此 |
| S5-8 | **SQLite ≠ Postgres**（继承 S3-8/S4-6） | 测试通过 ≠ 生产库通过 | 生产链路阶段 7 用真实 Postgres 回归 | ⚠️ 已知取舍 |
| S5-9 | **回测不含持仓明细**（`positions_key` 恒为 None，本阶段只产净值曲线 + 指标） | 详情页无逐日持仓表 | 阶段 6 报告导出时一并补持仓明细 | ⏳ 阶段 6 |
| S5-10 | **行情缺口按前值计价（forward-fill）**：dev cn_data 在 2019-04-29 整个 A 股横截面为 NaN（指数有值）；旧口径缺口日持仓按 0 计价 → 误触破产底线 → 净值永久归零（阶段 5 实机踩坑，见 05-testing §4-10） | 数据缺口会让回测假破产 | 模拟器缺口日沿用最近有效收盘（`last_close`），回归测试锁死；真破产（cash+持仓 ≤0）底线保留 | ✅ 已修复 |
| S5-11 | **股票池 = `instruments/all.txt` 全量**：含指数（SH000300/SH000905…）与全部个股，`max_instruments` 仅按 qlib 顺序截断前 N；无 CSI300/中证500 等池选择 | 回测标的里可能混入指数；截断顺序受 all.txt 排序影响 | 数据区间标注回显 `instruments` 数；阶段 6 提供 universe 选择（`instruments/csi300.txt` 等已在数据卷内） | ⏳ 阶段 6 |
| S5-12 | **镜像重建依赖 Docker Hub 可达性**：阶段 5 实测 `registry-1.docker.io` EOF，`python:3.11-slim` 本地无缓存 → `docker compose build worker` 不可用 | 环境变更（如 libgomp1 入镜像）无法固化 | 已移除 `# syntax=` 前端镜像拉取；libgomp1 已写入 Dockerfile；当日用 `exec apt-get` 热修运行容器先行冒烟。**2026-10-17 已固化**：Docker Hub 仍不可达（SSL_ERROR_SYSCALL），改走镜像源按 digest 精确拉取 `docker.1ms.run/library/python@sha256:e529028`（amd64，与 BuildKit 所需 digest 一致）→ 本地 retag `python:3.11-slim` → `docker compose build worker` 成功 → 容器重建，`import lightgbm 4.7.0` OpenMP 链接通过，3 handler 注册 + 消费正常 | ✅ 已固化 |

## 2. 验收清单（阶段 5）

> 对应 `docs/stage1/08-risks-and-roadmap.md` §4 阶段 5 交付。✅ = 已用测试验证；实机列标注 live smoke 覆盖情况。

| # | 验收项 | 状态 | 验证方式 |
|---|--------|------|----------|
| A5-1 | 模型 CRUD + 因子**创建即快照**（改因子不影响模型；重复表达式 400；删除二次确认 + 绑定 409） | ✅ | `test_study_api.py`（28 用例） |
| A5-2 | 训练提交：run 先落库→入队→payload 执行快照；默认 70/30 切分；越界 400/重叠 422；同模型并发 409；补偿删除 | ✅ | `test_study_api.py::TestTrainSubmit` |
| A5-3 | train handler 端到端：artifact 落对象存储、metrics/data_range 四标注回写、模型 → trained、日志逐行可见 | ✅（stub） | `test_worker_stage5.py::TestTrainHandler`；qlib 实机见 05-testing |
| A5-4 | 双信号源回测：rule 默认 / model 注入预测（降序分数）；无成功训练提交 → 409；空信号 RuntimeError 守卫 | ✅ | `test_study_api.py` + `test_compute_stub.py` + `test_worker_stage5.py::TestBacktestModelSignal` |
| A5-5 | 费用三件套必填 422 + **100% 透传**（`cost_applied` 回写）；滑点仅 `fixed_bp` | ✅ | `test_study_api.py::test_cost_three_required_422` 等 |
| A5-6 | 曲线按 `backtest_id` 隔离；≤1500 点降采样；未完成 400；四标注详情端点 | ✅ | `test_compute_stub.py` + `test_study_api.py::test_curve_before_done_400` |
| A5-7 | 任务中心：`since_seq` 增量日志（seq 连续、终态停）；queued 原子 CAS 取消、二次取消 409；running 走缓存标记（开跑前/检查点两处）；retry 复制 payload + `retry_of`；仅 failed/canceled 可重试 | ✅ | `test_jobs_api.py`（+7）+ `test_worker_stage5.py::TestCancelStateMachine/TestIncrementalLogs` |
| A5-8 | 策略：model 源缺 model_id 422、切换清 model_id、发布 confirm + admin、跨租户 404、viewer 写 403 | ✅ | `test_study_api.py::TestStrategyApi` |
| A5-9 | 架构约束不破：API 进程零 qlib、业务只依赖 `qqlab.ports`、写路径显式提交 | ✅ | 架构测试 19+ 用例（在 304 基线内） |
| A5-10 | 前端四页 + ECharts 曲线；lint/typecheck/build 绿；浏览器冒烟 | ✅ | build 18 路由；浏览器冒烟 7 页全过（models/strategies/backtests/jobs + 三详情页），见 05-testing §3 |

**测试基线：247 passed + 1 skipped → 304 passed + 1 skipped（+57）。**

## 3. 与阶段 1/3 设计的偏差

| 项 | 原设计 | 实际 | 原因 |
|----|--------|------|------|
| **算法目录**（衔接点 #5，登记于此） | 阶段 1 计划 worker 运行时探测可用算法 | **静态化**为 `GET /models/catalog`（仅 `lgb`，`available=true`） | 探测需要 worker 握手协议 + 结果缓存，成本高于收益；D5-7 本就限死仅 LightGBM；阶段 6 引入第二算法时再评估动态探测 |
| 模型 artifact 落盘（衔接点 #6） | 初版在 `qlib_compute.train` 内 `storage.put` | **移至 train handler 统一落盘** | ComputePort 保持纯计算（stub/qlib 一致、可测），存储职责归编排层 |
| 取消实现 | 直接 UPDATE jobs 状态 | queued 才 CAS 直改；running 只置缓存标记 | worker 单事务持锁（S3-15），API 直 UPDATE running 会与 worker 竞态/死锁 |
| 日志通道 | 计划内独立会话（D5-0e） | ✅ 按计划落地 `JobLogSink` | ——（无偏差，实现与计划一致） |
| 422 信封 | `exc.errors()` 直接 JSON | ctx 内 `ValueError` 字符串化 | `model_validator` 抛出的异常对象不可 JSON 序列化（阶段 5 首次触发，500 → 修复为 422） |
| 测试依赖 pandas | dev extra 只有 pytest/ruff；host 不装 pandas/numpy | dev extra 增 `pandas>=2.2`（对齐 lock 中 worker 实机的 3.0.6） | `_daily_ic` 等 worker 计算口径必须在单测里覆盖（§4-13 实机回归）；容器 `--no-dev` 且不带 `--extra dev`，API/worker 运行时不受影响 |
| `.gitignore` | `data/` 忽略运行期数据 | 放行 `frontend/src/app/**`、`docs/stage5/` | 防路由/文档目录被误吞（继承阶段 4 教训） |
