# 03 · 双信号源回测与四标注

## 1. 策略（`signal_source = rule | model`）

`POST /api/v1/strategies` 收 `project_id / name / description? / signal_source? / model_id? / lookback?`：

- 存储：`Strategy.model_id` 列 + `signal_config = {"source": "rule"|"model", "lookback": N}`（无迁移）；
- `signal_source=model` 但缺 `model_id` → 422；`signal_source=rule` 忽略 model_id（`StrategyCreateIn._check_source`）；
- `PATCH` 切换语义：传 `signal_source` 或 `model_id` 任一即重算绑定 —— 切回 rule 时 `model_id` 清空；
- 发布：`POST /strategies/{id}/publish?confirm=true`，缺 confirm → 400；`strategy.publish`（admin，viewer 403）；`visibility=public + version+1 + published_at/by`，审计 `strategy.publish`。

**运行时版本口径（D5-8）**：回测时取该 `model_id` **最近一次 `succeeded` 且带 `artifact_uri` 的 TrainingRun**（`TrainingRunRepository.latest_succeeded`），不落 strategies 表。

## 2. 提交回测（三件套费用 + 前置校验）

`POST /api/v1/backtests`：

| 校验 | 失败 |
|------|------|
| `cost_config.commission_rate / slippage_value / impact_rate_per_million` 缺一 | **422**（schema 层，`slippage_type` 仅 `fixed_bp`） |
| `start_date > end_date` | 422 |
| 数据集无日期范围 | 400 |
| 策略是 model 信号但模型**无成功训练** | **409**「尚未有成功的训练记录」（不排队才失败） |

提交顺序同训练：`Backtest` 行先落库 + commit → 入队（payload 含 `backtest_id` 执行快照）→ 回填 `job_id` + 审计 → commit。

`cost_config` **100% 透传**进模拟器（`BacktestSpec.cost` → `SimulatorConfig`），结果 `metrics.cost_applied` 回写实际生效的完整费用结构（含交易所常规默认项）。

## 3. 回测 handler（`handlers/backtest.py`）

1. rule 分支：既有动量规则生成信号；
2. **model 分支**：`storage.get(run.artifact_uri)` → bundle → `compute.predict_signals(features, bundle)`（同数据集面板，样本外）→ `spec.signals = 注入值`；
   - 注入空信号 → `RuntimeError` 守卫（fail-loud，不静默产出空曲线）；
   - `data_range` 记 `training_run_id / model_id / signal_source=model`；
3. `compute.backtest(spec)`：`BacktestSpec.backtest_id` 使**曲线对象键按回测隔离**：
   `{org}/backtests/{backtest_id or strategy_id}/stub_curve.csv`（qlib 侧同构 `curve.csv`）；
4. 回写：`metrics`（含 `cost_applied`、`engine`、`signal_source` 标签）、`data_range`（`start/end/freq/n_days/instruments/topk/synthetic/source/limitations…`）、`limitations`（按信号源分支文案）、`curve_uri`、`finished_at`。

## 4. 四标注口径（衔接点 #4，详情端点固定展示）

| # | 标注 | 载体 | 内容 |
|---|------|------|------|
| ① | 数据区间与口径 | `backtest.data_range` | `start~end`、`freq`、`n_days`、`engine`（qlib/stub）、`instruments`、`topk`、`signal_source`、`training_run_id`（model 时） |
| ② | 数据来源 / 授权 | `data_range.source`（worker 由 dataset→license 链注入） | `vendor / dataset_name / license_ref / allowed_use / redistribution_allowed` |
| ③ | 费用假设 | `backtest.cost_config` | 三件套 + 交易所常规默认（最低佣金/结算费/印花税卖出）；**100% 透传**，`cost_applied` 回写 |
| ④ | 局限说明 | `backtest.limitations` | 按 `signal_source` 分支固定文案（历史回测不代表未来收益、未含融资融券/涨跌停、rule=动量规则局限 / model=样本外预测局限 + 数据集局限） |

训练记录同口径：`TrainingRun.data_range` 内含 `train/valid` 切分、`engine`、`n_factors`、`source`、`limitations`（前端详情页展开行渲染）。

## 5. 净值曲线读取

`GET /api/v1/backtests/{id}/curve`：

- 未完成（`curve_uri` 为空）→ 400「回测尚未完成」；
- 从对象存储读回 CSV → **降采样 ≤1500 点** → `{points: [[date, nav],…], total, downsampled}`（ECharts 友好）；
- 跨租户 404；`backtest.read` 即可读。
