"""项目仓库。查询一律强制 ``org_id == scope.org_id``。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select

from qqlab.core.ids import stable_uuid
from qqlab.models import Project
from qqlab.repositories.base import BaseRepository


class ProjectRepository(BaseRepository):
    def _base(self):  # noqa: ANN202
        return select(Project).where(
            Project.org_id == stable_uuid(self.scope.org_id),
            Project.deleted_at.is_(None),
        )

    async def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        keyword: str | None = None,
    ) -> tuple[list[Project], int]:
        offset, limit = self.page_offsets(page, page_size)
        stmt = self._base()
        if keyword:
            like = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(Project.name.like(like), Project.description.like(like)),
            )
        total = int(
            (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        )
        rows = (
            (await self.session.execute(stmt.order_by(Project.updated_at.desc()).offset(offset).limit(limit)))
            .scalars()
            .all()
        )
        return list(rows), total

    async def get(self, project_id: str | uuid.UUID) -> Project | None:
        """跨租户 → 返回 None（上层转 404，不泄露资源是否存在）。"""
        try:
            pid = uuid.UUID(str(project_id))
        except ValueError:
            return None
        stmt = self._base().where(Project.id == pid)
        return (await self.session.execute(stmt)).scalars().first()

    async def count_by_name(self, name: str, *, exclude_id: str | uuid.UUID | None = None) -> int:
        stmt = (
            select(func.count())
            .select_from(Project)
            .where(
                Project.org_id == stable_uuid(self.scope.org_id),
                Project.deleted_at.is_(None),
                Project.name == name,
            )
        )
        if exclude_id:
            stmt = stmt.where(Project.id != stable_uuid(str(exclude_id)))
        return int((await self.session.execute(stmt)).scalar_one())

    async def add(self, project: Project) -> Project:
        self.session.add(project)
        await self.session.flush()
        return project

    async def soft_delete(self, project: Project) -> None:
        project.deleted_at = datetime.now(tz=UTC)
        await self.session.flush()

    async def created_by_names(self, projects: list[Project]) -> dict[uuid.UUID, str]:
        return await self.usernames([p.created_by for p in projects])


__all__ = ["ProjectRepository"]
