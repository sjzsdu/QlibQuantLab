"""审计与系统配置仓库。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from qqlab.core.ids import stable_uuid
from qqlab.models import AuditLog, SystemConfig


class AuditRepository:
    def __init__(self, session: AsyncSession, org_id: str) -> None:
        self.session = session
        self._org_id = stable_uuid(org_id)

    async def list(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        action: str | None = None,
        actor: str | None = None,
        outcome: str | None = None,
    ) -> tuple[list[AuditLog], int]:
        offset, limit = (max(1, page) - 1) * min(max(1, page_size), 200), min(max(1, page_size), 200)
        stmt = select(AuditLog).where(AuditLog.org_id == self._org_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if actor:
            stmt = stmt.where(AuditLog.actor_username == actor)
        if outcome:
            stmt = stmt.where(AuditLog.outcome == outcome)
        total = int(
            (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        )
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total

    async def distinct_actions(self) -> list[str]:
        rows = await self.session.execute(
            select(AuditLog.action)
            .where(AuditLog.org_id == self._org_id)
            .distinct()
            .order_by(AuditLog.action)
        )
        return list(rows.scalars().all())


class SystemConfigRepository:
    def __init__(self, session: AsyncSession, org_id: str) -> None:
        self.session = session
        self._org_id = stable_uuid(org_id)

    async def list_all(self) -> list[SystemConfig]:
        stmt = (
            select(SystemConfig).where(SystemConfig.org_id == self._org_id).order_by(SystemConfig.config_key)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, config_key: str) -> SystemConfig | None:
        stmt = select(SystemConfig).where(
            SystemConfig.org_id == self._org_id,
            SystemConfig.config_key == config_key,
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def upsert(
        self,
        *,
        config_key: str,
        value: dict,
        is_secret: bool = False,
        updated_by: str | None = None,
    ) -> SystemConfig:
        row = await self.get(config_key)
        if row is None:
            row = SystemConfig(
                id=uuid.uuid4(),
                org_id=self._org_id,
                config_key=config_key,
                value=value,
                is_secret=is_secret,
                updated_by=updated_by,
            )
            self.session.add(row)
        else:
            row.value = value
            row.is_secret = is_secret
            row.updated_by = updated_by
        await self.session.flush()
        return row


__all__ = ["AuditRepository", "SystemConfigRepository"]
