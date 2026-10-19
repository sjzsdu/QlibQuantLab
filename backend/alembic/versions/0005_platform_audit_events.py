"""新增 platform_audit_events 表（阶段 8 · C 项，D8-5 平台审计）。

跨租户平台事件（登录成败 / admin.* 配置变更）的全局审计表 —— 刻意**不挂
org_id**：登录失败发生在身份解析前，本就无租户归属，平台视角必须留痕；
已知租户线索折进 detail。保留期由 PLATFORM_AUDIT_RETENTION_DAYS 控制，
写入时节流剪枝（PlatformAuditTrail）。

新库兼容：0001 的 ``Base.metadata.create_all`` 会把元数据里的新表一并建出，
故本迁移先 inspect 守卫 —— 已存在则跳过（与 0003/0004 同一思路）。

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from sqlalchemy import inspect

    bind = op.get_bind()
    if "platform_audit_events" in inspect(bind).get_table_names():
        return  # 新库由 0001 的 create_all 一并建出

    op.create_table(
        "platform_audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_username", sa.String(length=120), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_platform_audit_events_action_created",
        "platform_audit_events",
        ["action", "created_at"],
    )
    op.create_index(
        "ix_platform_audit_events_actor_created",
        "platform_audit_events",
        ["actor_username", "created_at"],
    )
    op.create_index("ix_platform_audit_events_created", "platform_audit_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_platform_audit_events_created", table_name="platform_audit_events")
    op.drop_index("ix_platform_audit_events_actor_created", table_name="platform_audit_events")
    op.drop_index("ix_platform_audit_events_action_created", table_name="platform_audit_events")
    op.drop_table("platform_audit_events")
