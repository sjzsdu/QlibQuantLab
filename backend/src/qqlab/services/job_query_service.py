"""任务服务：只读（列表 + 详情 + 增量日志）+ 任务中心控制（cancel / retry）。

取消语义（D5-f，双通道）：
- ``queued``：直接 CAS ``queued → canceled``（Core UPDATE ... WHERE status，原子）；
- ``running``：**绝不直接 UPDATE jobs**（worker 单事务持锁，S3-15）——置缓存标记
  ``job:{id}:cancel``，worker 在每个 progress 检查点协作式落 ``canceled``；
- 终态：409。

重试 = 复制 payload（追加 ``retry_of``）重新入队，原任务行不变。
"""

from __future__ import annotations

from qqlab.core.errors import ConflictError, NotFoundError
from qqlab.core.tenant import OrgScope
from qqlab.models import Job, JobStatus
from qqlab.ports.audit import AuditAction, AuditWriter
from qqlab.ports.auth import CurrentUser
from qqlab.repositories import JobRepository
from qqlab.schemas import JobActionOut, JobLogOut, JobLogsOut, JobOut, PageOut
from qqlab.services.base import AuditContext
from qqlab.services.job_service import JobService

#: running 取消标记 TTL（秒）：足够覆盖任意两次 progress 之间的间隔
CANCEL_FLAG_TTL = 6 * 3600

#: 单页日志条数上限
LOG_PAGE_LIMIT = 500

#: 终态（不可取消；仅 failed/canceled 可重试）
TERMINAL = (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELED)
RETRYABLE = (JobStatus.FAILED, JobStatus.CANCELED)


def cancel_flag_key(job_id: str) -> str:
    """running 协作式取消的缓存键（worker 与 API 的唯一约定）。"""
    return f"job:{job_id}:cancel"


class JobQueryService:
    def __init__(
        self,
        *,
        session,  # noqa: ANN001 - AsyncSession
        scope: OrgScope,
        container=None,  # noqa: ANN001 - Container（cancel/retry 需要 cache/queue）
        user: CurrentUser | None = None,
        audit: AuditWriter | None = None,
        ctx: AuditContext | None = None,
    ) -> None:
        self._session = session
        self._scope = scope
        self._container = container
        self._user = user
        self._audit = audit
        self._ctx = ctx

    def _require_control(self):  # noqa: ANN202
        if self._container is None or self._user is None or self._audit is None or self._ctx is None:
            raise RuntimeError("JobQueryService 未装配 container/user/audit，不能执行控制操作")
        return self._container, self._user, self._audit, self._ctx

    # ------------------------------------------------------------- 序列化
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

    # ------------------------------------------------------------- 读取
    async def list(
        self, *, page: int, page_size: int, kind: str | None, status: str | None
    ) -> PageOut[JobOut]:
        rows, total = await JobRepository(self._session, self._scope).list(
            page=page, page_size=page_size, kind=kind, status=status
        )
        return PageOut[JobOut](
            items=[self._out(r) for r in rows], total=total, page=page, page_size=page_size
        )

    async def get(self, job_id: str) -> JobOut:
        row = await JobRepository(self._session, self._scope).get(job_id)
        if row is None:
            raise NotFoundError("任务不存在或不属于当前组织")
        return self._out(row)

    async def logs(self, job_id: str, *, since_seq: int = 0, limit: int = 200) -> JobLogsOut:
        """增量日志 + 当前状态（一次轮询拿到「状态 + 新日志」）。"""
        limit = max(1, min(limit, LOG_PAGE_LIMIT))
        row = await JobRepository(self._session, self._scope).get(job_id)
        if row is None:
            raise NotFoundError("任务不存在或不属于当前组织")
        rows = await JobRepository(self._session, self._scope).list_logs(
            job_id, since_seq=since_seq, limit=limit
        )
        next_seq = max([since_seq] + [r.seq for r in rows])
        return JobLogsOut(
            items=[
                JobLogOut(seq=r.seq, level=r.level, message=r.message, created_at=r.created_at) for r in rows
            ],
            next_seq=next_seq,
            status=row.status,
            progress=row.progress,
        )

    # ------------------------------------------------------------- 控制
    async def cancel(self, job_id: str) -> JobActionOut:
        container, user, audit, ctx = self._require_control()
        repo = JobRepository(self._session, self._scope)
        row = await repo.get(job_id)
        if row is None:
            raise NotFoundError("任务不存在或不属于当前组织")
        # CAS 内部会 expire_all()，先固化审计所需字段（否则 status_before 会被刷成新值）
        rid, kind, before_status = str(row.id), row.kind, row.status
        if before_status in TERMINAL:
            raise ConflictError(f"任务已处于终态（{before_status}），无法取消")

        if before_status == JobStatus.QUEUED and await repo.mark_canceled_if_queued(
            job_id, reason="用户取消（排队阶段）"
        ):
            await repo.append_log(job_id, "canceled: 用户在排队阶段取消", level="warn")
            outcome = "canceled"
        else:
            # 读到 queued 但 CAS 失败 = worker 刚抢走；running 同走缓存标记
            await container.cache.set(cancel_flag_key(rid), b"1", ttl=CANCEL_FLAG_TTL)
            outcome = "cancel_requested"

        await audit.record(
            action=AuditAction.JOB_CANCEL,
            resource_type="job",
            resource_id=rid,
            detail={"kind": kind, "status_before": before_status, "outcome": outcome},
            user=user,
            request_id=ctx.request_id,
            ip=ctx.ip,
        )
        await self._session.commit()  # 显式提交（D4-8 read-your-writes）
        return JobActionOut(
            id=rid,
            status=outcome,
            detail="已取消" if outcome == "canceled" else "已置取消标记：任务将在下一个进度检查点停止",
        )

    async def retry(self, job_id: str) -> JobActionOut:
        container, user, audit, ctx = self._require_control()
        row = await JobRepository(self._session, self._scope).get(job_id)
        if row is None:
            raise NotFoundError("任务不存在或不属于当前组织")
        if row.status not in RETRYABLE:
            raise ConflictError(f"仅失败/已取消的任务可重试（当前 {row.status}）")

        jobs = JobService(container=container, scope=self._scope)
        new_id = await jobs.enqueue(
            kind=row.kind,
            payload={**dict(row.payload or {}), "retry_of": str(row.id)},
            requested_by=user.username,
            project_id=row.project_id,
            max_attempts=row.max_attempts,
        )
        await audit.record(
            action=AuditAction.JOB_RETRY,
            resource_type="job",
            resource_id=str(row.id),
            detail={"kind": row.kind, "retry_job_id": new_id, "status_before": row.status},
            user=user,
            request_id=ctx.request_id,
            ip=ctx.ip,
        )
        await self._session.commit()
        return JobActionOut(
            id=new_id,
            status="queued",
            detail=f"已复制任务 {row.id} 的 payload 重新入队",
        )


__all__ = ["CANCEL_FLAG_TTL", "JobQueryService", "cancel_flag_key"]
