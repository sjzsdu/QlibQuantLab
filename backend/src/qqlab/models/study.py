"""研究链路：factors → models → training_runs → strategies → backtests。

每一步都保留**输入快照**（因子表达式、超参、信号配置、费用假设），
保证结果可复现、可解释；报告必须回显这些内容与数据区间。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from qqlab.models.base import Base, JSONType, TenantMixin, TimestampMixin, UUIDPk


class Visibility:
    PRIVATE = "private"
    ORG = "org"
    PUBLIC = "public"


class Factor(UUIDPk, TimestampMixin, TenantMixin, Base):
    __tablename__ = "factors"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Qlib 表达式，如 "$close / $open - 1"
    expression: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    params: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    factor_type: Mapped[str] = mapped_column(String(32), nullable=False, default="expression")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default=Visibility.PRIVATE)


class FactorComputeRun(UUIDPk, TimestampMixin, TenantMixin, Base):
    """因子计算运行记录（阶段 6 切片⑤）。

    一次计算 = 一次 job（``JobKind.FACTOR_COMPUTE``）。因子表达式在提交时
    **快照进 job payload**（含 version），行上只存结果口径：
    - ``metrics``：coverage / ic_mean / ic_std / ic_ir / ic_positive_ratio / n_days…；
    - ``data_range``：区间 + 引擎 + 表达式 + 股票池 + 数据来源授权（``source``）
      + 局限（``limitations``）—— 与训练/回测同一「四标注」口径；
    - ``ic_uri`` / ``values_uri``：对象存储 CSV（IC 序列 / 因子值面板）。
    """

    __tablename__ = "factor_compute_runs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    factor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("factors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("datasets.id", ondelete="RESTRICT"), nullable=False
    )
    metrics: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    data_range: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    ic_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    values_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MLModel(UUIDPk, TimestampMixin, TenantMixin, Base):
    """模型定义（算法 + 超参 + 数据集 + 因子集合快照）。表名 ``models``。"""

    __tablename__ = "models"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("datasets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    algo: Mapped[str] = mapped_column(String(64), nullable=False, default="LGBModel")
    hyperparams: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    training_config: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    #: 提交时的因子集合快照，避免因子后续修改导致结果不可复现
    factor_snapshot: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")


class TrainingRun(UUIDPk, TimestampMixin, TenantMixin, Base):
    __tablename__ = "training_runs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("models.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("datasets.id", ondelete="RESTRICT"), nullable=False
    )
    metrics: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    data_range: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    artifact_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    qlib_experiment: Mapped[str | None] = mapped_column(String(200), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Strategy(UUIDPk, TimestampMixin, TenantMixin, Base):
    """策略：信号规则 + 可选模型绑定。默认私有，公开需二次确认。

    ``model_id`` 可空：阶段 3 的 momentum-topk 是**纯规则信号**（决策 #6，训练在阶段 5），
    不存在关联模型；阶段 5 训练出模型后再绑定。
    """

    __tablename__ = "strategies"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("models.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    signal_config: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default=Visibility.PRIVATE)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[str | None] = mapped_column(String(120), nullable=True)


class Backtest(UUIDPk, TimestampMixin, TenantMixin, Base):
    """回测结果。必须标注数据区间、参数、费用假设与局限性。"""

    __tablename__ = "backtests"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("datasets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    benchmark: Mapped[str] = mapped_column(String(32), nullable=False, default="SH000300")
    split_config: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    #: 费用假设三件套（滑点 / 手续费 / 冲击成本），API 层必填
    cost_config: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    params: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    metrics: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    data_range: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    curve_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    positions_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    limitations: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)


__all__ = [
    "Backtest",
    "Factor",
    "FactorComputeRun",
    "MLModel",
    "Strategy",
    "TrainingRun",
    "Visibility",
]
