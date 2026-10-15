"""任务只读 API（阶段 4 子集：列表 + 详情，支撑导入进度轮询）。

cancel / retry / 日志流 / SSE 属阶段 5（任务中心）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from qqlab.api.deps import get_db_session, require_permission, success
from qqlab.core.tenant import OrgScope
from qqlab.ports.auth import CurrentUser
from qqlab.services import JobQueryService

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _service(session, user: CurrentUser):  # noqa: ANN001
    return JobQueryService(
        session=session,
        scope=OrgScope(org_id=user.org_id, user_id=user.user_id, roles=user.roles),
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


__all__ = ["router"]
