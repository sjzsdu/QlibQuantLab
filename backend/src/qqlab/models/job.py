"""统一任务表：jobs / job_logs。

状态机：queued → running → succeeded | failed | canceled（failed 可 retry 回 queued）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from qqlab.models.base import Base, JSONType, TenantMixin, TimestampMixin, UUIDPk


class JobKind:
    DATASET_IMPORT = "dataset_import"
    FACTOR_COMPUTE = "factor_compute"
    TRAIN = "train"
    BACKTEST = "backtest"
    EXPORT = "export"


class JobStatus:
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"

    ALL = (QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELED)
    TERMINAL = (SUCCEEDED, FAILED, CANCELED)


class Job(UUIDPk, TimestampMixin, TenantMixin, Base):
    __tablename__ = "jobs"

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=JobStatus.QUEUED, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    #: 与 status 同步的冗余字段，方便前端进度条
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    requested_by: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("org_id", "payload_hash", "status", name="uq_jobs_org_hash_status"),)


class JobLog(UUIDPk, Base):
    """任务关键事件时间线（大日志落对象存储，这里只存前 N 条）。"""

    __tablename__ = "job_logs"

    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(tz=UTC)
    )

    __table_args__ = (UniqueConstraint("job_id", "seq", name="uq_job_logs_job_seq"),)


__all__ = ["Job", "JobKind", "JobLog", "JobStatus"]
