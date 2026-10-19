"""平台审计装饰器（阶段 8 · D8-5）：平台事件双写 + 节流剪枝。"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select

from conftest import make_settings
from qqlab.adapters.audit.platform_audit_trail import PlatformAuditTrail, is_platform_action
from qqlab.container import Container
from qqlab.models import PlatformAuditEvent
from qqlab.ports.audit import AuditAction
from qqlab.ports.auth import CurrentUser, Role


class _SpyAuditWriter:
    """内层 writer 替身：记录收到的调用，验证转发行为不变。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def record(self, **kwargs) -> None:  # noqa: ANN003
        self.calls.append(kwargs)


class _MemoryOnlyCache:
    """get 恒 None（剪枝节流键永不存在）→ 每次写入都会触发剪枝尝试。"""

    async def get(self, key: str) -> bytes | None:  # noqa: ANN001
        return None

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:  # noqa: ANN001
        return None


def _user() -> CurrentUser:
    return CurrentUser(
        user_id="00000000-0000-0000-0000-0000000000aa",
        username="dev",
        org_id="11111111-1111-1111-1111-1111111111bb",
        roles=(Role.ADMIN,),
        provider="mock",
    )


async def _count_events(container: Container, action: str | None = None) -> int:
    query = select(func.count()).select_from(PlatformAuditEvent)
    if action:
        query = query.where(PlatformAuditEvent.action == action)
    async with container.database.session() as session:
        return (await session.execute(query)).scalar_one()


async def _reset_events(container: Container) -> None:
    """会话级共享测试库：数行数前先清空，防跨用例串扰。"""
    async with container.database.session() as session:
        await session.execute(delete(PlatformAuditEvent))
        await session.commit()


def test_is_platform_action_classification() -> None:
    assert is_platform_action(AuditAction.AUTH_LOGIN)
    assert is_platform_action(AuditAction.AUTH_LOGIN_FAILED)
    assert is_platform_action("admin.config.update")
    assert is_platform_action("admin.member.role_change")
    assert not is_platform_action(AuditAction.PROJECT_CREATE)
    assert not is_platform_action("adminx.not_a_real_prefix")


async def test_platform_action_writes_global_row_and_forwards() -> None:
    container = Container.build(make_settings())
    spy = _SpyAuditWriter()
    trail = PlatformAuditTrail(spy, container.database, container.cache, retention_days=365)
    user = _user()
    try:
        await _reset_events(container)
        await trail.record(
            action=AuditAction.AUTH_LOGIN,
            resource_type="auth",
            resource_id=user.user_id,
            user=user,
            org_id=user.org_id,
        )
        # ① 转发内层（租户审计路径行为不变）
        assert len(spy.calls) == 1
        assert spy.calls[0]["action"] == AuditAction.AUTH_LOGIN
        # ② 平台表一行：actor 落 username、org 线索折进 detail（列恒空，D8-5）
        assert await _count_events(container, AuditAction.AUTH_LOGIN) == 1
        async with container.database.session() as session:
            row = (await session.execute(select(PlatformAuditEvent).limit(1))).scalars().first()
        assert row is not None
        assert row.actor_username == "dev"
        assert row.detail.get("org_id") == user.org_id
    finally:
        await container.dispose()


async def test_non_platform_action_only_forwards() -> None:
    container = Container.build(make_settings())
    spy = _SpyAuditWriter()
    trail = PlatformAuditTrail(spy, container.database, container.cache, retention_days=365)
    try:
        await _reset_events(container)
        await trail.record(
            action=AuditAction.PROJECT_CREATE,
            resource_type="project",
            resource_id="p1",
            org_id="org-1",
        )
        assert len(spy.calls) == 1
        assert await _count_events(container) == 0
    finally:
        await container.dispose()


async def test_platform_row_failure_logged_not_raised() -> None:
    @asynccontextmanager
    async def _broken_session(self) -> AsyncIterator[None]:  # noqa: ANN001
        raise RuntimeError("db down")
        yield  # pragma: no cover

    class _BrokenDB:
        session = _broken_session

    trail = PlatformAuditTrail(_SpyAuditWriter(), _BrokenDB(), _MemoryOnlyCache(), retention_days=365)
    # 平台表写失败 + 剪枝失败都只记日志，不冒泡（同 DbAuditWriter 纪律）
    await trail.record(action=AuditAction.AUTH_LOGIN, resource_type="auth", resource_id=None)


async def test_login_failed_without_user_still_leaves_platform_trace() -> None:
    """D8-5 动机：登录失败无租户归属 → 租户表跳过，平台表必须留痕。"""
    container = Container.build(make_settings())
    spy = _SpyAuditWriter()
    trail = PlatformAuditTrail(spy, container.database, container.cache, retention_days=365)
    try:
        await _reset_events(container)
        await trail.record(
            action=AuditAction.AUTH_LOGIN_FAILED,
            resource_type="auth",
            resource_id=None,
            outcome="failure",
            detail={"reason": "invalid_state"},
            ip="203.0.113.7",
        )
        assert len(spy.calls) == 1  # 内层照常收到（无 org 时它自己跳过落表）
        assert await _count_events(container, AuditAction.AUTH_LOGIN_FAILED) == 1
        async with container.database.session() as session:
            row = (await session.execute(select(PlatformAuditEvent).limit(1))).scalars().first()
        assert row is not None and row.actor_username == "system"
        assert row.outcome == "failure" and row.ip == "203.0.113.7"
    finally:
        await container.dispose()


async def test_prune_deletes_expired_and_throttles_within_24h() -> None:
    container = Container.build(make_settings())
    spy = _SpyAuditWriter()
    trail = PlatformAuditTrail(spy, container.database, container.cache, retention_days=1)
    now = datetime.now(UTC)

    async def _seed(expired: bool) -> None:
        async with container.database.session() as session:
            session.add(
                PlatformAuditEvent(
                    actor_username="u",
                    action=AuditAction.AUTH_LOGIN,
                    created_at=now - timedelta(days=3) if expired else now,
                )
            )
            await session.commit()

    try:
        await _reset_events(container)
        await _seed(expired=True)
        await _seed(expired=False)
        await trail.record(action=AuditAction.AUTH_LOGIN, resource_type="auth", resource_id=None)
        # 首次写入触发剪枝：过期行没了，新鲜行 + 本次新写行保留
        assert await _count_events(container) == 2

        await _seed(expired=True)  # 再造一条过期行
        await trail.record(action=AuditAction.AUTH_LOGIN, resource_type="auth", resource_id=None)
        # 节流：24h 内不重跑剪枝 → 过期行仍在；总行数 = 2（留存）+ 1（新seed）+ 1（本次新写）
        assert await _count_events(container) == 4
    finally:
        await container.dispose()


async def test_prune_failures_do_not_raise() -> None:
    @asynccontextmanager
    async def _broken_session(self):  # noqa: ANN001, ANN202
        raise RuntimeError("db down")
        yield  # pragma: no cover

    class _BrokenDB:
        session = _broken_session

    trail = PlatformAuditTrail(_SpyAuditWriter(), _BrokenDB(), _MemoryOnlyCache(), retention_days=1)
    with contextlib.suppress(RuntimeError):  # record 内部本已吞掉，双保险防回归
        await trail.record(action=AuditAction.AUTH_LOGIN, resource_type="auth", resource_id=None)
