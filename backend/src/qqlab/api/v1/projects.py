"""项目 CRUD（阶段 2 范围：为阶段 4 打底，同时验证租户隔离）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from qqlab.api.deps import (
    get_audit_ctx,
    get_db_session,
    require_permission,
    success,
)
from qqlab.core.errors import ConfirmationRequiredError
from qqlab.core.tenant import OrgScope
from qqlab.ports.auth import CurrentUser
from qqlab.schemas import OkOut, ProjectCreateIn, ProjectUpdateIn
from qqlab.services import AuditContext, ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


def _service(request: Request, session, user: CurrentUser, ctx: AuditContext):  # noqa: ANN001
    return ProjectService(
        session=session,
        scope=OrgScope(org_id=user.org_id, user_id=user.user_id, roles=user.roles),
        user=user,
        audit=request.app.state.container.audit,
        ctx=ctx,
    )


@router.get("", summary="项目列表（仅当前组织）")
async def list_projects(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, max_length=100),
    user=Depends(require_permission("project.read")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _service(request, session, user, ctx)
    page_out = await service.list(page=page, page_size=page_size, keyword=keyword)
    return success(request, page_out.model_dump())


@router.post("", summary="新建项目（默认私有）")
async def create_project(
    request: Request,
    payload: ProjectCreateIn,
    user=Depends(require_permission("project.write")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _service(request, session, user, ctx)
    project = await service.create(payload)
    return success(request, project.model_dump(), message="项目已创建")


@router.get("/{project_id}", summary="项目详情")
async def get_project(
    request: Request,
    project_id: str,
    user=Depends(require_permission("project.read")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _service(request, session, user, ctx)
    return success(request, (await service.get(project_id)).model_dump())


@router.patch("/{project_id}", summary="更新项目")
async def update_project(
    request: Request,
    project_id: str,
    payload: ProjectUpdateIn,
    user=Depends(require_permission("project.write")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _service(request, session, user, ctx)
    project = await service.update(project_id, payload)
    return success(request, project.model_dump(), message="项目已更新")


@router.delete("/{project_id}", summary="删除项目（二次确认）")
async def delete_project(
    request: Request,
    project_id: str,
    confirm: bool = Query(False, description="高危操作需传 confirm=true"),
    user=Depends(require_permission("project.delete")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    if not confirm:
        raise ConfirmationRequiredError("project.delete")
    service = _service(request, session, user, ctx)
    deleted_id = await service.delete(project_id, confirm=confirm)
    return success(request, OkOut(deleted=True, id=deleted_id).model_dump(), message="项目已删除")
