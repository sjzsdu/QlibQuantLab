"""初始建表 + 开发种子数据。

Revision ID: 0001
Revises:
Create Date: 2026-10-14

说明：一次性建全部 17 张表（见 docs/stage1/03-data-model.md）。
后续阶段只加列/加表，不做破坏性变更。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from alembic import op
from sqlalchemy import insert, select

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from qqlab.core.ids import stable_uuid
    from qqlab.models import Base, Organization, OrgMember, SystemConfig, User

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)

    now = datetime.now(tz=UTC)
    org_id = stable_uuid("dev-org")
    user_id = stable_uuid("dev-user")

    if bind.execute(select(Organization.id).where(Organization.id == org_id)).first() is None:
        bind.execute(
            insert(Organization).values(
                id=org_id,
                slug="dev",
                name="Dev Organization",
                status="active",
                settings={},
                created_at=now,
                updated_at=now,
            )
        )
    if bind.execute(select(User.id).where(User.id == user_id)).first() is None:
        bind.execute(
            insert(User).values(
                id=user_id,
                username="dev",
                email="dev@qlibquantlab.local",
                display_name="Dev User",
                auth_provider="mock",
                external_id="dev-user",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
    if (
        bind.execute(
            select(OrgMember.id).where(OrgMember.org_id == org_id, OrgMember.user_id == user_id)
        ).first()
        is None
    ):
        bind.execute(
            insert(OrgMember).values(
                id=uuid.uuid4(),
                org_id=org_id,
                user_id=user_id,
                roles=["admin", "researcher"],
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
    for key, value in (
        ("compliance.notice_shown", {"enabled": True}),
        ("backtest.default_benchmark", {"value": "SH000300"}),
    ):
        if (
            bind.execute(
                select(SystemConfig.id).where(SystemConfig.org_id == org_id, SystemConfig.config_key == key)
            ).first()
            is None
        ):
            bind.execute(
                insert(SystemConfig).values(
                    id=uuid.uuid4(),
                    org_id=org_id,
                    config_key=key,
                    value=value,
                    is_secret=False,
                    updated_by="seed",
                    updated_at=now,
                )
            )


def downgrade() -> None:
    from qqlab.models import Base

    Base.metadata.drop_all(bind=op.get_bind())
