# 阶段 3 · Qlib-Server 打通 + 最小回测

> 一句话：**把「Qlib 真数据 → worker 计算 → 结果三标注」这条链路首次跑通** —— 自建 Qlib-Server 镜像（vendored 源码 + 钉死依赖）、worker 独立镜像（Python 3.11 + qlib，API 镜像物理不含 qlib）、自研最小日频模拟器（费用 100% 透传）、dataset_import 与 backtest 两个任务 handler、官方数据两段式导入脚本 + 三级连通性 smoke。

## 交付物速览

| 项 | 状态 | 说明 |
|----|------|------|
| `qlib-server/` 自建镜像 | ✅ 本地已构建验证 | vendored `microsoft/qlib-server` @ `0ad527d3`；`requirements.lock` 钉死；entrypoint 启动时渲染配置；`qqlab/qlib-server:stage3` 已构建并容器内验证 |
| worker 镜像链（`dev-worker` / `worker-runtime`） | ✅ | Python 3.11 + `--extra qlib`；独立 `worker_venv` 卷；API 镜像（3.12）不含 qlib |
| `ComputePort` 双实现 | ✅ | `stub_compute`（合成数据）/ `qlib_compute`（经 Qlib-Server 取数）；工厂惰性导入，API 进程结构上不可能加载 qlib |
| 最小日频模拟器 `simulator.py` | ✅ | 目标市值 delta 模型，先卖后买；六类费用字段 100% 透传（冲击成本 = rate_per_million × 成交额） |
| `dataset_import` handler | ✅ | 文件系统/qlib 双路径校验 + `data_sources`/`data_licenses`/`datasets` 台账 seed（幂等） |
| `backtest` handler | ✅ | 读快照 → ComputePort → 回写 `metrics`/`data_range`/`limitations` 三标注 + 曲线落对象存储 |
| `JobRepository` org_key 注入 | ✅ | 入队时注入外部 org 串，worker fail-closed 校验（防串租户） |
| 导入/连通/入队 smoke 脚本 | ✅ | `bootstrap_qlib_data.sh`（官方 zip 两段式）、`qlib_connectivity_smoke.py`（L1/L2/L3）、`enqueue_backtest_smoke.py` |
| 测试 | ✅ | **176 passed, 1 skipped**（新增 38：simulator 12 / compute 15 / worker handlers 6 / 架构 3+2） |
| `docker compose config -q` | ✅ | 默认与 `--profile qlib` 双双通过 |
| **A3-1 / A3-3 / A3-4 实机 smoke** | ⏳ | Qlib-Server 启动、连通、端到端回测需实跑（脚本与命令已备好，见 [05-testing](./05-testing.md)） |

## 文档导航

| 文件 | 内容 |
|------|------|
| [01-goal-and-tree.md](./01-goal-and-tree.md) | 目标 + 阶段 3 新增/改动文件树 |
| [02-qlib-server.md](./02-qlib-server.md) | Qlib-Server 自建镜像：vendored 源码、依赖锁定、配置渲染、与官方镜像的差异 |
| [03-worker-compute.md](./03-worker-compute.md) | worker 镜像链、ComputePort 双实现、模拟器口径、handler 生命周期、org_key 边界 |
| [04-deployment.md](./04-deployment.md) | compose 变更（qlib profile / rabbitmq-init / worker venv）、Makefile 目标、启动与 smoke 命令 |
| [05-testing.md](./05-testing.md) | 测试分层与实测结果、实机 smoke 流程（A3-1…A3-7） |
| [06-risks.md](./06-risks.md) | 已知风险 + 验收清单 + 与阶段 1 设计的偏差 |

## 阶段 3 的 10 条绑定决策（你已确认）

| # | 决策 |
|---|------|
| 1 | qlib profile 保持 opt-in（`--profile qlib`），绝不进默认 `up` |
| 2 | 全量 CN 数据 + `QLIB_DATA_SYMBOLS` 截断开关；首次 smoke 用小集合 |
| 3 | 数据导入只走官方两段式（下载 zip → 本地解压）；失败降级为连通性结论，不换源 |
| 4 | qlib-server 基座 = python 官方镜像，`ARG BASE_IMAGE` 可切（不追 miniconda3:4.8.2） |
| 5 | worker 锁 Python 3.11，API 保持 3.12（pyqlib 0.9.7 cp312 wheel 风险） |
| 6 | 动量 topk 日频调仓纯规则信号（无模型；训练在阶段 5） |
| 7 | 回测只经脚本入队，不开公共 API |
| 8 | dataset_import 台账 seed：1 条 data_sources（yahoo_official）+ 1 条 data_licenses（禁止再分发）+ dataset 行 |
| 9 | 提交拆分：infra / qlib-server / worker-compute / docs |
| 10 | 分工：代码 + 文档 + L1/L2 测试 + stub 链 + smoke 脚本由助手交付；实机 smoke 由你跑（或提供镜像源/Yahoo 兜底源） |
