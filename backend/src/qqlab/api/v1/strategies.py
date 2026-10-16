"""策略 API（阶段 5）：信号配置 CRUD + 绑定模型 + 公开发布（二次确认）。"""

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
from qqlab.schemas import StrategyCreateIn, StrategyUpdateIn
from qqlab.services import AuditContext, StrategyService

router = APIRouter(prefix="/strategies", tags=["strategies"])


def _service(session, user: CurrentUser, ctx: AuditContext, container: Container) -> StrategyService:
    return StrategyService(
        session=session,
        scope=OrgScope(org_id=user.org_id, user_id=user.user_id, roles=user.roles),
        user=user,
        audit=container.audit,
        ctx=ctx,
    )


@router.get("", summary="策略列表")
async def list_strategies(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, max_length=100),
    project_id: str | None = Query(None, max_length=64),
    user=Depends(require_permission("strategy.read")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
    container=Depends(get_container),
) -> dict:
    service = _service(session, user, ctx, container)
    result = await service.list(page=page, page_size=page_size, keyword=keyword, project_id=project_id)
    return success(request, result.model_dump())


@router.post("", summary="创建策略（rule | model 信号源）")
async def create_strategy(
    request: Request,
    payload: StrategyCreateIn,
    user=Depends(require_permission("strategy.write")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
    container=Depends(get_container),
) -> dict:
    service = _service(session, user, ctx, container)
    row = await service.create(payload)
    return success(request, row.model_dump(), message="策略已创建")


@router.get("/{strategy_id}", summary="策略详情")
async def get_strategy(
    request: Request,
    strategy_id: str,
    user=Depends(require_permission("strategy.read")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
    container=Depends(get_container),
) -> dict:
    service = _service(session, user, ctx, container)
    return success(request, (await service.get(strategy_id)).model_dump())


@router.patch("/{strategy_id}", summary="修改策略（信号源/绑定/名称）")
async def update_strategy(
    request: Request,
    strategy_id: str,
    payload: StrategyUpdateIn,
    user=Depends(require_permission("strategy.write")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
    container=Depends(get_container),
) -> dict:
    service = _service(session, user, ctx, container)
    row = await service.update(strategy_id, payload)
    return success(request, row.model_dump(), message="策略已更新")


@router.post("/{strategy_id}/publish", summary="公开策略（二次确认）")
async def publish_strategy(
    request: Request,
    strategy_id: str,
    confirm: bool = Query(False),
    user=Depends(require_permission("strategy.publish")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
    container=Depends(get_container),
) -> dict:
    service = _service(session, user, ctx, container)
    row = await service.publish(strategy_id, confirm=confirm)
    return success(request, row.model_dump(), message="策略已发布")


__all__ = ["router"]
