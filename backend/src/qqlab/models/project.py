"""项目：projects / project_members。"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from qqlab.models.base import Base, TenantMixin, TimestampMixin, UUIDPk


class Visibility:
    PRIVATE = "private"  # 默认：策略/项目默认私有
    ORG = "org"
    PUBLIC = "public"  # 需二次确认 + 审计


class Project(UUIDPk, TimestampMixin, TenantMixin, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default=Visibility.PRIVATE)
    default_benchmark: Mapped[str] = mapped_column(String(32), nullable=False, default="SH000300")

    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_projects_org_name"),)


class ProjectMember(UUIDPk, TimestampMixin, Base):
    __tablename__ = "project_members"

    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="viewer")

    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),)


__all__ = ["Project", "ProjectMember", "Visibility"]
