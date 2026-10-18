"""IdentityRepository.ensure_org：外部 IdP 回落名绝不能覆盖既有组织名（阶段 7 修复）。

场景：Casdoor JWT 只携带 owner（组织名），不带组织显示名 → 平台回落 ``Org {id[:8]}``。
若用户经 ORG_MAP 把 SSO 组织映射进**既有**平台组织，回落名不能在首次登录时把
组织改名（rename_existing=False）；mock（org_name 非空）维持原有「跟随配置改名」行为。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_settings
from qqlab.container import Container
from qqlab.repositories.identity import IdentityRepository


@pytest.fixture
async def settings(tmp_path: Path):
    s = make_settings(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'identity.db'}"
    )
    from sqlalchemy.ext.asyncio import create_async_engine

    from qqlab.models import Base

    engine = create_async_engine(s.DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    return s


@pytest.fixture
def container(settings) -> Container:
    return Container.build(settings)


async def test_ensure_org_creates_then_keeps_name(container: Container) -> None:
    async with container.database.session() as session:
        repo = IdentityRepository(session)
        org = await repo.ensure_org("org-x", slug="org-x-slug", name="Org x")
        assert org.name == "Org x"
        # 同名再次 ensure → 幂等不动
        org2 = await repo.ensure_org("org-x", slug="org-x-slug", name="Org x")
        assert org2.id == org.id
        assert org2.name == "Org x"


async def test_rename_existing_true_renames_like_before(container: Container) -> None:
    """mock 路径（org_name 非空）：改 MOCK_ORG_NAME 后登录仍会同步改名（既有行为）。"""
    async with container.database.session() as session:
        repo = IdentityRepository(session)
        await repo.ensure_org("org-y", slug="s", name="Old Name")
        org = await repo.ensure_org("org-y", slug="s", name="New Name", rename_existing=True)
        assert org.name == "New Name"


async def test_rename_existing_false_preserves_name(container: Container) -> None:
    """casdoor 路径（org_name 为空回落名）：既有组织名绝不被覆盖。"""
    async with container.database.session() as session:
        repo = IdentityRepository(session)
        await repo.ensure_org("org-z", slug="s", name="Real Display Name")
        org = await repo.ensure_org(
            "org-z", slug="s", name="Org org-z-…", rename_existing=False
        )
        assert org.name == "Real Display Name"
