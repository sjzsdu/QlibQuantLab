"""任务入队编排：写 job 行（提交）→ 发布 MQ 消息。**唯一入队路径**。

两阶段顺序是硬约束：``JobRepository.create`` 只落库不发消息，本服务在
session 提交**之后**才 ``publish`` —— 消息永远不早于 job 行存在，否则
worker 查不到 job 会 nack 丢弃（阶段 3 live smoke 实测踩过的坑）。

消息体只含 ``kind`` + ``job_id``：job 行才是权威（org_key / payload 从行上读，
见 ``qqlab.worker.handlers.base.run_job``）。publish 失败时 job 停在 queued
（可重投），本阶段不做 outbox —— 见 docs/stage3/06-risks。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from qqlab.ports.message_queue import JOB_QUEUE
from qqlab.repositories.job import JobRepository

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    import uuid

    from qqlab.container import Container
    from qqlab.core.tenant import OrgScope

__all__ = ["JOB_QUEUE", "JobService"]


class JobService:
    def __init__(self, *, container: Container, scope: OrgScope) -> None:
        self._container = container
        self._scope = scope

    async def enqueue(
        self,
        *,
        kind: str,
        payload: dict,
        requested_by: str = "",
        project_id: str | uuid.UUID | None = None,
        max_attempts: int = 3,
    ) -> str:
        """入队一个任务：落库（org_key/payload_hash 由 repository 注入）→ 发布消息。

        返回 job id。``payload`` 无需包含 ``org_key``（repository 从 scope 注入）。
        """
        async with self._container.database.session() as session:
            job = await JobRepository(session, self._scope).create(
                kind=kind,
                payload=payload,
                project_id=project_id,
                requested_by=requested_by,
                max_attempts=max_attempts,
            )
            job_id = str(job.id)
        # session 退出即 commit —— 行先于消息可见
        body = json.dumps({"kind": kind, "job_id": job_id}, ensure_ascii=False).encode("utf-8")
        await self._container.queue.publish(JOB_QUEUE, body)
        return job_id
