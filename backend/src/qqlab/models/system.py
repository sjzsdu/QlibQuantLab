"""系统：audit_logs（审计日志）/ system_configs（系统配置）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from qqlab.models.base import Base, JSONType, UUIDPk


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class AuditLog(UUIDPk, Base):
    """敏感操作审计。保留期由 AUDIT_RETENTION_DAYS 控制，按 org + 时间分区检索。"""

    __tablename__ = "audit_logs"

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False)
    #: 系统触发的操作允许为空（actor_user_id）
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    actor_username: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    detail: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_audit_logs_org_created", "org_id", "created_at"),
        Index("ix_audit_logs_org_actor_created", "org_id", "actor_user_id", "created_at"),
        Index("ix_audit_logs_org_action_created", "org_id", "action", "created_at"),
    )


class SystemConfig(UUIDPk, Base):
    """组织级系统配置。``is_secret=true`` 的值在 API 层脱敏。"""

    __tablename__ = "system_configs"

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False)
    config_key: Mapped[str] = mapped_column(String(120), nullable=False)
    value: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    is_secret: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (UniqueConstraint("org_id", "config_key", name="uq_system_configs_org_key"),)


__all__ = ["AuditLog", "SystemConfig"]
