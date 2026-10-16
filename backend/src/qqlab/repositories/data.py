"""数据域仓库：data_sources / data_licenses / datasets。

查询一律强制 ``org_id == scope.org_id``；跨租户 → None（上层转 404）。
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from qqlab.core.ids import stable_uuid
from qqlab.models import DataLicense, Dataset, DataSource
from qqlab.repositories.base import BaseRepository


class DataSourceRepository(BaseRepository):
    def _base(self):  # noqa: ANN202
        return select(DataSource).where(DataSource.org_id == stable_uuid(self.scope.org_id))

    async def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        keyword: str | None = None,
    ) -> tuple[list[DataSource], int]:
        from sqlalchemy import or_

        offset, limit = self.page_offsets(page, page_size)
        stmt = self._base()
        if keyword:
            like = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(DataSource.name.like(like), DataSource.vendor.like(like)),
            )
        total = int(
            (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        )
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(DataSource.updated_at.desc()).offset(offset).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total

    async def get(self, source_id: str | uuid.UUID) -> DataSource | None:
        try:
            sid = uuid.UUID(str(source_id))
        except ValueError:
            return None
        return (await self.session.execute(self._base().where(DataSource.id == sid))).scalars().first()

    async def count_by_name(self, name: str, *, exclude_id: str | uuid.UUID | None = None) -> int:
        stmt = (
            select(func.count())
            .select_from(DataSource)
            .where(DataSource.org_id == stable_uuid(self.scope.org_id), DataSource.name == name)
        )
        if exclude_id:
            stmt = stmt.where(DataSource.id != stable_uuid(str(exclude_id)))
        return int((await self.session.execute(stmt)).scalar_one())

    async def add(self, source: DataSource) -> DataSource:
        self.session.add(source)
        await self.session.flush()
        return source

    async def dataset_count(self, source_id: uuid.UUID) -> int:
        return int(
            (
                await self.session.execute(
                    select(func.count())
                    .select_from(Dataset)
                    .where(
                        Dataset.org_id == stable_uuid(self.scope.org_id), Dataset.data_source_id == source_id
                    )
                )
            ).scalar_one()
        )

    async def created_by_names(self, sources: list[DataSource]) -> dict[uuid.UUID, str]:
        return await self.usernames([s.created_by for s in sources])


class DataLicenseRepository(BaseRepository):
    def _base(self):  # noqa: ANN202
        return select(DataLicense).where(DataLicense.org_id == stable_uuid(self.scope.org_id))

    async def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        data_source_id: str | None = None,
        status: str | None = None,
    ) -> tuple[list[DataLicense], int]:
        offset, limit = self.page_offsets(page, page_size)
        stmt = self._base()
        if data_source_id:
            stmt = stmt.where(DataLicense.data_source_id == stable_uuid(data_source_id))
        if status:
            stmt = stmt.where(DataLicense.status == status)
        total = int(
            (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        )
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(DataLicense.updated_at.desc()).offset(offset).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total

    async def get(self, license_id: str | uuid.UUID) -> DataLicense | None:
        try:
            lid = uuid.UUID(str(license_id))
        except ValueError:
            return None
        return (await self.session.execute(self._base().where(DataLicense.id == lid))).scalars().first()

    async def add(self, license_row: DataLicense) -> DataLicense:
        self.session.add(license_row)
        await self.session.flush()
        return license_row


class DatasetRepository(BaseRepository):
    def _base(self):  # noqa: ANN202
        return select(Dataset).where(Dataset.org_id == stable_uuid(self.scope.org_id))

    async def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        keyword: str | None = None,
        project_id: str | None = None,
        status: str | None = None,
    ) -> tuple[list[Dataset], int]:
        from sqlalchemy import or_

        offset, limit = self.page_offsets(page, page_size)
        stmt = self._base()
        if keyword:
            like = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(Dataset.name.like(like), Dataset.storage_uri.like(like)),
            )
        if project_id:
            stmt = stmt.where(Dataset.project_id == stable_uuid(project_id))
        if status:
            stmt = stmt.where(Dataset.status == status)
        total = int(
            (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        )
        rows = (
            (await self.session.execute(stmt.order_by(Dataset.updated_at.desc()).offset(offset).limit(limit)))
            .scalars()
            .all()
        )
        return list(rows), total

    async def get(self, dataset_id: str | uuid.UUID) -> Dataset | None:
        try:
            did = uuid.UUID(str(dataset_id))
        except ValueError:
            return None
        return (await self.session.execute(self._base().where(Dataset.id == did))).scalars().first()

    async def add(self, dataset: Dataset) -> Dataset:
        self.session.add(dataset)
        await self.session.flush()
        return dataset


__all__ = ["DataLicenseRepository", "DataSourceRepository", "DatasetRepository"]
