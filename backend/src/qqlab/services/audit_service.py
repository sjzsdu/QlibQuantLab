"""审计查询服务（只读）。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from qqlab.core.tenant import OrgScope
from qqlab.repositories import AuditRepository
from qqlab.schemas import AuditLogOut, PageOut


class AuditService:
    def __init__(self, session: AsyncSession, scope: OrgScope) -> None:
        self._repo = AuditRepository(session, scope.org_id)

    async def list(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        action: str | None = None,
        actor: str | None = None,
        outcome: str | None = None,
    ) -> PageOut[AuditLogOut]:
        rows, total = await self._repo.list(
            page=page, page_size=page_size, action=action, actor=actor, outcome=outcome
        )
        return PageOut(
            items=[
                AuditLogOut(
                    id=str(r.id),
                    action=r.action,
                    resource_type=r.resource_type,
                    resource_id=r.resource_id,
                    outcome=r.outcome,
                    actor_username=r.actor_username,
                    detail=dict(r.detail or {}),
                    ip=r.ip,
                    request_id=r.request_id,
                    created_at=r.created_at,
                )
                for r in rows
            ],
            total=total,
            page=max(1, page),
            page_size=min(max(1, page_size), 200),
        )

    async def actions(self) -> list[str]:
        return await self._repo.distinct_actions()


__all__ = ["AuditService"]
