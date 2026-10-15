# 06 · 已知风险、验收清单与偏差说明

## 1. 已知风险（阶段 3 视角）

| # | 风险 | 影响 | 本阶段处置 | 状态 |
|---|------|------|------------|------|
| S3-1 | **A3-1/2/3/4 实机 smoke 未跑** | Qlib-Server 启动、Rosetta 性能、Yahoo/registry 连通需实证 | 脚本、compose、Makefile 目标全备好；smoke 输出结构化便于留档 | ✅ 2026-10-15 实跑全过（结论回写 `docs/stage1/06 §8.5`） |
| S3-1b | **pyqlib 0.9.7 无 linux/arm64 wheel（无 sdist）**：Apple Silicon 上 `docker build` 默认 arm64 直接失败 | worker 镜像构建失败（实测暴露：`doesn't have a wheel for the current platform`） | worker 服务锁 `platform: ${WORKER_PLATFORM:-linux/amd64}`（与 qlib-server 同一约束）；本机 `uv sync` 用 universal2 wheel 不受影响 | ✅ 已修复并实测构建通过 |
| S3-2 | **registry mirror 未配**：`python:3.10/3.11-slim` 在当前环境可能拉不动 | 镜像构建失败 | 预注给决策 #10；拉不动先配 mirror 或换内网源 | ✅ 未触发（实机直拉成功） |
| S3-3 | **Yahoo 连通性**（get_data.py 走 GitHub Release） | 数据导入失败 | 决策 #3：失败降级为连通性结论，**不换源**；bootstrap 脚本前置连通性检查（实测发现 slim 镜像无 curl，改用 python urllib） | ✅ 实测通过（196MB 官方 zip 下载成功） |
| S3-4 | **Apple Silicon 跑 amd64 Rosetta**：qlib-server 启动慢、gevent 在 Rosetta 下偶发卡顿 | 首次启动 30–60s；极端情况起不来 | healthcheck `start_period: 60s`；arm64 原生镜像待 wheel 齐全后切 | ✅ 实测可接受（worker 内 qlib init ≈ 2.0s；见 §8.5 性能快照） |
| S3-5 | **qlib 进程级单例**：并发 init 会互相覆盖全局 C 配置 | 数据串 org / 崩溃 | `QLIB_WORKER_CONCURRENCY=1`（.env）+ `qlib_online` 的 `threading.Lock` 二重防线 | ✅ 双保险 |
| S3-6 | **模拟器是自研最小实现**（非 qlib contrib backtest） | 与 qlib 官方回测结果数值不同 | 阶段 3 有意为之：qlib 只取数，模拟器口径统一（stub/qlib 一致）；`limitations` 明示「静态费用模型」 | ⚠️ 设计如此 |
| S3-7 | **冲击成本口径 = rate_per_million × 成交额**（不做 /1e6 缩放） | 数值上比「每百万分之一」直觉大 | 依据 `docs/stage1/06 §4` 权威公式；阶段 3 实测核对后固化；单测保证字段透传 | ✅ 已核对 |
| S3-8 | **SQLite ≠ Postgres**（JSONB / 部分索引） | 测试通过 ≠ 生产库通过 | 阶段 2 已知取舍（D5）；阶段 3 handler 测试走 SQLite，生产链路阶段 5 用真实 Postgres 回归 | ⚠️ 已知取舍 |
| S3-9 | **`JobLog` 不含 `TenantMixin`** | 只按 `org_id` + `job_id` 过滤，无 `created_by` | 有意为之：日志是任务的附属，不需要操作人归属 | ✅ 设计如此 |
| S3-10 | **worker 启动探测失败只告警不退出** | qlib-server 不可达时 worker 照常消费，任务快速失败 | 阶段 1 §7 的处置：job 标 `failed: qlib-server unreachable`，错误可见不掩盖 | ✅ 设计如此 |
| S3-11 | **`qlib_data` 卷无备份策略** | 重建容器不丢，但宿主级灾难会丢 | 阶段 5+ 评估对象存储归档 | ⏳ 后续 |
| S3-12 | **回测只经脚本入队（决策 #7）** | 无公共 API，UI 无法触发回测 | 阶段 4 补 API（经 service 层，不开直连 worker 的口子） | ⏳ 阶段 4 |
| S3-13 | **净值可能跌破 0**：`min_commission` 是绝对费用下限，净值衰减到极小时一笔迷你交易的佣金即击穿现金 → `_metrics` 对负底数取分数幂返回 **complex** → JSONB 落库 TypeError（实测：NAV = -5.28） | 回测结果无法落库 | 模拟器破产底线（净值 ≤ 0 清仓清零、亏损封顶 -100%）+ `_metrics` 年化收益兜底 + 回归测试 `test_bankruptcy_floor_caps_loss_at_100_percent` | ✅ 已修复 |
| S3-14 | **flush 失败毒化 session**：execute 内 flush 异常（如 JSON 写入非法值）后 `mark_failed` 自抛 `PendingRollbackError` | 任务**永远卡 queued**、终态丢失（实测踩过：041410f8） | 失败路径：记日志失败 → 回滚 → 重新登记拾取（attempts 不丢）→ 重试落终态；重试仍败只记日志并原样上抛原始异常 + 回归测试 `test_flush_poison_still_marks_failed` | ✅ 已修复 |
| S3-15 | **任务执行期间 DB 状态不可见**：整条任务链在单一事务里，终态才 commit | 运行中 `jobs` 行仍显示 queued/progress=0，进度只在 worker 日志 | 设计语义：崩溃时消息重投、任务仍 queued 可恢复（恰好依赖此不变量）；阶段 4 UI 若需实时进度再评估心跳提交 | ⚠️ 设计如此 |
| S3-16 | **aio_pika 迭代器空闲 30s 重建**：每 30s 打一条 INFO `closing with timeout 30 seconds` + 换 ctag | 日志噪音（易误判为连接抖动） | `rabbitmq_mq.consume` 的设计内行为（注释明示）：空闲超时 ≠ 消费结束，重建迭代器继续 | ⚠️ 良性 |

## 2. 验收清单（阶段 3）

> 对应 `docs/stage1/08-risks-and-roadmap.md` §3。✅ = 已用测试/命令验证；⏳ = 需要 Docker 实机验收。

| # | 验收项 | 状态 | 验证方式 |
|---|--------|------|----------|
| A3-1 | 默认栈 `docker compose up -d --build` 全绿（qlib profile 不计入） | ✅ | 2026-10-15 实跑：7 服务 healthy，`/api/v1/health/ready` 全 true，前端 :3000 200 |
| A3-2 | `docker compose --profile qlib up -d` 起 Qlib-Server 且 healthy | ✅ | `qlib-server` healthy（qlib init + RequestListener/RequestResponder/DataProcessor 全启动）；`rabbitmq-init` completed（vhost `/` + 权限授权） |
| A3-3 | 数据导入成功 + 三级连通 smoke 全 ok | ✅ | `make qlib-data`：196MB 官方 zip → **3875 标的 / 4943 交易日**（1999-11-10 → 2020-09-25）；`make qlib-smoke`：L1 握手 / L2 instruments=3875 / L3 features 抽样 35895 行 全 ok |
| A3-4 | 端到端回测：入队 → worker 消费 → 结果三标注 + 曲线落存储 | ✅ | dataset_import `83d61ee8` succeeded（台账 1/1/1）；backtest stub `2b153cd8` succeeded；backtest **qlib** `8d6a6a58` succeeded（metrics/data_range/limitations 三标注齐、曲线落存储，快照见 `docs/stage1/06 §8.5`） |
| A3-5 | 全量单测绿 | ✅ | `uv run pytest -q` → **183 passed, 1 skipped**（含破产底线与终态自愈 2 条实测回归） |
| A3-6 | 架构约束：API 不 import qlib；白名单 + 惰性导入 | ✅ | `uv run pytest tests/architecture -q` 通过（含 qlib 隔离用例） |
| A3-7 | compose 双 profile `config -q` 通过 | ✅ | `docker compose config -q && docker compose --profile qlib config -q` |
| A3-8 | 费用 100% 透传（六字段逐一开关） | ✅ | `test_every_cost_field_reduces_pnl_vs_zero_cost`；实跑回测 `cost_applied` 六字段回显 |
| A3-9 | 台账合规（data_sources / data_licenses / datasets 幂等 seed） | ✅ | `test_creates_ledger_rows_idempotent`；实跑 1/1/1（Yahoo、禁止再分发） |
| A3-10 | 租户边界 fail-closed（org_key 校验） | ✅ | `run_job` 的 org_key 校验 + `test_kind_mismatch_rejected`（kind 不匹配前 job 保持 queued） |

## 3. 与阶段 1 设计文档的偏差（阶段 3）

| # | 偏差 | 原因 | 影响 |
|---|------|------|------|
| E1 | qlib-server 基座 = `python:3.10-slim`（阶段 1 写的是 miniconda3:4.8.2） | 决策 #4：官方镜像拉不到且 `pip install git+qlib` 不可复现；3.10 是 gevent<23 有官方 wheel 的最高版本 | `ARG BASE_IMAGE` 可切；矩阵结论回写 06 §8 |
| E2 | 数据导入走官方「预构建 zip → 解压」而非「get_data.py 下载 CSV → dump_bin」 | 决策 #3：官方 zip 已是 dump_bin 格式，两段式更简单且不引入 dump_bin 依赖 | bootstrap 脚本更短、更快；`via` 标记仍区分 qlib/filesystem |
| E3 | 冲击成本公式 = `rate_per_million × 成交额`（不做 /1e6） | 依据 `docs/stage1/06 §4` 权威公式；阶段 3 实测核对后固化 | 数值口径明确；单测保证透传 |
| E4 | `JobRepository.create` 注入 `org_key` 到 payload | worker 需要外部 org 串派生数据目录与存储键；`job.org_id` 是 UUID，不能直接用作路径 | 入队必须经 `JobRepository.create`（`run_job` fail-closed 校验） |
| E5 | worker 镜像链独立（`dev-worker` / `worker-runtime`），API 镜像物理不含 qlib | 决策 #5：Python 3.11 vs 3.12 分离；venv 卷分开避免解释器串味 | compose 里 worker 有自己的 `build.target` 与 `worker_venv` 卷 |
| E6 | `rabbitmq-init` 一次性授权服务 | Qlib-Server 连 vhost `/`，默认用户只在 `/qqlab` 有权限；不改 vendored 源码 | `qlib-server` depends_on `rabbitmq-init` completed |
| E7 | 回测只经脚本入队，不开公共 API（决策 #7） | 阶段 3 交付最小闭环；API 留到阶段 4 | UI 无法触发回测（阶段 4 补） |
| E8 | `JobLog` 不含 `TenantMixin`（无 `created_by`） | 日志是任务附属，不需要操作人归属 | 只按 `org_id` + `job_id` 过滤 |
| E9 | `strategies.model_id` 放宽为可空（迁移 `0003_strategy_model_optional`） | 决策 #6：momentum-topk 是纯规则信号（训练在阶段 5），原 NOT NULL 使纯规则策略无法落库（实测 NotNullViolation） | `model_id IS NULL` = 纯规则策略；阶段 5 出模型后再绑定 |
| E10 | dev compose 的 `migrate` 服务挂载 `./backend` 工作树 | 镜像烤入的 alembic 落后于工作树（实测 `Can't locate revision identified by '0003'`：DB 已到 0003 而镜像只认 0001/0002） | 与 backend/worker 同构的工作树语义；prod 侧照旧每次 `target: runtime` 重建镜像 |
| E11 | qlib-server 依赖栈锁定 flask-socketio 4.3.2 / Flask 2.1.2 / Werkzeug 2.0.3 | Werkzeug 2.1 移除 `run_with_reloader`；flask-socketio ≥ 4.4 要 python-socketio 5（破坏 EIO3 客户端矩阵） | EIO3 矩阵成立（server 4.4.0/engineio 3.11.2 ↔ client 4.6.1/3.14.2），实机握手通过 |
| E12 | `JobService.enqueue` 两段式（session 提交 → MQ 发布） | `JobRepository.create` 只落库不发消息（实测：任务永远 queued 无人消费，如 job `ebbeda05`） | job 行是权威；发布失败有日志可追（阶段 4 补重发机制）；常量 `JOB_QUEUE` 放 `ports/message_queue`（worker py3.11 不能 import services） |

## 4. 阶段 1 风险登记册对照（R1–R10）

| 阶段 1 风险 | 阶段 3 触发？ | 处置 |
|-------------|--------------|------|
| R1 Apple Silicon amd64 | ✅ | `platform: linux/amd64` + `start_period: 60s`；arm64 待 wheel |
| R4 NFS 不可用 | ✅ | 共享卷 + 本地 provider_uri + `auto_mount=False`（`build_qlib_config` 单测断言） |
| R11 Redis 无密码 | ✅ | Docker 内网 + 宿主回环绑定；生产建议分实例 |
| 其余（R2/R3/R5–R10） | ❌ | 阶段 3 未触发 |
