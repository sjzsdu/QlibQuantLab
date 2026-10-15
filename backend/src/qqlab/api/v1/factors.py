"""因子 API：表达式 CRUD + 静态校验 + 发布（阶段 4 范围，不含计算）。"""

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
from qqlab.schemas import ExpressionCheckIn, ExpressionCheckOut, FactorCreateIn, FactorUpdateIn, OkOut
from qqlab.services import AuditContext, FactorService

router = APIRouter(prefix="/factors", tags=["factors"])


def _service(request: Request, session, user: CurrentUser, ctx: AuditContext):  # noqa: ANN001
    return FactorService(
        session=session,
        scope=OrgScope(org_id=user.org_id, user_id=user.user_id, roles=user.roles),
        user=user,
        audit=request.app.state.container.audit,
        ctx=ctx,
    )


@router.get("", summary="因子列表")
async def list_factors(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, max_length=100),
    project_id: str | None = Query(None),
    user=Depends(require_permission("factor.read")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _service(request, session, user, ctx)
    page_out = await service.list(page=page, page_size=page_size, keyword=keyword, project_id=project_id)
    return success(request, page_out.model_dump())


@router.post("", summary="新建因子（表达式静态校验）")
async def create_factor(
    request: Request,
    payload: FactorCreateIn,
    user=Depends(require_permission("factor.write")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _service(request, session, user, ctx)
    factor = await service.create(payload)
    return success(request, factor.model_dump(), message="因子已创建")


@router.post("/validate", summary="表达式静态校验（不落库）")
async def validate_expression(
    request: Request,
    payload: ExpressionCheckIn,
    user=Depends(require_permission("factor.read")),
) -> dict:
    result: ExpressionCheckOut = FactorService.check(payload.expression)
    return success(request, result.model_dump())


@router.get("/{factor_id}", summary="因子详情")
async def get_factor(
    request: Request,
    factor_id: str,
    user=Depends(require_permission("factor.read")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _service(request, session, user, ctx)
    return success(request, (await service.get(factor_id)).model_dump())


@router.patch("/{factor_id}", summary="更新因子（表达式变更 → version+1）")
async def update_factor(
    request: Request,
    factor_id: str,
    payload: FactorUpdateIn,
    user=Depends(require_permission("factor.write")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _service(request, session, user, ctx)
    factor = await service.update(factor_id, payload)
    return success(request, factor.model_dump(), message="因子已更新")


@router.delete("/{factor_id}", summary="删除因子（二次确认）")
async def delete_factor(
    request: Request,
    factor_id: str,
    confirm: bool = Query(False, description="高危操作需传 confirm=true"),
    user=Depends(require_permission("resource.delete")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    if not confirm:
        raise ConfirmationRequiredError("factor.delete")
    service = _service(request, session, user, ctx)
    deleted = await service.delete(factor_id, confirm=confirm)
    return success(request, OkOut(deleted=deleted).model_dump(), message="因子已删除")


@router.post("/{factor_id}/publish", summary="发布因子（visibility→public，二次确认）")
async def publish_factor(
    request: Request,
    factor_id: str,
    confirm: bool = Query(False, description="高危操作需传 confirm=true"),
    user=Depends(require_permission("factor.publish")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _service(request, session, user, ctx)
    factor = await service.publish(factor_id, confirm=confirm)
    return success(request, factor.model_dump(), message="因子已发布")


__all__ = ["router"]
