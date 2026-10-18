# 06 · 阶段 6 残余风险与后续动作

> 口径：运维降级项**只评估、写入本文档**（D6-11），不在本阶段做。

## R6-1 worker 镜像 libgomp1 固化（承接 S5-12）— ✅ 已解决（2026-10-17）

**原现状**：Docker Hub 不可达导致 `docker compose build worker` 失败；阶段 5 的 qlib 运行时依赖 `libgomp1` 为**容器内热修**（`apt-get install` 进运行容器，未固化进镜像）。容器重建即丢失 → 届时 train/backtest/factor_compute 全部失败且报错隐蔽（`libgomp.so.1: cannot open shared object file`）。

**解决**（2026-10-17 上午，见 docs/stage5/06-risks.md S5-12）：Docker Hub 仍不可达，改走镜像源**按 digest 精确拉取** `docker.1ms.run/library/python@sha256:e529028…`（amd64，与 BuildKit 所需 manifest digest 一致）→ 本地 retag `python:3.11-slim` → `docker compose build worker` 成功 → 容器重建。验证：镜像内 `ldconfig -p` 含 `libgomp.so.1 (x86-64)`；容器内 `import lightgbm 4.7.0` OpenMP 链接通过；阶段 6 smoke 34/34 中的 qlib 真实训练/因子计算均经此镜像执行成功。

## R6-2 worker 崩溃留下孤儿 `running` 任务 — 中风险 → ✅ 已解决（阶段 7，见下）

**现象**（本阶段实测）：OrbStack hang 后 worker 重启，DB 里残留 `status=running` 的行（消费者已死）。API cancel 只能置 `cancel_requested`（设计上要消费者在进度检查点确认），无消费者的任务**永不收敛**；冒烟/调度侧看到的 running 计数被污染。

**已做**：dev 库人工 `UPDATE jobs SET status='canceled'` 收敛（记录在 05-testing §5）。

**解决**（阶段 7）：worker 启动消费前调用 `repositories/job.py::recover_stale_running_jobs` —— `heartbeat_at` 早于 `WORKER_STALE_JOB_MINUTES`（默认 10，env 可调）的 `running` 行：attempts 未耗尽 → 回 `queued` 重投，耗尽 → `failed`。**单副本前提**（多副本下「心跳超时」判据有双执行风险，扩副本前须改 `locked_by`/租约比对）写入函数注释、`.env.example` 与 [docs/stage7/06-risks.md](../stage7/06-risks.md)。实证：`tests/unit/test_worker_recover.py` 6 例 + 冒烟期间多次 worker 重启零残留。

## R6-3 登录限流与冒烟/e2e 共享额度 — 低风险

**现状**：`RATE_LIMIT_LOGIN_PER_MIN=5` 按 IP 固定窗口，冒烟（admin+viewer = 4 次）与 e2e（4 次）**各自安全但不可同分钟叠加**；同机并行跑两者会 429。

**已做**：两脚本文档均标注预算与错峰要求；e2e 用 storageState 把整套登录压到 4 次。

**后续**：CI 串行执行；或给 e2e 提供专用环境开关（如 `RATE_LIMIT_LOGIN_PER_MIN=1000` 的 staging 配置）—— **不改生产默认值**。

## R6-4 e2e 对种子数据的依赖 — 低风险

**现状**：02–08 旅程断言锚定开发种子（项目 `smoke`、因子 `s6-ma20-ic`、模型 `s6-reuse-lgb`、数据集 dev cn_data 等）。全新部署（无种子）除 01-auth 外全红。

**已做**：spec 头注释写明依赖；仓库提供一键种子脚本。

**后续**：CI 流水线里「起栈 → 跑种子 → e2e」固化为一条命令。

## R6-5 e2e 在 dev server 下的编译抖动 — 低风险

**现状**：共享模块编辑后 Next dev 全量重编译，首导航可能 >20s（唯一 flake 源）。已用 40s 导航等待 + `retries: 1` 缓解（实测两遍 11/11）。

**后续**：CI 用 `pnpm build && pnpm start`（生产构建）跑 e2e，抖动源消失、耗时更短。

## R6-6 因子值 100 万行硬上限 — 低风险

**现状**：`MAX_VALUES_ROWS = 1_000_000`（约 690 只 × 20 年日频的 7 倍余量）；超限**明确报错**而非截断。全市场 × 全历史 × 高频表达式会触顶。

**后续**：分片存储（按年/按池拆分多个 gz）或 parquet —— 等真实规模需求。

## R6-7 导出格式单一 / 前端不做权限树 — 低风险（已裁剪，见 01 决策）

审计导出仅 CSV；前端不按权限隐藏按钮（viewer 可见按钮 → 点击 403 兜底）。两者均以后端为唯一权威，属可接受的阶段性形态；阶段 7 结合 Casdoor 细粒度角色再评估。

## R6-8 旧回测无持仓明细 — 低风险

`positions_uri` 为空的存量回测，持仓导出按钮禁用并提示原因（不假装可导）。无需数据回填。

## R6-9 打印版依赖浏览器渲染 — 低风险

打印效果（分页、页眉页脚）随浏览器略有差异；我们只保证内容完整（print CSS + `.print-only` 页脚）与无多余 UI。需要像素级一致的归档 PDF 时再引入服务端渲染（明确不进本阶段，D6-10）。
