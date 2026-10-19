"""平台审计装饰器（阶段 8 · D8-5）：平台事件双写进 platform_audit_events。

在 **container.py 唯一装配点** 接线：

    audit = PlatformAuditTrail(DbAuditWriter(database), database, cache, retention_days=…)

语义：

- **平台事件**（auth.* 登录成败 + admin.* 配置变更）→ 先转发内层 writer
  （有 org 的事件照旧落租户审计表，行为零变化），再写平台表 —— 跨租户全局视图，
  org 恒为空（登录失败发生在身份解析前，本就无租户归属，D8-5）；已知租户线索
  折进 detail.org_id 保留信号；
- **其余动作**只转发（租户审计主路径不动）；
- 平台表写入/剪枝失败**只记日志**，不影响主流程（同 DbAuditWriter 纪律）；
- 保留期剪枝在写入时**节流**触发：缓存键距上次剪枝 < 24h 直接跳过，
  避免每条写都全表扫。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from qqlab.core.ids import stable_uuid
from qqlab.core.logging import get_logger
from qqlab.models import PlatformAuditEvent
from qqlab.ports.audit import AuditAction, AuditWriter
from qqlab.ports.auth import CurrentUser
from qqlab.ports.cache import CacheProvider
from qqlab.ports.database import DatabaseProvider

logger = get_logger("qqlab.platform_audit")

#: 平台事件里的 auth.* 动作（admin.* 前缀匹配，见 is_platform_action）
_PLATFORM_AUTH_ACTIONS = frozenset(
    {
        AuditAction.AUTH_LOGIN,
        AuditAction.AUTH_LOGOUT,
        AuditAction.AUTH_LOGIN_FAILED,
        AuditAction.AUTH_TOKEN_INVALID,
    }
)

#: 剪枝节流键：24h 内至多全表剪枝一次
_PRUNE_KEY = "qqlab:platform_audit:last_prune"
_PRUNE_INTERVAL_SECONDS = 24 * 3600


def is_platform_action(action: str) -> bool:
    """登录成败 + admin.* 属于平台全局事件（D8-5）。"""
    return action in _PLATFORM_AUTH_ACTIONS or action.startswith("admin.")


class PlatformAuditTrail:
    """AuditWriter 装饰器：平台事件双写 + 节流剪枝。"""

    def __init__(
        self,
        inner: AuditWriter,
        db: DatabaseProvider,
        cache: CacheProvider,
        *,
        retention_days: int = 365,
    ) -> None:
        self._inner = inner
        self._db = db
        self._cache = cache
        self._retention_days = max(1, retention_days)

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
        # 先转发：内层自吞异常，租户审计路径行为与装饰前完全一致
        await self._inner.record(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            detail=detail,
            user=user,
            request_id=request_id,
            ip=ip,
            org_id=org_id,
        )
        if not is_platform_action(action):
            return
        try:
            enriched = dict(detail or {})
            resolved_org = org_id or (user.org_id if user else None)
            if resolved_org:
                enriched.setdefault("org_id", resolved_org)  # 列置空、线索保留
            row = PlatformAuditEvent(
                actor_user_id=stable_uuid(user.user_id) if user else None,
                actor_username=user.username if user else "system",
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                outcome=outcome,
                detail=enriched,
                ip=ip,
                request_id=request_id,
            )
            async with self._db.session() as session:
                session.add(row)
        except Exception:  # noqa: BLE001 - 审计失败不影响主流程
            logger.exception(
                "platform_audit_write_failed",
                extra={"action": action, "outcome": outcome},
            )
        await self._maybe_prune()

    async def _maybe_prune(self) -> None:
        """写入时节流剪枝：距上次剪枝 ≥24h 才真正跑（缓存键缺席即视为到期）。"""
        try:
            if await self._cache.get(_PRUNE_KEY) is not None:
                return
            cutoff = datetime.now(UTC) - timedelta(days=self._retention_days)
            async with self._db.session() as session:
                await session.execute(delete(PlatformAuditEvent).where(PlatformAuditEvent.created_at < cutoff))
            await self._cache.set(_PRUNE_KEY, b"1", ttl=_PRUNE_INTERVAL_SECONDS)
        except Exception:  # noqa: BLE001 - 剪枝失败不影响主流程
            logger.exception("platform_audit_prune_failed")
