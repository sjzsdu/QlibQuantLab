"""jobs 去重约束改为"活跃态内唯一"。

旧：``uq_jobs_org_hash_status`` (org_id, payload_hash, status) —— status 参与唯一键，
导致同一 payload 的两个任务进入同一终态时（如都失败）在 ``mark_failed`` 撞约束。

新：``uq_jobs_org_active_hash`` 部分唯一索引，仅在 status IN ('queued','running')
内对 (org_id, payload_hash) 唯一 —— 真正想防的是"同一 payload 重复入队"，
终态历史记录应共存。

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = "uq_jobs_org_hash_status"
_NEW = "uq_jobs_org_active_hash"


def upgrade() -> None:
    bind = op.get_bind()
    # 旧约束可能不存在（0001 用 metadata.create_all，schema 由模型驱动）
    if _OLD in {c["name"] for c in _get_unique_constraints(bind, "jobs")}:
        op.drop_constraint(_OLD, "jobs", type_="unique")
    op.execute(
        text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {_NEW} "
            "ON jobs (org_id, payload_hash) "
            "WHERE status IN ('queued', 'running')"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _NEW in {i["name"] for i in _get_indexes(bind, "jobs")}:
        op.drop_index(_NEW, table_name="jobs")
    op.execute(
        text(
            f"ALTER TABLE jobs ADD CONSTRAINT {_OLD} "
            "UNIQUE (org_id, payload_hash, status)"
        )
    )


def _get_unique_constraints(bind, table: str) -> list[dict]:  # noqa: ANN001, ANN202
    from sqlalchemy import inspect

    return [c for c in inspect(bind).get_unique_constraints(table) if c.get("name")]


def _get_indexes(bind, table: str) -> list[dict]:  # noqa: ANN001, ANN202
    from sqlalchemy import inspect

    return [i for i in inspect(bind).get_indexes(table) if i.get("name")]
