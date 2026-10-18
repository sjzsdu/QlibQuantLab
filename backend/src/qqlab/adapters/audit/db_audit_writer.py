"""审计落库适配器（写 audit_logs 表）。

审计失败**绝不能**影响主流程：异常只记日志。
"""

from __future__ import annotations

from qqlab.core.ids import stable_uuid
from qqlab.core.logging import get_logger
from qqlab.models import AuditLog
from qqlab.ports.auth import CurrentUser
from qqlab.ports.database import DatabaseProvider

logger = get_logger("qqlab.audit")


class DbAuditWriter:
    def __init__(self, db: DatabaseProvider) -> None:
        self._db = db

    async def record(
        self,
        *,
        action: str,
        resource_type: str,
        resource_id: str | None,
        outcome: str = "success",
        detail: dict | None = None,
        user: CurrentUser | None = None,
        request_id: str | None = None,
        ip: str | None = None,
        org_id: str | None = None,
    ) -> None:
        resolved_org = org_id or (user.org_id if user else None)
        if not resolved_org:
            # 无 org 归属（典型：登录失败发生在身份解析前）——不落租户审计表
            # （跨租户隔离：审计查询强制 org 范围），但安全信号必须留在结构化日志里。
            logger.warning(
                "audit_skipped_no_org",
                extra={
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "outcome": outcome,
                    "detail": detail or {},
                    "ip": ip,
                },
            )
            return
        row = AuditLog(
            org_id=stable_uuid(resolved_org),
            actor_user_id=stable_uuid(user.user_id) if user else None,
            actor_username=user.username if user else "system",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            detail=detail or {},
            ip=ip,
            request_id=request_id,
        )
        try:
            async with self._db.session() as session:
                session.add(row)
        except Exception:  # noqa: BLE001 - 审计失败不影响主流程
            logger.exception(
                "audit_write_failed",
                extra={"action": action, "resource_type": resource_type, "outcome": outcome},
            )
