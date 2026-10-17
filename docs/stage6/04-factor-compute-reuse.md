# 04 · 因子计算落库 + IC 预览 + 训练复用因子值（D6-5 / D6-9 / D6-11）

## 1. 因子计算（FactorCompute）

### 任务与数据模型

- `JobKind.FACTOR_COMPUTE` + 新迁移 `0004_factor_compute_runs.py`（纯 `op.sa` 列定义，不用模块属性 —— 离线模式兼容）；
- `factor_compute_runs` 行：`factor_id / dataset_id / job_id / job_status / metrics / data_range / ic_uri / values_uri`；
- 同因子已有 queued/running 任务 → **409**（不重复排队）；入队失败**补偿删除** run 行（不留孤儿记录）。

### ComputePort 扩展

```python
async def compute_factor(spec: FactorSpec) -> FactorComputeResult
```

双实现（qlib / stub）；双对象落对象存储：

| 对象 | 格式 | 说明 |
|------|------|------|
| `values.csv.gz` | gzip CSV | 因子值面板（date, instrument, value）；`MAX_VALUES_ROWS = 1_000_000` 硬上限（超限明确报错，不截断静默出错） |
| `ic.csv` | 明文 CSV | 日度 rank-IC 序列（date, ic） |

IC 统计收敛在 `core/ic.py`（纯函数，worker 与测试共用）：`MIN_DAILY_SAMPLES = 5`（样本不足不给 IC，给空 metrics 而非假数）；`ic_ir` 分母 `1e-12` 护栏；rank-IC 用 `pandas.Series.rank` 实现。

### API

```
POST /api/v1/factors/{id}/compute   {dataset_id, start_date, end_date, universe, max_instruments}
GET  /api/v1/factors/{id}/compute-runs          计算记录列表（PageOut）
GET  /api/v1/factors/{id}/compute-runs/{rid}/ic-curve   日度 IC 曲线（≤1500 点降采样，与净值曲线同口径）
```

`data_range` 四标注齐全（本阶段新增 `universe` 维度）：区间 + 引擎 + 表达式 + 股票池 + `source.*`（vendor/license_ref/dataset）+ limitations。

实机（smoke §4）：`Mean($close,20)/$close-1` csi300 2018–2019 → ic_mean=0.031779 / ic_ir=0.179637 / coverage=0.968489 / 484 日×690 只；IC 曲线 484 点（未触降采样）。

## 2. 训练复用因子值（opt-in）

### 动机与语义

阶段 5 训练时对每个因子**重算**表达式 —— 与因子页 IC 预览各算一遍，既慢又可能因窗口不同而数字对不上。复用 = 训练直接读计算阶段落库的 `values.csv.gz`，**与 IC 预览严格同源**。

### 契约（D6-9）

- `TrainSubmitIn.reuse_factor_values: bool = False` —— **显式 opt-in，默认 False（重算，行为不变）**；
- 逐因子按 **`data_range["version"]` 匹配** `factor_compute_runs`（succeeded 且 `values_uri` 非空）；
- 任一因子无匹配 → **400 code 1005（`ValidationAppError`）**，消息可执行（指路「先在因子页计算 IC」），**绝不静默回退重算**（否则用户以为在复用、实际在重算，指标口径不可控）；
- payload 携带 `reuse_factor_values` + `factor_value_sources`（逐因子 `factor_id / run_id / values_uri / version`）；
- 训练 run 的 `data_range` 记 `reuse_factor_values: true` + `factor_value_runs: [run_id...]`（可追溯到具体计算记录）；
- `train.submit` 审计 detail 记 `reuse_factor_values`。

### 复用面板管线（worker/train handler）

```
_load_reused_panel(spec)   # 逐因子：storage 读 gzip → panel_from_values_csv → 左连接对齐
        ↓
_fetch_panel(spec, reused_panel)   # reused 为 None 时走原重算路径；有则以复用面板为准
        ↓
y 永远来自 qlib D.features        # 只有 X 复用；标签必须与 qlib 官方口径一致（防未来函数）
```

`panel_from_values_csv` / `slice_panel` 是 `qlib_compute.py` 里的**纯函数**（可单测）：gzip 解压 → 宽表 pivot（date × instrument）→ 按请求区间/股票池切片；多因子按 (date, instrument) 左连接取交集并对齐排序。

### 前端

- 训练弹窗新增「复用已计算的因子值（与 IC 预览同源）」Checkbox（默认不勾，与后端默认一致）；
- 训练记录展开行新增「因子值来源」：`复用已计算的因子值（与因子页 IC 预览同源）：<run_id 前 8 位>`（浏览器实测 ✓）—— 用户在训练记录里能直接看出这轮训练是重算还是复用。

### 测试

`test_train_reuse.py`（api，stub 计算）：正例（payload/data_range/审计三处留痕）、负例（无记录 → 400/1005 且消息含指引）、默认 False 行为不变、部分因子缺记录同样 1005。
`test_qlib_universe.py`（unit，纯函数）：`panel_from_values_csv` gzip 往返、`slice_panel` 区间/池切片、多因子对齐。
实机（smoke §6）：复用训练 succeeded，train_ic=0.129 / valid_ic=-0.018 / n_train=17587；`data_range.factor_value_runs == [计算 run]`；负例 400/1005 消息「无同版本的已完成计算记录（含因子值对象），无法复用——请先在因子页…」。
