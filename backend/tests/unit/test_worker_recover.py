"""R6-2：worker 启动时回收孤儿 running 任务（心跳断更 → queued/failed）。

**单副本前提**（见 ``recover_stale_running_jobs`` docstring）：dev/prod compose 的
worker 均为单服务、无 replicas —— 启动时旧消费者必已退出，回收安全。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from conftest import make_settings
from qqlab.container import Container
from qqlab.core.ids import stable_uuid
from qqlab.core.tenant import OrgScope
from qqlab.models import Job, JobStatus, Organization, User
from qqlab.repositories.job import JobRepository, recover_stale_running_jobs

ORG = "recover-org"
USER = "recover-user"


@pytest.fixture
def settings(tmp_path):
    from sqlalchemy import create_engine

    from qqlab.models import Base

    db_file = tmp_path / "recover.db"
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)
    engine.dispose()
    return make_settings(DATABASE_URL=f"sqlite+aiosqlite:///{db_file}")


@pytest.fixture
def container(settings) -> Container:
    return Container.build(settings)


async def _seed(container: Container) -> uuid.UUID:
    """建 org/user 并返回一个可入队的 job_id（queued 状态）。"""
    async with container.database.session() as session:
        org_uuid = stable_uuid(ORG)
        user_uuid = stable_uuid(USER)
        if await session.get(Organization, org_uuid) is None:
            session.add(Organization(id=org_uuid, slug="recover", name="Recover Org"))
        if await session.get(User, user_uuid) is None:
            session.add(User(id=user_uuid, username="recover"))
        await session.flush()
        scope = OrgScope(org_id=ORG, user_id=USER)
        job = await JobRepository(session, scope).create(kind="backtest", payload={"seed": True})
        return job.id


async def _make_stale_running(
    container: Container, job_id: uuid.UUID, *, attempts: int, heartbeat_age_minutes: int | None
) -> None:
    """把 job 置为 running 并伪造 attempts / heartbeat（模拟 worker 崩溃现场）。"""
    async with container.database.session() as session:
        job = await session.get(Job, job_id)
        assert job is not None
        job.status = JobStatus.RUNNING
        job.attempts = attempts
        job.locked_by = "qqlab-worker"
        job.started_at = datetime.now(tz=UTC) - timedelta(minutes=heartbeat_age_minutes or 30)
        if heartbeat_age_minutes is None:
            job.heartbeat_at = None  # mark_running 后、首个 progress 前崩溃
        else:
            job.heartbeat_at = datetime.now(tz=UTC) - timedelta(minutes=heartbeat_age_minutes)
        await session.commit()


async def _get(container: Container, job_id: uuid.UUID) -> Job | None:
    async with container.database.session() as session:
        return (await session.execute(select(Job).where(Job.id == job_id))).scalars().first()


@pytest.mark.asyncio
async def test_stale_running_requeued_when_attempts_remain(container: Container) -> None:
    """running + 心跳 > 阈值 + attempts < max → 回 queued（可再被消费）。"""
    job_id = await _seed(container)
    await _make_stale_running(container, job_id, attempts=1, heartbeat_age_minutes=30)
    async with container.database.session() as session:
        stats = await recover_stale_running_jobs(session, stale_minutes=10)
    assert stats["requeued"] == 1
    assert stats["failed"] == 0
    job = await _get(container, job_id)
    assert job is not None
    assert job.status == JobStatus.QUEUED
    assert job.locked_by is None
    assert job.heartbeat_at is None


@pytest.mark.asyncio
async def test_stale_running_failed_when_attempts_exhausted(container: Container) -> None:
    """running + 心跳 > 阈值 + attempts >= max → 落 failed（不无限重试）。"""
    job_id = await _seed(container)
    await _make_stale_running(container, job_id, attempts=3, heartbeat_age_minutes=30)
    async with container.database.session() as session:
        stats = await recover_stale_running_jobs(session, stale_minutes=10)
    assert stats["requeued"] == 0
    assert stats["failed"] == 1
    job = await _get(container, job_id)
    assert job is not None
    assert job.status == JobStatus.FAILED
    assert job.finished_at is not None


@pytest.mark.asyncio
async def test_fresh_running_untouched(container: Container) -> None:
    """running + 心跳新鲜（< 阈值）→ 不动（可能正被健康消费者持有）。"""
    job_id = await _seed(container)
    await _make_stale_running(container, job_id, attempts=1, heartbeat_age_minutes=1)
    async with container.database.session() as session:
        stats = await recover_stale_running_jobs(session, stale_minutes=10)
    assert stats == {"requeued": 0, "failed": 0}
    job = await _get(container, job_id)
    assert job is not None
    assert job.status == JobStatus.RUNNING


@pytest.mark.asyncio
async def test_running_null_heartbeat_treated_as_stale(container: Container) -> None:
    """mark_running 后、首个 progress 前崩溃（heartbeat 为 NULL）→ 视为陈旧，回收。"""
    job_id = await _seed(container)
    await _make_stale_running(container, job_id, attempts=1, heartbeat_age_minutes=None)
    async with container.database.session() as session:
        stats = await recover_stale_running_jobs(session, stale_minutes=10)
    assert stats["requeued"] == 1
    job = await _get(container, job_id)
    assert job is not None
    assert job.status == JobStatus.QUEUED


@pytest.mark.asyncio
async def test_queued_and_terminal_jobs_untouched(container: Container) -> None:
    """queued / succeeded / failed / canceled 均不受影响（只处理 running）。"""
    job_id = await _seed(container)
    # job 状态保持 queued（不调 _make_stale_running）
    async with container.database.session() as session:
        stats = await recover_stale_running_jobs(session, stale_minutes=10)
    assert stats == {"requeued": 0, "failed": 0}
    job = await _get(container, job_id)
    assert job is not None
    assert job.status == JobStatus.QUEUED


@pytest.mark.asyncio
async def test_no_jobs_at_all_no_error(container: Container) -> None:
    """空库调用不报错，返回全 0（worker 启动时数据库可能没有任何任务）。"""
    async with container.database.session() as session:
        stats = await recover_stale_running_jobs(session, stale_minutes=10)
    assert stats == {"requeued": 0, "failed": 0}
