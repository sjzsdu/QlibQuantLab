# 02 · 模型与训练链路

## 1. 模型 CRUD（因子快照，衔接点 #3）

`POST /api/v1/models` 收 `project_id / dataset_id / name / algo / factor_ids / hyperparams / target?`：

- `algo` 必须在静态目录 `GET /api/v1/models/catalog` 内（当前仅 `lgb`，D5-7）→ 否则 400 / 1005；
- `factor_ids` 逐个经 `FactorRepository`（org 过滤，跨租户 404）读取，**创建瞬间快照**：

```json
"factor_snapshot": [
  { "factor_id": "...", "name": "mom5", "expression": "$close / Ref($close, 5) - 1", "version": 3, "factor_type": "expression" }
]
```

- 快照内表达式**重复 → 400**「表达式重复」；因子库后续改表达式/改版本**不影响**已建模型（`test_study_api::test_create_snapshots_factor_expression`）；
- `target` 默认 `DEFAULT_TARGET`（次期收益），存 `training_config.target`（无迁移）；
- 删除：`DELETE /models/{id}?confirm=true` 二次确认（缺省 400）+ `resource.delete`（viewer 403）；**被策略绑定时 409**「存在策略绑定」，需先解绑（策略切回 rule 或删除）。

## 2. 提交训练（read-your-writes + commit-before-enqueue）

`POST /api/v1/models/{id}/train`，body `{ "split": {"train": ["s","e"], "valid": ["s","e"]}? , "max_instruments": 0? }`：

| 步骤 | 行为 | 失败分支 |
|------|------|----------|
| 1 | 校验数据集有 `start_date/end_date` | 无 → 400「尚无日期范围」 |
| 2 | 显式切分必须落在数据集区间内 | 越界 → 400；train/valid 重叠 → 422（pydantic `model_validator`） |
| 3 | 未传切分 → `default_split()` 按数据集区间 **70/30**（train 前段 / valid 后段；区间 <60 天报「无法默认切分」400） | — |
| 4 | `TrainingRun` 行先落库（flush + **commit**） | — |
| 5 | `JobService.enqueue("train", payload)` | 入队抛错 → **补偿删除** run 行 + 状态回滚，不产孤儿 |
| 6 | 回填 `run.job_id` + 审计 `train.submit` → **commit** | — |

- **同模型已有 queued/running 训练 → 409**「训练任务进行中」（`JobRepository.active_by_kind`，按 payload hash 命中同一模型）；
- job payload 是**完整执行快照**：`{model_id, dataset_id, factors[快照], split, target, algo, hyperparams, max_instruments}` —— 因子库后续变化不影响已入队任务；
- 提交后即时可读（D4-8）：`GET /training-runs?model_id=` 立刻返回 run（`job_status=queued`），模型 `status → training`。

## 3. train handler（worker，`handlers/train.py`）

```
payload(执行快照) ──► TrainSpec ──► compute.train ──► storage.put(artifact) ──► 回写
```

1. `run.started_at` 落库（flush + commit）→ 任务开跑进度可读；
2. **执行前校验**：快照里的因子表达式在 qlib D.features 面板中缺列 → run `failed` + 可读错误（不重试性错误直接终态）；
3. `compute.train(TrainSpec)`（qlib 适配器）：
   - 单次 `qlib_online._fetch_panel`：`D.features` → MultiIndex(instrument, date) × 表达式列；
   - 切分由 API 层给定（handler 不自行切）；LightGBM 拟合；
   - 指标：`train_ic`（pooled）、`valid_ic`（逐日均值）、`valid_ir`（逐日均值/std）；
   - 返回 bundle `{format_version:1, model, features, target, algo}`；
4. **`storage.put` 由 handler 统一负责**（D5-6，compute 不碰存储）→ `artifact_uri = models/{org}/{model_id}/runs/{run_id}/stub_model.pkl`（stub）或 qlib 同构键；
5. 回写（单事务）：`run.metrics`、`run.data_range = {train, valid, engine, n_factors, source, limitations, artifact_key}`、`run.artifact_uri`、`run.finished_at`；`model.status="trained"`（模型已被删除则跳过）；
6. `data_range.source` = `_source_annotation()`（与回测共用，定义在 `handlers/backtest.py`）：dataset → data_source，org 过滤，带出 `vendor / license_ref / allowed_use / redistribution_allowed`；
7. progress：`JobLogSink` 独立会话逐行写（`[N%] …`），检查点先查取消标记（D5-11/D5-12）。

## 4. stub 计算（本地/测试模式）

`StubComputeProvider.train/predict_signals`（`QLIB_BACKEND=stub` 或 API 测试）：

- 面板为**确定性合成**（种子来自 `model_id` hash → 同输入两次训练产物逐位一致）；产出 pickle bundle + 指标 `engine=stub`；
- `predict_signals(features, bundle)` 返回按分数降序的 `list[(date, instrument, score)]`，供注入回测；
- 单测覆盖：bundle 落盘/确定性/降序/缺列报错（`test_compute_stub.py::TestStubTrainPredict`）。

## 5. 训练记录读取

- `GET /api/v1/training-runs?model_id=&page=` / `GET /training-runs/{id}`：含 `job_status`（联查 jobs）、`metrics`、`data_range`（四标注载体）、`artifact_uri`、时间戳；
- 跨租户 404（org 过滤）；`model.read` 即可读（viewer OK）。
