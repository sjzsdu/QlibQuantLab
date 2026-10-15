"""JobService 入队两阶段单测（memory MQ + SQLite，零外部依赖）。

回归阶段 3 live smoke 实测的根因缺口：``JobRepository.create`` 只落库、
**从不发布 MQ 消息** —— 直接调它的入队会让 job 永远停在 queued（A3-4 卡住）。
入队唯一路径必须是 ``JobService.enqueue``：落库提交 → 发布 ``kind`` + ``job_id``。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from conftest import make_settings
from qqlab.container import Container
from qqlab.core.ids import stable_uuid
from qqlab.core.tenant import OrgScope
from qqlab.models import Job, JobKind, JobStatus
from qqlab.ports.message_queue import JOB_QUEUE
from qqlab.services.job_service import JobService

ORG = "dev-org"
USER = "dev-user"


@pytest.fixture
async def settings(tmp_path: Path):
    # 独立 DB：共享 TEST_DB_URL 会与既有测试的 queued job 撞 uq_jobs_org_hash_status
    s = make_settings(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'jobsvc.db'}",
        QLIB_DATA_ROOT=str(tmp_path / "qlib_data"),
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


@pytest.fixture
def scope() -> OrgScope:
    return OrgScope(org_id=ORG, user_id=USER)


async def test_enqueue_persists_row_then_publishes_message(container: Container, scope: OrgScope) -> None:
    svc = JobService(container=container, scope=scope)
    job_id = await svc.enqueue(
        kind=JobKind.DATASET_IMPORT,
        payload={"region": "cn"},
        requested_by="unit-test",
    )

    # 1) 行已提交（独立会话可见）—— repository 注入 org_key / created_by / payload_hash
    async with container.database.session() as session:
        job = await session.get(Job, uuid.UUID(job_id))
    assert job is not None
    assert job.status == JobStatus.QUEUED
    assert job.kind == JobKind.DATASET_IMPORT
    assert (job.payload or {}).get("org_key") == ORG
    assert (job.payload or {}).get("region") == "cn"
    assert job.payload_hash
    assert job.created_by == stable_uuid(USER)
    assert job.requested_by == "unit-test"

    # 2) 消息已入队且只含 kind + job_id（job 行是权威）
    assert container.queue.pending(JOB_QUEUE) == 1
    received: dict = {}

    async def _capture(msg) -> None:  # noqa: ANN001 - memory MQ Message
        received.update(json.loads(msg.body.decode("utf-8")))

    assert await container.queue.drain(JOB_QUEUE, _capture) == 1
    assert received == {"kind": JobKind.DATASET_IMPORT, "job_id": job_id}


async def test_enqueue_publishes_after_commit(container: Container, scope: OrgScope) -> None:
    """时序：消息被消费时 job 行必须已可见（否则 worker 会 nack 丢弃）。"""
    svc = JobService(container=container, scope=scope)
    job_id = await svc.enqueue(kind=JobKind.BACKTEST, payload={"backtest_id": uuid.uuid4().hex})

    seen: dict = {}

    async def _consume(msg) -> None:  # noqa: ANN001
        async with container.database.session() as session:
            job = await session.get(Job, uuid.UUID(str(json.loads(msg.body.decode())["job_id"])))
        seen["found"] = job is not None
        seen["status"] = job.status if job else None

    await container.queue.drain(JOB_QUEUE, _consume)
    assert seen == {"found": True, "status": JobStatus.QUEUED}
    assert seen["found"] is True and str(job_id)  # job_id 已发布


async def test_worker_and_service_share_queue_name(settings, container: Container) -> None:
    """worker 默认消费队列与 JobService 发布队列必须是同一个（防命名漂移）。"""
    from qqlab.worker.main import Worker

    assert Worker(settings, container).queue_name == JOB_QUEUE == "qqlab_jobs"
