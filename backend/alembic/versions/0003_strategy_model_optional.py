"""strategies.model_id 放宽为可空。

阶段 3 决策 #6：momentum-topk 是**纯规则信号**（训练在阶段 5），不存在关联模型。
原 schema 的 NOT NULL 使纯规则策略无法落库（backtest smoke 实测 NotNullViolation）。

空值语义：model_id IS NULL ⇒ 纯规则策略（信号仅来自 signal_config）；
非空 ⇒ 绑定了阶段 5 训练产物的模型策略。

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    from sqlalchemy import inspect

    col = next(
        (c for c in inspect(bind).get_columns("strategies") if c["name"] == "model_id"),
        None,
    )
    if col is None or col["nullable"]:
        return  # 已可空（0001 create_all 由模型驱动，新库本就可空）
    if bind.dialect.name == "postgresql":
        op.alter_column("strategies", "model_id", nullable=True)
    else:
        # SQLite 无法 DROP NOT NULL；但 SQLite 库均由 0001 create_all（当前模型）建出，
        # 走到这分支说明 schema 异常，显式失败好过静默保留约束。
        raise RuntimeError("strategies.model_id 为 NOT NULL，但当前方言不支持 ALTER（非预期路径）")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # 若存在纯规则策略（model_id IS NULL），alter 会失败——降级前需先删除/绑定这些行
    op.alter_column("strategies", "model_id", nullable=False)
