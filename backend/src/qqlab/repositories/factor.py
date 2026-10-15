"""因子仓库。查询一律强制 ``org_id == scope.org_id``。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select

from qqlab.core.ids import stable_uuid
from qqlab.models import Factor
from qqlab.repositories.base import BaseRepository


class FactorRepository(BaseRepository):
    def _base(self):  # noqa: ANN202
        return select(Factor).where(Factor.org_id == stable_uuid(self.scope.org_id))

    async def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        keyword: str | None = None,
        project_id: str | None = None,
    ) -> tuple[list[Factor], int]:
        offset, limit = self.page_offsets(page, page_size)
        stmt = self._base()
        if keyword:
            like = f"%{keyword.strip()}%"
            stmt = stmt.where(or_(Factor.name.like(like), Factor.expression.like(like)))
        if project_id:
            stmt = stmt.where(Factor.project_id == stable_uuid(project_id))
        total = int(
            (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        )
        rows = (
            (await self.session.execute(stmt.order_by(Factor.updated_at.desc()).offset(offset).limit(limit)))
            .scalars()
            .all()
        )
        return list(rows), total

    async def get(self, factor_id: str | uuid.UUID) -> Factor | None:
        try:
            fid = uuid.UUID(str(factor_id))
        except ValueError:
            return None
        return (await self.session.execute(self._base().where(Factor.id == fid))).scalars().first()

    async def count_by_name(self, name: str, *, project_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(Factor)
            .where(
                Factor.org_id == stable_uuid(self.scope.org_id),
                Factor.project_id == project_id,
                Factor.name == name,
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def add(self, factor: Factor) -> Factor:
        self.session.add(factor)
        await self.session.flush()
        return factor


__all__ = ["FactorRepository"]
