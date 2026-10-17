"""审计导出的键集分页正确性（阶段 6 D6-1）。

``page_for_export`` 用 (created_at, id) 游标升序分页：小批量多次迭代
必须与单次全量导出**逐行一致**（无重复、无漏行），且在导出期间有新行
插入时不会像 offset 那样漂移。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from conftest import make_settings
from qqlab.container import Container
from qqlab.core.ids import stable_uuid
from qqlab.core.tenant import OrgScope
from qqlab.models import AuditLog
from qqlab.repositories.audit import AuditRepository
from qqlab.services.audit_service import AuditService

ORG = "export-org"


@pytest.fixture
async def container(tmp_path: Path) -> Container:
    s = make_settings(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'audit_export.db'}",
        QLIB_DATA_ROOT=str(tmp_path / "qlib_data"),
    )
    from sqlalchemy.ext.asyncio import create_async_engine

    from qqlab.models import Base

    engine = create_async_engine(s.DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    return Container.build(s)


async def _seed(session, *, n: int = 7) -> None:
    org = stable_uuid(ORG)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(n):
        session.add(
            AuditLog(
                id=uuid.uuid4(),
                org_id=org,
                actor_username=f"user{i % 3}",
                action=f"test.action{i}",
                resource_type="test",
                outcome="success",
                detail={"i": i},
                created_at=base + timedelta(seconds=i),  # 同一秒内多行 → 靠 id 决出次序
            )
        )
    await session.flush()


async def test_keyset_pages_match_single_pass(container: Container) -> None:
    scope = OrgScope(org_id=ORG, user_id="u")
    async with container.database.session() as session:
        await _seed(session, n=7)
        await session.commit()

    # 单次全量（batch 大于行数）
    async with container.database.session() as session:
        svc = AuditService(session, scope)
        full = [line async for line in svc.stream_csv(batch=100)]

    # 小批量强制多次游标迭代（7 行 / batch=2 → 4 批）
    async with container.database.session() as session:
        svc = AuditService(session, scope)
        paged = [line async for line in svc.stream_csv(batch=2)]

    assert "".join(paged) == "".join(full)
    body_lines = "".join(full).splitlines()
    assert len(body_lines) == 8  # 表头 + 7 行
    # 升序：created_at 严格不减
    stamps = [line.split(",", 1)[0] for line in body_lines[1:]]
    assert stamps == sorted(stamps)


async def test_keyset_cursor_filters_apply(container: Container) -> None:
    scope = OrgScope(org_id=ORG, user_id="u")
    async with container.database.session() as session:
        await _seed(session, n=5)
        await session.commit()

    async with container.database.session() as session:
        repo = AuditRepository(session, scope.org_id)
        rows = await repo.page_for_export(after=None, batch=10, action="test.action2")
        assert len(rows) == 1
        assert rows[0].action == "test.action2"

        # 游标指向最后一行 → 之后无匹配行
        last = rows[0]
        more = await repo.page_for_export(
            after=(last.created_at, str(last.id)), batch=10, action="test.action2"
        )
        assert more == []


async def test_keyset_insert_during_export_no_shift(container: Container) -> None:
    """导出进行中插入新行：已产出的游标序列不受影响（对比 offset 会漂移）。"""
    scope = OrgScope(org_id=ORG, user_id="u")
    org = scope.org_id
    async with container.database.session() as session:
        await _seed(session, n=6)
        await session.commit()

    from qqlab.core.ids import stable_uuid

    async with container.database.session() as session:
        repo = AuditRepository(session, scope.org_id)
        page1 = await repo.page_for_export(after=None, batch=3)
        assert len(page1) == 3
        # 模拟导出期间新行插入（时间戳晚于既有行）
        session.add(
            AuditLog(
                id=uuid.uuid4(),
                org_id=stable_uuid(org),
                actor_username="inserter",
                action="late.action",
                resource_type="test",
                outcome="success",
                detail={},
                created_at=datetime(2026, 6, 1, tzinfo=UTC),
            )
        )
        await session.flush()
        cursor = (page1[-1].created_at, str(page1[-1].id))
        page2 = await repo.page_for_export(after=cursor, batch=10)

    ids1 = [str(r.id) for r in page1]
    ids2 = [str(r.id) for r in page2]
    # 无重复
    assert not set(ids1) & set(ids2)
    # 既有 6 行全覆盖（新行时间戳晚于全部既有行 → 排在最后一批）
    assert len(ids1) + len(ids2) == 7
    # 新行只出现一次，且在第二批
    assert sum(1 for r in page2 if r.action == "late.action") == 1
    assert all(r.action != "late.action" for r in page1)
