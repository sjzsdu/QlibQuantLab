"""任务 API（阶段 4 读取子集 + 阶段 5 任务中心）：列表 / 详情 / 增量日志 / cancel / retry。

轮询约定（阶段 5，不做 SSE）：前端每 2s 拉 ``GET /jobs/{id}/logs?since_seq=N``，
一次拿「当前状态 + 新日志」；``next_seq`` 供下次请求。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from qqlab.api.deps import (
    get_audit_ctx,
    get_container,
    get_db_session,
    require_permission,
    success,
)
from qqlab.container import Container
from qqlab.core.tenant import OrgScope
from qqlab.ports.auth import CurrentUser
from qqlab.services import AuditContext, JobQueryService

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _service(
    session,
    user: CurrentUser,
    ctx: AuditContext | None = None,
    container: Container | None = None,
) -> JobQueryService:
    return JobQueryService(
        session=session,
        scope=OrgScope(org_id=user.org_id, user_id=user.user_id, roles=user.roles),
        container=container,
        user=user,
        audit=container.audit if container is not None else None,
        ctx=ctx,
    )


@router.get("", summary="任务列表（仅当前组织）")
async def list_jobs(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    kind: str | None = Query(None, max_length=32),
    status: str | None = Query(None, max_length=16),
    user=Depends(require_permission("job.read")),
    session=Depends(get_db_session),
) -> dict:
    service = _service(session, user)
    page_out = await service.list(page=page, page_size=page_size, kind=kind, status=status)
    return success(request, page_out.model_dump())


@router.get("/{job_id}", summary="任务详情（轮询导入进度用）")
async def get_job(
    request: Request,
    job_id: str,
    user=Depends(require_permission("job.read")),
    session=Depends(get_db_session),
) -> dict:
    service = _service(session, user)
    return success(request, (await service.get(job_id)).model_dump())


@router.get("/{job_id}/logs", summary="任务增量日志 + 当前状态")
async def get_job_logs(
    request: Request,
    job_id: str,
    since_seq: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    user=Depends(require_permission("job.read")),
    session=Depends(get_db_session),
) -> dict:
    service = _service(session, user)
    result = await service.logs(job_id, since_seq=since_seq, limit=limit)
    return success(request, result.model_dump())


@router.post("/{job_id}/cancel", summary="取消任务（queued 直接取消 / running 协作式）")
async def cancel_job(
    request: Request,
    job_id: str,
    user=Depends(require_permission("job.control")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
    container=Depends(get_container),
) -> dict:
    service = _service(session, user, ctx, container)
    result = await service.cancel(job_id)
    return success(request, result.model_dump(), message="取消请求已受理")


@router.post("/{job_id}/retry", summary="重试任务（复制 payload 重新入队）")
async def retry_job(
    request: Request,
    job_id: str,
    user=Depends(require_permission("job.control")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
    container=Depends(get_container),
) -> dict:
    service = _service(session, user, ctx, container)
    result = await service.retry(job_id)
    return success(request, result.model_dump(), message="已重新入队")


__all__ = ["router"]
