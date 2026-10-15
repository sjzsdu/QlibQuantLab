"""任务只读服务（阶段 4 子集：列表 + 详情）。

完整任务中心（cancel / retry / 日志流 / SSE）属阶段 5；这里只提供
数据集导入进度轮询所需的最小读面，权限点 ``job.read``（人人可读，租户隔离）。
"""

from __future__ import annotations

from qqlab.core.errors import NotFoundError
from qqlab.core.tenant import OrgScope
from qqlab.models import Job
from qqlab.repositories import JobRepository
from qqlab.schemas import JobOut, PageOut


class JobQueryService:
    def __init__(self, *, session, scope: OrgScope) -> None:  # noqa: ANN001 - AsyncSession
        self._session = session
        self._scope = scope

    @staticmethod
    def _out(row: Job) -> JobOut:
        return JobOut(
            id=str(row.id),
            kind=row.kind,
            status=row.status,
            progress=row.progress,
            attempts=row.attempts,
            max_attempts=row.max_attempts,
            error=row.error,
            payload=dict(row.payload or {}),
            requested_by=row.requested_by,
            queued_at=row.queued_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
            created_at=row.created_at,
        )

    async def list(
        self, *, page: int, page_size: int, kind: str | None, status: str | None
    ) -> PageOut[JobOut]:
        repo = JobRepository(self._session, self._scope)
        rows, total = await repo.list(page=page, page_size=page_size, kind=kind, status=status)
        return PageOut[JobOut](
            items=[self._out(r) for r in rows], total=total, page=page, page_size=page_size
        )

    async def get(self, job_id: str) -> JobOut:
        row = await JobRepository(self._session, self._scope).get(job_id)
        if row is None:
            raise NotFoundError("任务不存在或不属于当前组织")
        return self._out(row)


__all__ = ["JobQueryService"]
