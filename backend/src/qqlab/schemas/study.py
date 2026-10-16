"""研究域 schema：因子（阶段 4）+ 模型/训练/策略/回测（阶段 5）。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


# ------------------------------------------------------------------ 因子（阶段 4）
class FactorCreateIn(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=200)
    expression: str = Field(min_length=1, max_length=500)
    factor_type: str = Field(default="expression", max_length=32)
    description: str | None = None
    params: dict = Field(default_factory=dict)


class FactorUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    expression: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    params: dict | None = None


class FactorOut(BaseModel):
    id: str
    project_id: str
    project_name: str | None = None
    name: str
    expression: str
    factor_type: str
    description: str | None = None
    params: dict = Field(default_factory=dict)
    version: int
    visibility: str
    created_by: str = "（空）"
    created_at: datetime
    updated_at: datetime


class ExpressionCheckIn(BaseModel):
    expression: str = Field(min_length=1, max_length=500)


class ExpressionCheckOut(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    fields: list[str] = Field(default_factory=list)
    functions: list[str] = Field(default_factory=list)


# ------------------------------------------------------------ 模型 / 训练（阶段 5）
class ModelCreateIn(BaseModel):
    """创建模型：``factor_ids`` 引用因子库，创建时**快照**表达式进 ``factor_snapshot``。

    ``dataset_id`` 必填（models.dataset_id 非空约束）：模型绑定数据集，
    训练默认在该数据集区间上切分。``algo`` 目前仅 ``lgb``（D5-0a）。
    """

    project_id: str
    dataset_id: str
    name: str = Field(min_length=1, max_length=200)
    algo: str = Field(default="lgb", max_length=64)
    factor_ids: list[str] = Field(min_length=1, max_length=50)
    hyperparams: dict = Field(default_factory=dict)
    #: qlib 目标表达式；缺省用 ports.compute.DEFAULT_TARGET（次期收益）
    target: str | None = Field(default=None, max_length=300)


class ModelUpdateIn(BaseModel):
    """可改名与调超参；因子快照与算法不可改（可复现性），需另建模型。"""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    hyperparams: dict | None = None


class TrainingRunBrief(BaseModel):
    id: str
    job_id: str | None = None
    job_status: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class ModelOut(BaseModel):
    id: str
    project_id: str
    project_name: str | None = None
    dataset_id: str
    dataset_name: str | None = None
    name: str
    algo: str
    hyperparams: dict = Field(default_factory=dict)
    training_config: dict = Field(default_factory=dict)
    factor_snapshot: list[dict] = Field(default_factory=list)
    status: str
    last_run: TrainingRunBrief | None = None
    created_by: str = "（空）"
    created_at: datetime
    updated_at: datetime


class ModelCatalogItem(BaseModel):
    """``GET /models/catalog`` 条目。

    阶段 1 写的是「worker 探测」，阶段 5 实现为**静态目录**（worker 可用性
    由 healthcheck 反映）—— 偏差已登记在 docs/stage5/06-risks.md。
    """

    algo: str
    label: str
    available: bool = True
    note: str = ""


class SplitIn(BaseModel):
    """训练切分（ISO 日期闭区间）。valid 缺省时由服务按数据集区间补默认切分。"""

    train: tuple[str, str]
    valid: tuple[str, str] | None = None

    @model_validator(mode="after")
    def _check(self) -> SplitIn:
        spans = {"train": self.train}
        if self.valid is not None:
            spans["valid"] = self.valid
        parsed: dict[str, tuple[date, date]] = {}
        for key, (start_s, end_s) in spans.items():
            try:
                start, end = date.fromisoformat(start_s), date.fromisoformat(end_s)
            except ValueError as exc:
                raise ValueError(f"{key} 区间必须是 ISO 日期（YYYY-MM-DD）") from exc
            if start > end:
                raise ValueError(f"{key} 区间起始不能晚于结束")
            parsed[key] = (start, end)
        if self.valid is not None and parsed["valid"][0] <= parsed["train"][1]:
            raise ValueError("valid 区间必须晚于 train 区间（不可重叠）")
        return self


class TrainSubmitIn(BaseModel):
    split: SplitIn | None = None
    #: 训练标的截断（0 = 全量）；小样本冒烟/调参用
    max_instruments: int = Field(default=0, ge=0, le=20000)


class TrainingRunOut(BaseModel):
    id: str
    model_id: str
    model_name: str | None = None
    dataset_id: str
    job_id: str | None = None
    job_status: str | None = None
    metrics: dict = Field(default_factory=dict)
    #: 四标注（阶段 5 口径）：data_range / limitations / 数据来源授权 都在此字典内
    data_range: dict = Field(default_factory=dict)
    artifact_uri: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


# ---------------------------------------------------------------- 策略（阶段 5）
class StrategyCreateIn(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    signal_source: Literal["rule", "model"] = "rule"
    model_id: str | None = None
    #: 规则信号回看窗口（动量 lookback）；model 信号源忽略此参数
    lookback: int = Field(default=20, ge=1, le=250)

    @model_validator(mode="after")
    def _check_source(self) -> StrategyCreateIn:
        if self.signal_source == "model" and not self.model_id:
            raise ValueError("signal_source=model 时必须提供 model_id")
        if self.signal_source == "rule":
            self.model_id = None
        return self


class StrategyUpdateIn(BaseModel):
    """局部更新。source/model_id 的**有效组合**校验在服务层做（需要读行上现值）。"""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    signal_source: Literal["rule", "model"] | None = None
    model_id: str | None = None
    lookback: int | None = Field(default=None, ge=1, le=250)


class StrategyOut(BaseModel):
    id: str
    project_id: str
    project_name: str | None = None
    model_id: str | None = None
    model_name: str | None = None
    name: str
    description: str | None = None
    signal_source: str = "rule"
    signal_config: dict = Field(default_factory=dict)
    visibility: str
    is_public: bool = False
    version: int
    published_at: datetime | None = None
    published_by: str | None = None
    created_by: str = "（空）"
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- 回测（阶段 5）
class CostConfigIn(BaseModel):
    """费用假设：**三件套必填**（佣金 / 滑点 / 冲击成本，缺失即 422）。

    其余字段给交易所常规默认值（可覆盖）。所有字段 100% 透传进模拟器，
    不使用任何「qlib 默认值」兜底（docs/stage1/06 §费用硬约束）。
    """

    commission_rate: float = Field(ge=0.0, le=0.5, description="佣金费率（按成交额）")
    slippage_value: float = Field(ge=0.0, le=1000.0, description="滑点（基点，fixed_bp）")
    impact_rate_per_million: float = Field(ge=0.0, le=1.0, description="冲击成本费率/成交额")
    slippage_type: Literal["fixed_bp"] = "fixed_bp"
    min_commission: float = Field(default=5.0, ge=0.0)
    settlement_fee_rate: float = Field(default=0.00002, ge=0.0)
    stamp_duty_sell: float = Field(default=0.0005, ge=0.0)


class BacktestCreateIn(BaseModel):
    strategy_id: str
    dataset_id: str
    benchmark: str = Field(default="SH000300", max_length=32)
    start_date: date | None = None
    end_date: date | None = None
    topk: int = Field(default=50, ge=1, le=500)
    max_instruments: int = Field(default=0, ge=0, le=10000)
    cost_config: CostConfigIn

    @model_validator(mode="after")
    def _check_range(self) -> BacktestCreateIn:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date 不能晚于 end_date")
        return self


class BacktestOut(BaseModel):
    id: str
    project_id: str
    project_name: str | None = None
    strategy_id: str
    strategy_name: str | None = None
    dataset_id: str
    dataset_name: str | None = None
    job_id: str | None = None
    job_status: str | None = None
    benchmark: str
    cost_config: dict = Field(default_factory=dict)
    params: dict = Field(default_factory=dict)
    split_config: dict = Field(default_factory=dict)
    metrics: dict = Field(default_factory=dict)
    #: 四标注：data_range（含数据来源授权）/ cost_config / limitations
    data_range: dict = Field(default_factory=dict)
    limitations: str | None = None
    curve_uri: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    created_by: str = "（空）"
    created_at: datetime
    updated_at: datetime


class CurveOut(BaseModel):
    """净值曲线（降采样 ≤1500 点，ECharts 直接消费）。"""

    points: list[list] = Field(default_factory=list)  # [[date, nav], ...]
    total: int = 0
    downsampled: bool = False


__all__ = [
    "BacktestCreateIn",
    "BacktestOut",
    "CostConfigIn",
    "CurveOut",
    "ExpressionCheckIn",
    "ExpressionCheckOut",
    "FactorCreateIn",
    "FactorOut",
    "FactorUpdateIn",
    "ModelCatalogItem",
    "ModelCreateIn",
    "ModelOut",
    "ModelUpdateIn",
    "SplitIn",
    "StrategyCreateIn",
    "StrategyOut",
    "StrategyUpdateIn",
    "TrainSubmitIn",
    "TrainingRunBrief",
    "TrainingRunOut",
]
