"""审计查询服务（只读）+ CSV 导出流。"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from qqlab.core.tenant import OrgScope
from qqlab.repositories import AuditRepository
from qqlab.schemas import AuditLogOut, PageOut

#: 导出 CSV 列（与 API 文档一致；detail 为 JSON 单列）
EXPORT_COLUMNS = (
    "created_at",
    "action",
    "resource_type",
    "resource_id",
    "outcome",
    "actor_username",
    "ip",
    "user_agent",
    "request_id",
    "detail",
)


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

    async def stream_csv(
        self,
        *,
        action: str | None = None,
        actor: str | None = None,
        outcome: str | None = None,
        batch: int = 500,
    ) -> AsyncIterator[str]:
        """流式导出 CSV（键集分页，边查边发，全量也不占内存）。

        生成器在响应流内运行，FastAPI 的 ``yield`` 依赖 session 到流结束才关闭
        （已在阶段 6 实证：teardown 发生在 generator 完成之后）。
        """
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(EXPORT_COLUMNS)
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)

        cursor: tuple[datetime, str] | None = None
        while True:
            rows = await self._repo.page_for_export(
                after=cursor, batch=batch, action=action, actor=actor, outcome=outcome
            )
            if not rows:
                break
            for r in rows:
                writer.writerow(
                    [
                        r.created_at.isoformat(),
                        r.action,
                        r.resource_type,
                        r.resource_id or "",
                        r.outcome,
                        r.actor_username,
                        r.ip or "",
                        r.user_agent or "",
                        r.request_id or "",
                        json.dumps(dict(r.detail or {}), ensure_ascii=False, separators=(",", ":")),
                    ]
                )
                cursor = (r.created_at, str(r.id))
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
            if len(rows) < batch:
                break


__all__ = ["AuditService"]
