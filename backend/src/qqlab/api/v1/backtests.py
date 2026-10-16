"""回测 API（阶段 5）：提交（费用三件套必填）+ 列表 / 详情 / 净值曲线。"""

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
from qqlab.schemas import BacktestCreateIn, BacktestOut, CurveOut, PageOut
from qqlab.services import AuditContext, BacktestService, JobService

router = APIRouter(prefix="/backtests", tags=["backtests"])


def _service(session, user: CurrentUser, ctx: AuditContext, container: Container) -> BacktestService:
    return BacktestService(
        session=session,
        scope=OrgScope(org_id=user.org_id, user_id=user.user_id, roles=user.roles),
        user=user,
        audit=container.audit,
        ctx=ctx,
        storage=container.storage,
    )


@router.get("", summary="回测列表")
async def list_backtests(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    strategy_id: str | None = Query(None, max_length=64),
    project_id: str | None = Query(None, max_length=64),
    user=Depends(require_permission("backtest.read")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
    container=Depends(get_container),
) -> dict:
    service = _service(session, user, ctx, container)
    result: PageOut[BacktestOut] = await service.list(
        page=page, page_size=page_size, strategy_id=strategy_id, project_id=project_id
    )
    return success(request, result.model_dump())


@router.post("", summary="提交回测（费用三件套必填）")
async def submit_backtest(
    request: Request,
    payload: BacktestCreateIn,
    user=Depends(require_permission("backtest.submit")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
    container=Depends(get_container),
) -> dict:
    service = _service(session, user, ctx, container)
    jobs = JobService(
        container=container,
        scope=OrgScope(org_id=user.org_id, user_id=user.user_id, roles=user.roles),
    )
    row = await service.submit(payload, job_service=jobs)
    return success(request, row.model_dump(), message="回测任务已入队")


@router.get("/{backtest_id}", summary="回测详情（含四标注）")
async def get_backtest(
    request: Request,
    backtest_id: str,
    user=Depends(require_permission("backtest.read")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
    container=Depends(get_container),
) -> dict:
    service = _service(session, user, ctx, container)
    return success(request, (await service.get(backtest_id)).model_dump())


@router.get("/{backtest_id}/curve", summary="净值曲线（降采样 ≤1500 点）")
async def get_backtest_curve(
    request: Request,
    backtest_id: str,
    user=Depends(require_permission("backtest.read")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
    container=Depends(get_container),
) -> dict:
    service = _service(session, user, ctx, container)
    curve: CurveOut = await service.curve(backtest_id)
    return success(request, curve.model_dump())


__all__ = ["router"]
