# 01 · 目标与文件树

## 目标

1. **训练闭环**：模型（绑定数据集 + 因子快照 + 超参）→ 提交训练入队（`train` 任务）→ worker 用 qlib LightGBM 训练 → artifact（joblib bundle）落对象存储 → 训练记录回写指标与四标注。
2. **双信号源回测**：策略 `signal_source = rule | model`；rule 走既有动量规则，model 在 worker 侧加载**最近一次产出 artifact 的成功训练**做样本外预测并注入 `BacktestSpec.signals`；提交时前置校验（无成功训练 → 409，不排队才失败）。
3. **四标注固定展示**（衔接点 #4 落定口径）：结果必带 ① `data_range`（切分/引擎/区间/信号源）② `cost_config`（费用三件套 100% 透传）③ `limitations`（局限说明，按信号源分支）④ 数据来源/授权（dataset → data_source/vendor + license_ref/allowed_use，org 过滤后注入）。
4. **任务中心**：`since_seq` 增量日志（worker 独立会话逐行提交，2s 轮询，终态自动停）+ 取消双通道（queued 原子 CAS / running 缓存标记协作式，**绝不直接 UPDATE running**）+ 重试（复制 payload + `retry_of` 重新入队）。
5. **前端四页**：`/models(+[id])`、`/strategies`、`/backtests(+[id])`（ECharts 净值曲线）、`/jobs(+[id])`；侧边导航四入口；权限点门控按钮。
6. **架构约束不破**：业务代码只依赖 `qqlab.ports`；API 进程零 qlib import（`train`/`predict_signals` 只存在于 ComputePort 两个适配器）；架构测试基线（304 tests）全绿。

## 集成点决策（6 项，用户确认 → 决策记录）

| # | 集成点（用户提出） | 落定口径 | 处置 |
|---|--------------------|----------|------|
| D5-1 | #1 训练/回测如何接入阶段 3 的 Qlib-Server 与 worker 链路 | **更正**：阶段 3/4 已交付 qlib 链（`qlib_compute` + worker 双模式）与只读 `/jobs`；训练复用同一 ComputePort / worker 注册机制，新增 `JobKind.TRAIN` handler | 已更正 |
| D5-2 | #2 训练数据从哪来 | **更正**：直接复用阶段 4 既有数据集（`dataset_id` 绑定 + 导入后的日期区间），不新建数据集类型；切分必须落在数据集区间内 | 已更正 |
| D5-3 | #3 模型的因子从哪来（`factor_ids` 引用） | 模型收 `factor_ids` **引用**因子库，**创建瞬间快照**表达式进 `factor_snapshot`；后续改因子不影响已建模型；训练 payload 同样携带快照（可复现性） | 已更正 |
| D5-4 | #4 报告四标注具体指什么 | ① `data_range`（含信号源/切分/引擎）② `cost_config` ③ `limitations` ④ 数据来源/授权 = dataset→data_source(vendor) + license(license_ref/allowed_use/redistribution)；worker 回写，详情端点固定展示 | ✅ 接受 |
| D5-5 | #5 算法目录与阶段 1「worker 探测」的偏差 | 目录**静态化**为 `GET /models/catalog`（仅 `lgb`，`available=true`），不做 worker 运行时探测；偏差登记 `docs/stage5/06-risks.md` §3 | ✅ 接受 |
| D5-6 | #6 模型 artifact 怎么落/读 | 统一经对象存储（`container.storage`）：qlib 训练产 joblib bundle `{format_version, model, features, target, algo}`，**落盘由 train handler 统一负责**（compute 不碰存储）；stub 用 pickle；回测时 handler `storage.get` + `predict_signals` | ✅ 接受 |

## 实现决策（对应计划 D5-0a…D5-0g）

| # | 决策 | 理由 |
|---|------|------|
| D5-7（0a） | 训练算法**仅 LightGBM**；`algo` 字段 + catalog 结构留扩展 | 阶段 5 先闭环，目录静态化已登记偏差（D5-5） |
| D5-8（0b） | 策略绑 `model_id`，`signal_config={"source","lookback"}`；**运行时版本 = 最近一次 `succeeded` 且有 `artifact_uri` 的训练**（`TrainingRunRepository.latest_succeeded`），不落 strategies 表 | strategies 只有 `model_id` 列，运行时取最新成功件，口径写死文档 |
| D5-9（0c） | 因子真实计算（factor_compute）/ IC 预览**推迟阶段 6** | 阶段 5 聚焦训练→回测→任务闭环；表达式静态校验已覆盖定义侧 |
| D5-10（0d） | 回测报告**导出**（PDF/CSV）推迟阶段 6 | 四标注 + 曲线页面已满足本阶段「可视化 + 说明」目标 |
| D5-11（0e） | 日志 = **worker 独立会话 `JobLogSink`**（seq=max+1、逐行 commit、失败仅 warning）+ `GET /jobs/{id}/logs?since_seq=N` 增量轮询；**2s 轮询，不做 SSE** | 独立会话避免被任务主事务回滚吞日志；轮询实现简单、够用 |
| D5-12（0f） | 取消双通道：queued → `mark_canceled_if_queued` 原子 CAS（Core UPDATE WHERE status + rowcount）；running → 仅置缓存标记 `job:{id}:cancel`（TTL 21600s），worker 在 progress 检查点协作式落终态；终态 → 409。重试 = 复制 payload + `retry_of` 重新入队（仅 failed/canceled 可重试） | worker 单事务持锁（S3-15 不变式），API 绝不直 UPDATE running；重试保留原始执行快照 |
| D5-13（0g） | 前端四页全做（模型列表+详情、策略、回测列表+详情、任务列表+详情） | 与用户确认的阶段 5 范围一致 |

## 文件树（新增 / 改动）

```
backend/src/qqlab/
├── ports/compute.py                     # [改] +TrainSpec/predict_signals、BacktestSpec +backtest_id/signal_source/signals
├── ports/audit.py                       # [改] +MODEL_DELETE
├── adapters/compute/
│   ├── qlib_compute.py                  # [改] train/predict_signals（qlib LightGBM + D.features 面板）、注入 signals 分支
│   └── stub_compute.py                  # [改] train（pickle bundle）/predict_signals、curve 键按 backtest_id 隔离
├── repositories/study.py                # [新增] Model/TrainingRun（latest/latest_succeeded）/Strategy（count_bounding）
├── repositories/job.py                  # [改] +list_logs、+active_by_kind、BacktestRepository list/add、取消 CAS（sync expire_all）
├── schemas/study.py  job.py             # [改] 模型/训练/策略/回测 DTO、JobLogsOut/JobActionOut
├── services/
│   ├── model_service.py                 # [新增] CRUD/快照/默认切分/commit-before-enqueue/补偿删除
│   ├── strategy_service.py              # [新增] 双信号源 CRUD + 绑模 + 发布（confirm）
│   ├── backtest_service.py              # [新增] 费用三件套 + 模型就绪 409 + 曲线 ≤1500 降采样
│   └── job_query_service.py             # [改] +logs(since_seq)/cancel(双通道)/retry(payload 复制)
├── api/v1/
│   ├── models.py                        # [新增] CRUD + /catalog + /{id}/train + training-runs 路由
│   ├── strategies.py  backtests.py      # [新增]
│   └── jobs.py                          # [改] +logs/cancel/retry
└── worker/handlers/
    ├── base.py                          # [改] JobCanceled、JobLogSink（独立会话）、progress 取消检查点、_honor_cancel
    ├── train.py                         # [新增] payload 快照 → TrainSpec → compute.train → storage.put → run/model 回写
    ├── backtest.py                      # [改] 模型信号路径（artifact 加载 + predict + 注入）、_source_annotation、backtest_id
    └── __init__.py  worker/main.py      # [改] 导出 + 注册 JobKind.TRAIN

backend/tests/
├── unit/test_worker_stage5.py           # [新增] train handler e2e / 模型信号回测 / 取消状态机 / 增量日志 / 默认切分
├── unit/test_compute_stub.py            # [改] +train/predict/信号标签/曲线隔离（18 用例）
├── api/test_study_api.py                # [新增] 模型/训练/策略/回测 28 用例（快照、409、422、RBAC、跨租户）
└── api/test_jobs_api.py                 # [改] +日志增量/取消/重试/权限 7 用例
（另：main.py 422 信封修复 —— model_validator 的 ValueError 在 ctx 中不可 JSON 序列化）

frontend/
├── src/app/models/page.tsx  [id]/page.tsx          # [新增] 模型列表/详情（提交训练 + 训练记录四标注展开）
├── src/app/strategies/page.tsx                     # [新增] 双信号源 CRUD + 发布
├── src/app/backtests/page.tsx  [id]/page.tsx       # [新增] 提交（费用三件套）/ 详情（ECharts 曲线 + 四标注）
├── src/app/jobs/page.tsx  [id]/page.tsx            # [新增] 任务中心 / 详情（since_seq 2s 轮询 + 取消/重试）
├── src/components/NavCurveChart.tsx                # [新增] echarts/core 按需引入 + ResizeObserver
├── src/components/AppShell.tsx                     # [改] +四导航入口
├── src/lib/types.ts                                # [改] +模型/训练/策略/回测/任务日志类型
└── package.json                                    # [改] +echarts 6.1.0
```

无新数据库迁移：`TrainingRun` 的四标注存 `data_range`（JSON）；`MLModel.dataset_id` NOT NULL、target 存 `training_config`；`Strategy.signal_config={"source","lookback"}`。
