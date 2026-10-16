# 阶段 5 · 训练 → 回测 → 可视化 → 任务中心闭环

> 一句话：**把「因子快照 → LightGBM 训练 → artifact 落对象存储 → 双信号源回测（rule|model）→ ECharts 净值曲线 + 四标注 → 任务中心（增量日志/取消/重试）」这条研究闭环做成可用功能** —— API 进程依旧零 qlib，训练与回测全部经 worker + ComputePort，四标注（数据区间/来源授权/费用口径/局限说明）在结果上固定展示。

## 交付物

| # | 交付物 | 状态 | 验证 |
|---|--------|------|------|
| 模型 CRUD + 因子创建即快照 + 删除二次确认/绑定 409 | ✅ | `test_study_api.py` |
| 训练提交（run 先落库 → 入队 → payload 执行快照，默认 70/30 切分） | ✅ | `test_study_api.py::TestTrainSubmit` |
| train handler（qlib LightGBM + stub 双实现，artifact 统一落存储） | ✅ | `test_worker_stage5.py::TestTrainHandler`（stub）；qlib 实机见 05-testing |
| 策略双信号源（rule\|model）+ 绑模 + 发布二次确认 | ✅ | `test_study_api.py::TestStrategyApi` |
| 回测提交（费用三件套 422 + 模型就绪 409 前置）+ 模型信号注入 | ✅ | `test_study_api.py` + handler 测试 |
| 四标注回写与固定展示（data_range / source / cost / limitations） | ✅ | handler + API 测试；前端详情页 |
| 净值曲线：按 backtest_id 隔离 + ≤1500 降采样 + ECharts | ✅ | `test_compute_stub.py`；build ✓ |
| 任务中心：since_seq 增量日志 / queued CAS 取消 / running 缓存标记 / retry | ✅ | `test_jobs_api.py` + `TestCancelStateMachine` |
| 前端四页（模型/策略/回测/任务） | ✅ | lint ✓ typecheck ✓ build ✓（18 路由）+ 浏览器冒烟 7 页 |
| 写路径显式提交（read-your-writes） | ✅ | 全部新增服务方法显式 commit |

**测试基线：247 → 304 passed（+57）+ 1 skipped，ruff 全绿；实机 smoke 43/43（见 05-testing §3）。**

## 文档导航

| 文档 | 内容 |
|------|------|
| [01-goal-and-tree.md](./01-goal-and-tree.md) | 阶段目标、**6 个集成点决策记录（D5-1…D5-6）**、实现决策（D5-7…D5-13）、文件树 |
| [02-model-training.md](./02-model-training.md) | 模型快照 / 训练提交与切分 / train handler / artifact 落盘 |
| [03-backtest-signals.md](./03-backtest-signals.md) | 双信号源策略、模型信号注入、**四标注口径**、曲线降采样 |
| [04-jobs-center.md](./04-jobs-center.md) | 增量日志（独立会话）、取消双通道、重试复制 payload |
| [05-frontend.md](./05-frontend.md) | 前端四页与 ECharts、2s 轮询交互 |
| [06-risks.md](./06-risks.md) | 已知风险（S5-1…S5-12）+ 验收清单（A5-1…A5-10）+ **偏差登记（算法目录静态化等）** |

## 快速验证

```bash
# 后端
cd backend && uv run ruff check src tests && uv run pytest -q   # 304 passed, 1 skipped

# 前端
cd frontend && pnpm lint && pnpm typecheck && pnpm build

# 实机（栈已起；worker 改动后需重启：docker compose restart worker）
# 1) 建模型（因子快照）→ 提交训练 → 任务中心日志增量至 succeeded
# 2) 策略绑模型 → 模型信号回测 → 详情页曲线 + 四标注
# 3) queued 取消 / running 取消（缓存标记）/ 失败重试（retry_of）
python3 scripts/stage5_smoke.py   # 见 05-testing.md §3 实机记录（43/43）
```
