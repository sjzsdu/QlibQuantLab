"""身份与组织：organizations / users / org_members。

``users`` 是唯一**不含 org_id** 的表（全局身份，跨组织复用）；
``org_members`` 才是「用户在某组织中的角色」。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from qqlab.models.base import Base, JSONType, TimestampMixin, UUIDPk


class Organization(UUIDPk, TimestampMixin, Base):
    __tablename__ = "organizations"

    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    settings: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)


class User(UUIDPk, TimestampMixin, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: mock | casdoor（阶段 7 切换后靠 provider+external_id 归属同一个人）
    auth_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="mock")
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("auth_provider", "external_id", name="uq_users_provider_external"),)


class OrgMember(UUIDPk, TimestampMixin, Base):
    __tablename__ = "org_members"

    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: 角色列表，如 ["admin","researcher"]（JSON 以便 Postgres/SQLite 双方言测试）
    roles: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")

    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_org_members_org_user"),)


__all__ = ["OrgMember", "Organization", "User"]
