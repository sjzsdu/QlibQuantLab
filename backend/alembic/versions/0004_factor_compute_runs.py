"""新增 factor_compute_runs 表（阶段 6 切片⑤：因子计算 + IC 预览）。

一次因子计算 = 一次 job（``JobKind.FACTOR_COMPUTE``）。因子表达式快照进
job payload；本表存结果口径（metrics / data_range 四标注 / ic_uri / values_uri）。

新库兼容：0001 的 ``Base.metadata.create_all`` 会把元数据里的新表一并建出，
故本迁移先 inspect 守卫 —— 已存在则跳过（与 0003 的列守卫同一思路）。

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from sqlalchemy import inspect

    bind = op.get_bind()
    if "factor_compute_runs" in inspect(bind).get_table_names():
        return  # 新库由 0001 的 create_all 一并建出

    op.create_table(
        "factor_compute_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "org_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "factor_id",
            sa.Uuid(),
            sa.ForeignKey("factors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "dataset_id",
            sa.Uuid(),
            sa.ForeignKey("datasets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("data_range", sa.JSON(), nullable=False),
        sa.Column("ic_uri", sa.String(length=500), nullable=True),
        sa.Column("values_uri", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_factor_compute_runs_org_id", "factor_compute_runs", ["org_id"])
    op.create_index("ix_factor_compute_runs_project_id", "factor_compute_runs", ["project_id"])
    op.create_index("ix_factor_compute_runs_factor_id", "factor_compute_runs", ["factor_id"])
    op.create_index("ix_factor_compute_runs_job_id", "factor_compute_runs", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_factor_compute_runs_job_id", table_name="factor_compute_runs")
    op.drop_index("ix_factor_compute_runs_factor_id", table_name="factor_compute_runs")
    op.drop_index("ix_factor_compute_runs_project_id", table_name="factor_compute_runs")
    op.drop_index("ix_factor_compute_runs_org_id", table_name="factor_compute_runs")
    op.drop_table("factor_compute_runs")
