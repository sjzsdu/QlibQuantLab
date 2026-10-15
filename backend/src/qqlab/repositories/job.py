"""任务仓库：jobs / job_logs / backtests 的读写（**强制租户过滤**）。

worker 处理任务时同样受租户边界约束：job 按 org_id 读取，
跨租户读到 None 即失败（handler 会把任务标记为 failed）。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from qqlab.core.ids import stable_uuid
from qqlab.models import Backtest, Job, JobLog, JobStatus
from qqlab.repositories.base import BaseRepository

WORKER_ID = "qqlab-worker"


def payload_hash(kind: str, payload: dict) -> str:
    raw = json.dumps({"kind": kind, "payload": payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


class JobRepository(BaseRepository):
    def _base(self):  # noqa: ANN202
        return select(Job).where(Job.org_id == stable_uuid(self.scope.org_id))

    async def create(
        self,
        *,
        kind: str,
        payload: dict,
        project_id: str | uuid.UUID | None = None,
        requested_by: str = "",
        max_attempts: int = 3,
        created_by: str | uuid.UUID | None = None,
    ) -> Job:
        """入队一条任务。

        ``payload["org_key"]`` 由本方法从 scope 注入（外部 org 串，如 ``dev-org``）：
        worker 用它派生 Qlib 数据目录与对象存储键（与 API 层同源），
        并在执行前校验 ``stable_uuid(org_key) == job.org_id``，防止串租户。
        ``created_by`` 缺省取 scope.user_id（外部用户串 → users.id）。
        """
        full_payload = {**payload, "org_key": self.scope.org_id}
        job = Job(
            org_id=stable_uuid(self.scope.org_id),
            created_by=stable_uuid(created_by or self.scope.user_id),
            project_id=uuid.UUID(str(project_id)) if project_id else None,
            kind=kind,
            status=JobStatus.QUEUED,
            payload=full_payload,
            requested_by=requested_by,
            max_attempts=max_attempts,
            payload_hash=payload_hash(kind, full_payload),
            queued_at=datetime.now(tz=UTC),
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get(self, job_id: str | uuid.UUID) -> Job | None:
        try:
            jid = uuid.UUID(str(job_id))
        except ValueError:
            return None
        return (await self.session.execute(self._base().where(Job.id == jid))).scalars().first()

    async def find_by_hash(self, kind: str, payload: dict, *, status: str) -> Job | None:
        # 与 create() 同源：哈希按注入 org_key 后的 payload 计算
        h = payload_hash(kind, {**payload, "org_key": self.scope.org_id})
        stmt = self._base().where(Job.kind == kind, Job.payload_hash == h, Job.status == status)
        return (await self.session.execute(stmt)).scalars().first()

    async def count(self, *, status: str | None = None, kind: str | None = None) -> int:
        stmt = select(func.count()).select_from(Job).where(Job.org_id == stable_uuid(self.scope.org_id))
        if status:
            stmt = stmt.where(Job.status == status)
        if kind:
            stmt = stmt.where(Job.kind == kind)
        return int((await self.session.execute(stmt)).scalar_one())

    async def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        kind: str | None = None,
        status: str | None = None,
    ) -> tuple[list[Job], int]:
        """分页列举任务（阶段 4 只读子集；供 UI 轮询导入进度）。"""
        offset, limit = self.page_offsets(page, page_size)
        stmt = self._base()
        if kind:
            stmt = stmt.where(Job.kind == kind)
        if status:
            stmt = stmt.where(Job.status == status)
        total = int(
            (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        )
        rows = (
            (await self.session.execute(stmt.order_by(Job.created_at.desc()).offset(offset).limit(limit)))
            .scalars()
            .all()
        )
        return list(rows), total

    async def mark_running(self, job_id: str | uuid.UUID) -> bool:
        """queued → running 的比较并交换（attempts 自增，带心跳时间）。"""
        job = await self.get(job_id)
        if job is None or job.status != JobStatus.QUEUED:
            return False
        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.locked_by = WORKER_ID
        job.started_at = job.started_at or datetime.now(tz=UTC)
        job.heartbeat_at = datetime.now(tz=UTC)
        await self.session.flush()
        return True

    async def heartbeat(self, job_id: str | uuid.UUID, *, progress: int | None = None) -> None:
        job = await self.get(job_id)
        if job is None:
            return
        job.heartbeat_at = datetime.now(tz=UTC)
        if progress is not None:
            job.progress = max(0, min(100, int(progress)))
        await self.session.flush()

    async def mark_succeeded(self, job_id: str | uuid.UUID, *, log_uri: str | None = None) -> None:
        job = await self.get(job_id)
        if job is None:
            return
        job.status = JobStatus.SUCCEEDED
        job.progress = 100
        job.error = None
        job.log_uri = log_uri or job.log_uri
        job.finished_at = datetime.now(tz=UTC)
        await self.session.flush()

    async def mark_failed(self, job_id: str | uuid.UUID, error: str) -> None:
        job = await self.get(job_id)
        if job is None:
            return
        job.status = JobStatus.FAILED
        job.error = error[:4000]
        job.finished_at = datetime.now(tz=UTC)
        await self.session.flush()

    async def append_log(self, job_id: str | uuid.UUID, message: str, *, level: str = "info") -> None:
        jid = uuid.UUID(str(job_id))
        seq = int(
            (
                await self.session.execute(
                    select(func.coalesce(func.max(JobLog.seq), -1)).where(JobLog.job_id == jid)
                )
            ).scalar_one()
            + 1
        )
        self.session.add(
            JobLog(
                org_id=stable_uuid(self.scope.org_id),
                job_id=jid,
                seq=seq,
                level=level,
                message=message[:4000],
            )
        )
        await self.session.flush()


class BacktestRepository(BaseRepository):
    def _base(self):  # noqa: ANN202
        return select(Backtest).where(Backtest.org_id == stable_uuid(self.scope.org_id))

    async def get(self, backtest_id: str | uuid.UUID) -> Backtest | None:
        try:
            bid = uuid.UUID(str(backtest_id))
        except ValueError:
            return None
        return (await self.session.execute(self._base().where(Backtest.id == bid))).scalars().first()

    async def save_result(
        self,
        backtest_id: str | uuid.UUID,
        *,
        metrics: dict,
        data_range: dict,
        limitations: str,
        curve_uri: str | None,
        job_id: str | uuid.UUID | None = None,
    ) -> None:
        bt = await self.get(backtest_id)
        if bt is None:
            return
        bt.metrics = metrics
        bt.data_range = data_range
        bt.limitations = limitations
        bt.curve_uri = curve_uri or bt.curve_uri
        if job_id is not None:
            bt.job_id = uuid.UUID(str(job_id))
        await self.session.flush()


__all__ = ["BacktestRepository", "JobRepository", "WORKER_ID", "payload_hash"]
