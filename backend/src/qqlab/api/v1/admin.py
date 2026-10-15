"""管理端：成员管理与系统配置（均需 admin 权限）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from qqlab.api.deps import get_audit_ctx, get_db_session, require_permission, success
from qqlab.core.errors import ConfirmationRequiredError
from qqlab.core.tenant import OrgScope
from qqlab.ports.auth import CurrentUser
from qqlab.schemas import ConfigUpdateIn, MemberAddIn, MemberRoleUpdateIn
from qqlab.services import AdminService, AuditContext

router = APIRouter(tags=["admin"])


def _service(request: Request, session, user: CurrentUser, ctx: AuditContext) -> AdminService:
    return AdminService(
        session=session,
        scope=OrgScope(org_id=user.org_id, user_id=user.user_id, roles=user.roles),
        user=user,
        audit=request.app.state.container.audit,
        ctx=ctx,
    )


# ------------------------------------------------------------------ 成员
@router.get("/admin/members", summary="组织成员列表")
async def list_members(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user=Depends(require_permission("admin.member")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _service(request, session, user, ctx)
    return success(request, (await service.list_members(page=page, page_size=page_size)).model_dump())


@router.post("/admin/members", summary="添加成员")
async def add_member(
    request: Request,
    payload: MemberAddIn,
    user=Depends(require_permission("admin.member")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _service(request, session, user, ctx)
    member = await service.add_member(payload)
    return success(request, member.model_dump(), message="成员已添加")


@router.put("/admin/members/{user_id}/roles", summary="修改成员角色")
async def update_member_roles(
    request: Request,
    user_id: str,
    payload: MemberRoleUpdateIn,
    user=Depends(require_permission("admin.member")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _service(request, session, user, ctx)
    member = await service.update_member_roles(user_id, payload.roles)
    return success(request, member.model_dump(), message="角色已更新")


@router.delete("/admin/members/{user_id}", summary="移除成员（二次确认）")
async def remove_member(
    request: Request,
    user_id: str,
    confirm: bool = Query(False),
    user=Depends(require_permission("admin.member")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    if not confirm:
        raise ConfirmationRequiredError("admin.member.remove")
    service = _service(request, session, user, ctx)
    removed = await service.remove_member(user_id, confirm=confirm)
    return success(request, {"removed": removed}, message="成员已移除")


# ------------------------------------------------------------ 系统配置
@router.get("/admin/config", summary="系统配置列表（机密值脱敏）")
async def list_config(
    request: Request,
    user=Depends(require_permission("admin.config")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _service(request, session, user, ctx)
    rows = await service.list_configs(redact=True)
    return success(request, [row.model_dump() for row in rows])


@router.put("/admin/config/{config_key}", summary="写入系统配置")
async def update_config(
    request: Request,
    config_key: str,
    payload: ConfigUpdateIn,
    user=Depends(require_permission("admin.config")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _service(request, session, user, ctx)
    row = await service.update_config(config_key, payload)
    return success(request, row.model_dump(), message="配置已保存")
