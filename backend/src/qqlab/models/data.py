"""数据管理：data_sources / data_licenses（授权台账）/ datasets。

平台**不内置未授权行情数据**：没有有效 ``data_licenses`` 记录就不能创建 ``datasets``。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from qqlab.models.base import Base, TenantMixin, TimestampMixin, UUIDPk


class DataSource(UUIDPk, TimestampMixin, TenantMixin, Base):
    __tablename__ = "data_sources"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="market")
    vendor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    homepage: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")


class DataLicense(UUIDPk, TimestampMixin, TenantMixin, Base):
    """授权台账：谁授权、授权范围、是否允许再分发、有效期、证据。"""

    __tablename__ = "data_licenses"

    data_source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    scope: Mapped[str] = mapped_column(String(64), nullable=False, default="internal_research")
    license_ref: Mapped[str] = mapped_column(String(200), nullable=False, default="unknown")
    allowed_use: Mapped[str] = mapped_column(Text, nullable=False, default="internal research only")
    redistribution_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    granted_by: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")


class Dataset(UUIDPk, TimestampMixin, TenantMixin, Base):
    __tablename__ = "datasets"

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    #: 无授权台账不得入库（服务层 + 数据库双重约束）
    license_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("data_licenses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    qlib_region: Mapped[str] = mapped_column(String(32), nullable=False, default="cn")
    freq: Mapped[str] = mapped_column(String(8), nullable=False, default="day")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    instrument_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_uri: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")


__all__ = ["DataLicense", "DataSource", "Dataset"]
