"""审计日志查询与导出（admin / auditor 可读，仅本组织）。"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from qqlab.api.deps import (
    get_db_session,
    get_scope,
    require_permission,
    success,
)
from qqlab.core.errors import ConfirmationRequiredError
from qqlab.core.tenant import OrgScope
from qqlab.ports.audit import AuditAction
from qqlab.services import AuditService

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", summary="审计日志列表")
async def list_audit_logs(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    action: str | None = Query(None, max_length=64),
    actor: str | None = Query(None, max_length=120),
    outcome: str | None = Query(None, max_length=16),
    scope: OrgScope = Depends(get_scope),
    _user=Depends(require_permission("audit.read")),
    session=Depends(get_db_session),
) -> dict:
    service = AuditService(session, scope)
    page_out = await service.list(page=page, page_size=page_size, action=action, actor=actor, outcome=outcome)
    return success(request, page_out.model_dump())


@router.get("/actions", summary="出现过的审计动作（筛选下拉用）")
async def audit_actions(
    request: Request,
    scope: OrgScope = Depends(get_scope),
    _user=Depends(require_permission("audit.read")),
    session=Depends(get_db_session),
) -> dict:
    service = AuditService(session, scope)
    return success(request, await service.actions())


@router.get("/export", summary="审计日志导出 CSV（二次确认 + 记审计）")
async def export_audit_logs(
    request: Request,
    format: str = Query("csv", pattern="^(csv)$", description="仅支持 csv"),
    confirm: bool = Query(False, description="导出属敏感操作，需传 confirm=true"),
    action: str | None = Query(None, max_length=64),
    actor: str | None = Query(None, max_length=120),
    outcome: str | None = Query(None, max_length=16),
    scope: OrgScope = Depends(get_scope),
    user=Depends(require_permission("audit.export")),
    session=Depends(get_db_session),
) -> StreamingResponse:
    if not confirm:
        raise ConfirmationRequiredError("audit.export")

    container = request.app.state.container
    await container.audit.record(
        action=AuditAction.AUDIT_EXPORT,
        resource_type="audit_log",
        resource_id=None,
        detail={
            "filters": {"action": action, "actor": actor, "outcome": outcome},
            "format": format,
        },
        user=user,
        request_id=getattr(request.state, "request_id", None),
        ip=request.client.host if request.client else None,
        org_id=scope.org_id,
    )

    service = AuditService(session, scope)
    filename = f"audit_logs_{datetime.now(tz=UTC).strftime('%Y%m%d_%H%M%S')}.csv"

    async def _generate():
        async for chunk in service.stream_csv(action=action, actor=actor, outcome=outcome):
            yield chunk

    return StreamingResponse(
        _generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
