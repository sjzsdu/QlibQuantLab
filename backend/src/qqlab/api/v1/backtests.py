"""回测 API（阶段 5 提交/曲线 + 阶段 6 导出）：提交（费用三件套必填）+ 列表 / 详情 / 净值曲线 / 导出 CSV。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from qqlab.api.deps import (
    get_audit_ctx,
    get_container,
    get_db_session,
    require_permission,
    success,
)
from qqlab.container import Container
from qqlab.core.errors import ConfirmationRequiredError
from qqlab.core.tenant import OrgScope
from qqlab.ports.audit import AuditAction
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
        settings=container.settings,
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


@router.get("/{backtest_id}/export", summary="回测导出 CSV（报告/持仓明细，二次确认 + 记审计）")
async def export_backtest(
    request: Request,
    backtest_id: str,
    section: str = Query("report", pattern="^(report|positions)$", description="报告或持仓明细"),
    format: str = Query("csv", pattern="^(csv)$", description="仅支持 csv"),
    confirm: bool = Query(False, description="导出属敏感操作，需传 confirm=true"),
    user=Depends(require_permission("backtest.export")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
    container=Depends(get_container),
) -> StreamingResponse:
    if not confirm:
        raise ConfirmationRequiredError("backtest.export")

    service = _service(session, user, ctx, container)
    # 先取数据（404/400/422 在此抛出）再记审计 —— 只有真正拿到内容才算导出成功
    filename, payload = await service.export_csv(backtest_id, section=section)
    await container.audit.record(
        action=AuditAction.BACKTEST_EXPORT,
        resource_type="backtest",
        resource_id=backtest_id,
        detail={"section": section, "format": format, "bytes": len(payload)},
        user=user,
        request_id=getattr(request.state, "request_id", None),
        ip=request.client.host if request.client else None,
        org_id=user.org_id,
    )

    def _chunks(data: bytes, size: int = 64 * 1024):
        for offset in range(0, len(data), size):
            yield data[offset : offset + size]

    return StreamingResponse(
        _chunks(payload),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


__all__ = ["router"]
