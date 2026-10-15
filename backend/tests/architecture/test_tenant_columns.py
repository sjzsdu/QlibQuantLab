"""数据模型约束：所有业务表必须带 org_id（多租户硬性要求）。"""

from __future__ import annotations

import pytest

from qqlab.models import ALL_MODELS, NON_TENANT_MODELS, TENANT_MODELS


def test_tenant_models_all_declared() -> None:
    assert set(TENANT_MODELS) | set(NON_TENANT_MODELS) == set(ALL_MODELS)


@pytest.mark.parametrize("model", TENANT_MODELS, ids=lambda m: m.__tablename__)
def test_business_table_has_org_id(model) -> None:  # noqa: ANN001
    columns = model.__table__.columns
    assert "org_id" in columns, f"{model.__tablename__} 缺少 org_id，无法做租户隔离"
    assert columns["org_id"].nullable is False, f"{model.__tablename__}.org_id 不能为空"

    org = columns["org_id"]
    covering = any(any(col is org for col in index.columns) for index in model.__table__.indexes) or any(
        any(col is org for col in constraint.columns)
        for constraint in model.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    )
    assert covering, f"{model.__tablename__}.org_id 应被索引覆盖（单列或组合索引/唯一约束首列）"


@pytest.mark.parametrize("model", NON_TENANT_MODELS, ids=lambda m: m.__tablename__)
def test_identity_tables_have_no_org_id(model) -> None:  # noqa: ANN001
    """全局身份表（organizations / users）本身不挂 org_id。"""
    assert "org_id" not in model.__table__.columns
