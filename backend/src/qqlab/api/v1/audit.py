"""审计日志查询（admin / auditor 可读，仅本组织）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from qqlab.api.deps import get_db_session, get_scope, require_permission, success
from qqlab.core.tenant import OrgScope
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
