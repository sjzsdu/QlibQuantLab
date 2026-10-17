"""数据服务：数据源 / 授权台账 / 数据集（含导入入队与预览读取）。

合规链（阶段 1 设计 §合规，服务层强制）：
- 没有**有效**授权台账（status=active 且未过期）就不能创建数据集；
- 台账必须挂在数据源上，且 dataset.data_source_id == license.data_source_id；
- 预览读取路径强制 ``{QLIB_DATA_ROOT}/{org_id}/`` 前缀（fail-closed，跨租户 404）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from qqlab.services.job_service import JobService

from qqlab.config import Settings
from qqlab.core.errors import (
    ConfirmationRequiredError,
    ConflictError,
    NotFoundError,
    ValidationAppError,
)
from qqlab.core.ids import stable_uuid
from qqlab.core.qlib_data import (
    DataPathError,
    PreviewRow,
    list_universes,
    read_calendar,
    read_instruments,
    read_ohlcv,
    read_universe,
)
from qqlab.core.tenant import OrgScope
from qqlab.models import DataLicense, Dataset, DataSource
from qqlab.ports.audit import AuditAction, AuditWriter
from qqlab.ports.auth import CurrentUser
from qqlab.repositories import (
    DataLicenseRepository,
    DatasetRepository,
    DataSourceRepository,
    ProjectRepository,
)
from qqlab.schemas import (
    DataLicenseCreateIn,
    DataLicenseOut,
    DataLicenseUpdateIn,
    DatasetCreateIn,
    DatasetOut,
    DataSourceCreateIn,
    DataSourceOut,
    DataSourceUpdateIn,
    PageOut,
)
from qqlab.services.base import AuditContext

_EMPTY = "（空）"


def _license_active(row: DataLicense) -> bool:
    """台账有效性：status=active 且未过期（过期是只读事实，不改库）。"""
    if row.status != "active":
        return False
    if row.expires_at is None:
        return True
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
    return expires > datetime.now(tz=UTC)


class _BaseDataService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        scope: OrgScope,
        user: CurrentUser,
        audit: AuditWriter,
        ctx: AuditContext,
    ) -> None:
        self._session = session
        self._scope = scope
        self._user = user
        self._audit = audit
        self._ctx = ctx


class DataSourceService(_BaseDataService):
    """数据源登记（谁的数据、从哪来）。"""

    async def list(self, *, page: int, page_size: int, keyword: str | None) -> PageOut[DataSourceOut]:
        repo = DataSourceRepository(self._session, self._scope)
        rows, total = await repo.list(page=page, page_size=page_size, keyword=keyword)
        names = await repo.created_by_names(rows)
        items = [
            DataSourceOut(
                id=str(r.id),
                name=r.name,
                kind=r.kind,
                vendor=r.vendor,
                homepage=r.homepage,
                notes=r.notes,
                status=r.status,
                dataset_count=await repo.dataset_count(r.id),
                created_by=names.get(r.created_by, _EMPTY),
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in rows
        ]
        return PageOut[DataSourceOut](items=items, total=total, page=page, page_size=page_size)

    async def get(self, source_id: str) -> DataSourceOut:
        repo = DataSourceRepository(self._session, self._scope)
        row = await repo.get(source_id)
        if row is None:
            raise NotFoundError("数据源不存在或不属于当前组织")
        names = await repo.created_by_names([row])
        return DataSourceOut(
            id=str(row.id),
            name=row.name,
            kind=row.kind,
            vendor=row.vendor,
            homepage=row.homepage,
            notes=row.notes,
            status=row.status,
            dataset_count=await repo.dataset_count(row.id),
            created_by=names.get(row.created_by, _EMPTY),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def create(self, data: DataSourceCreateIn) -> DataSourceOut:
        repo = DataSourceRepository(self._session, self._scope)
        if await repo.count_by_name(data.name.strip()):
            raise ConflictError(f"数据源名称已存在：{data.name}")
        row = await repo.add(
            DataSource(
                org_id=stable_uuid(self._scope.org_id),
                created_by=stable_uuid(self._scope.user_id),
                name=data.name.strip(),
                kind=data.kind.strip() or "market",
                vendor=data.vendor,
                homepage=data.homepage,
                notes=data.notes,
            )
        )
        await self._audit.record(
            action=AuditAction.DATA_SOURCE_CREATE,
            resource_type="data_source",
            resource_id=str(row.id),
            detail={"name": row.name, "kind": row.kind},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        # 写路径显式提交：请求级 session 的 teardown 在响应发出后才执行，
        # 不提交会让「创建后立刻读」的下一个请求读不到（read-your-writes）。
        await self._session.commit()
        return await self.get(str(row.id))

    async def update(self, source_id: str, data: DataSourceUpdateIn) -> DataSourceOut:
        repo = DataSourceRepository(self._session, self._scope)
        row = await repo.get(source_id)
        if row is None:
            raise NotFoundError("数据源不存在或不属于当前组织")
        payload = data.model_dump(exclude_unset=True)
        if "name" in payload and payload["name"] is not None:
            new_name = str(payload["name"]).strip()
            if await repo.count_by_name(new_name, exclude_id=row.id):
                raise ConflictError(f"数据源名称已存在：{new_name}")
            row.name = new_name
        for field_name in ("vendor", "homepage", "notes", "status"):
            if field_name in payload:
                setattr(row, field_name, payload[field_name])
        await self._session.flush()
        await self._audit.record(
            action=AuditAction.DATA_SOURCE_UPDATE,
            resource_type="data_source",
            resource_id=str(row.id),
            detail={"fields": sorted(payload)},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        await self._session.commit()
        return await self.get(str(row.id))

    async def delete(self, source_id: str, *, confirm: bool) -> bool:
        if not confirm:
            raise ConfirmationRequiredError("data_source.delete")
        repo = DataSourceRepository(self._session, self._scope)
        row = await repo.get(source_id)
        if row is None:
            raise NotFoundError("数据源不存在或不属于当前组织")
        if await repo.dataset_count(row.id):
            raise ConflictError("该数据源下仍有关联数据集，无法删除（先处理数据集）")
        await self._session.delete(row)
        await self._session.flush()
        await self._audit.record(
            action=AuditAction.DATA_SOURCE_DELETE,
            resource_type="data_source",
            resource_id=source_id,
            detail={"name": row.name},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        await self._session.commit()
        return True


class DataLicenseService(_BaseDataService):
    """授权台账（谁授权、授权范围、是否可再分发、有效期）。"""

    @staticmethod
    def _out(row: DataLicense, *, source_name: str | None = None) -> DataLicenseOut:
        return DataLicenseOut(
            id=str(row.id),
            data_source_id=str(row.data_source_id),
            data_source_name=source_name,
            scope=row.scope,
            license_ref=row.license_ref,
            allowed_use=row.allowed_use,
            redistribution_allowed=row.redistribution_allowed,
            granted_by=row.granted_by,
            granted_at=row.granted_at,
            expires_at=row.expires_at,
            evidence_uri=row.evidence_uri,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _source_names(self, rows: list[DataLicense]) -> dict[uuid.UUID, str]:
        source_ids = {r.data_source_id for r in rows}
        if not source_ids:
            return {}
        from sqlalchemy import select

        result = await self._session.execute(
            select(DataSource.id, DataSource.name).where(
                DataSource.org_id == stable_uuid(self._scope.org_id), DataSource.id.in_(source_ids)
            )
        )
        return {sid: name for sid, name in result.all()}

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        data_source_id: str | None,
        status: str | None,
    ) -> PageOut[DataLicenseOut]:
        repo = DataLicenseRepository(self._session, self._scope)
        rows, total = await repo.list(
            page=page, page_size=page_size, data_source_id=data_source_id, status=status
        )
        names = await self._source_names(rows)
        items = [self._out(r, source_name=names.get(r.data_source_id)) for r in rows]
        return PageOut[DataLicenseOut](items=items, total=total, page=page, page_size=page_size)

    async def get(self, license_id: str) -> DataLicenseOut:
        repo = DataLicenseRepository(self._session, self._scope)
        row = await repo.get(license_id)
        if row is None:
            raise NotFoundError("授权台账不存在或不属于当前组织")
        names = await self._source_names([row])
        return self._out(row, source_name=names.get(row.data_source_id))

    async def create(self, data: DataLicenseCreateIn) -> DataLicenseOut:
        sources = DataSourceRepository(self._session, self._scope)
        if await sources.get(data.data_source_id) is None:
            raise NotFoundError("数据源不存在或不属于当前组织")
        row = await DataLicenseRepository(self._session, self._scope).add(
            DataLicense(
                org_id=stable_uuid(self._scope.org_id),
                created_by=stable_uuid(self._scope.user_id),
                data_source_id=stable_uuid(data.data_source_id),
                scope=data.scope.strip(),
                license_ref=data.license_ref.strip(),
                allowed_use=data.allowed_use.strip(),
                redistribution_allowed=data.redistribution_allowed,
                granted_by=data.granted_by.strip(),
                granted_at=data.granted_at or datetime.now(tz=UTC),
                expires_at=data.expires_at,
                evidence_uri=data.evidence_uri,
            )
        )
        await self._audit.record(
            action=AuditAction.DATA_LICENSE_CREATE,
            resource_type="data_license",
            resource_id=str(row.id),
            detail={
                "data_source_id": data.data_source_id,
                "license_ref": row.license_ref,
                "redistribution_allowed": row.redistribution_allowed,
            },
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        await self._session.commit()
        return await self.get(str(row.id))

    async def update(self, license_id: str, data: DataLicenseUpdateIn) -> DataLicenseOut:
        repo = DataLicenseRepository(self._session, self._scope)
        row = await repo.get(license_id)
        if row is None:
            raise NotFoundError("授权台账不存在或不属于当前组织")
        payload = data.model_dump(exclude_unset=True)
        if "status" in payload and payload["status"] == "revoked":
            await self._audit.record(
                action=AuditAction.DATA_LICENSE_REVOKE,
                resource_type="data_license",
                resource_id=str(row.id),
                detail={"license_ref": row.license_ref},
                user=self._user,
                request_id=self._ctx.request_id,
                ip=self._ctx.ip,
            )
        for field_name in ("allowed_use", "redistribution_allowed", "expires_at", "evidence_uri", "status"):
            if field_name in payload:
                setattr(row, field_name, payload[field_name])
        await self._session.flush()
        await self._audit.record(
            action=AuditAction.DATA_LICENSE_UPDATE,
            resource_type="data_license",
            resource_id=str(row.id),
            detail={"fields": sorted(payload)},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        await self._session.commit()
        return await self.get(str(row.id))


class DatasetService(_BaseDataService):
    """数据集：创建（合规校验）→ 导入入队 → 预览（挂卷直读）。"""

    def __init__(
        self,
        *,
        session: AsyncSession,
        scope: OrgScope,
        user: CurrentUser,
        audit: AuditWriter,
        ctx: AuditContext,
        settings: Settings,
    ) -> None:
        super().__init__(session=session, scope=scope, user=user, audit=audit, ctx=ctx)
        self._settings = settings

    # ------------------------------------------------------------- 序列化
    async def _out(self, row: Dataset) -> DatasetOut:
        sources = DataSourceRepository(self._session, self._scope)
        source = await sources.get(str(row.data_source_id))
        license_row = await DataLicenseRepository(self._session, self._scope).get(str(row.license_id))
        project = (
            await ProjectRepository(self._session, self._scope).get(str(row.project_id))
            if row.project_id
            else None
        )
        names = await sources.usernames([row.created_by])
        return DatasetOut(
            id=str(row.id),
            project_id=str(row.project_id) if row.project_id else None,
            project_name=project.name if project else None,
            data_source_id=str(row.data_source_id),
            data_source_name=source.name if source else None,
            license_id=str(row.license_id),
            license_ref=license_row.license_ref if license_row else None,
            name=row.name,
            qlib_region=row.qlib_region,
            freq=row.freq,
            start_date=row.start_date,
            end_date=row.end_date,
            instrument_count=row.instrument_count,
            storage_uri=row.storage_uri,
            status=row.status,
            created_by=names.get(row.created_by, _EMPTY),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    # ------------------------------------------------------------- CRUD
    async def list(
        self, *, page: int, page_size: int, keyword: str | None, status: str | None
    ) -> PageOut[DatasetOut]:
        repo = DatasetRepository(self._session, self._scope)
        rows, total = await repo.list(page=page, page_size=page_size, keyword=keyword, status=status)
        items = [await self._out(r) for r in rows]
        return PageOut[DatasetOut](items=items, total=total, page=page, page_size=page_size)

    async def get(self, dataset_id: str) -> DatasetOut:
        row = await DatasetRepository(self._session, self._scope).get(dataset_id)
        if row is None:
            raise NotFoundError("数据集不存在或不属于当前组织")
        return await self._out(row)

    async def create(self, data: DatasetCreateIn) -> DatasetOut:
        source = await DataSourceRepository(self._session, self._scope).get(data.data_source_id)
        if source is None:
            raise NotFoundError("数据源不存在或不属于当前组织")
        license_row = await DataLicenseRepository(self._session, self._scope).get(data.license_id)
        if license_row is None or str(license_row.data_source_id) != str(source.id):
            raise ValidationAppError("授权台账不存在或不属于该数据源")
        if not _license_active(license_row):
            raise ValidationAppError("授权台账无效（已吊销或已过期）——平台不允许无有效授权的数据入库")
        project_id = None
        if data.project_id:
            project = await ProjectRepository(self._session, self._scope).get(data.project_id)
            if project is None:
                raise NotFoundError("项目不存在或不属于当前组织")
            project_id = project.id
        row = await DatasetRepository(self._session, self._scope).add(
            Dataset(
                org_id=stable_uuid(self._scope.org_id),
                created_by=stable_uuid(self._scope.user_id),
                project_id=project_id,
                data_source_id=source.id,
                license_id=license_row.id,
                name=data.name.strip(),
                qlib_region=data.qlib_region.strip() or "cn",
                freq=data.freq.strip() or "day",
            )
        )
        await self._audit.record(
            action=AuditAction.DATASET_CREATE,
            resource_type="dataset",
            resource_id=str(row.id),
            detail={"name": row.name, "license_id": str(license_row.id)},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        await self._session.commit()
        return await self._out(row)

    # ------------------------------------------------------------- 导入
    async def enqueue_import(self, dataset_id: str, *, job_service: JobService) -> tuple[str, str]:
        """入队 dataset_import（payload 只带 dataset_id；org_key 由 repository 注入）。

        返回 ``(dataset_id, job_id)``。入队经 JobService 两阶段提交（行先于消息）；
        同数据集已有 queued/running 任务时由活跃态 payload_hash 唯一索引拦截（409）。
        """
        row = await DatasetRepository(self._session, self._scope).get(dataset_id)
        if row is None:
            raise NotFoundError("数据集不存在或不属于当前组织")
        job_id = await job_service.enqueue(
            kind="dataset_import",
            payload={"dataset_id": str(row.id)},
            requested_by=self._user.username,
            project_id=row.project_id,
        )
        await self._audit.record(
            action=AuditAction.DATASET_IMPORT,
            resource_type="dataset",
            resource_id=str(row.id),
            detail={"name": row.name, "job_id": job_id},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        await self._session.commit()
        return str(row.id), job_id

    # ------------------------------------------------------------- 预览
    def _data_root(self, row: Dataset) -> Path:
        """解析数据目录并强制 org 前缀（fail-closed：越界即拒绝）。"""
        if not row.storage_uri:
            raise ValidationAppError("数据集尚未导入（无数据目录）——先执行「导入数据」")
        root = (Path(self._settings.QLIB_DATA_ROOT) / self._scope.org_id).resolve()
        target = Path(row.storage_uri).resolve()
        if not target.is_relative_to(root):
            raise NotFoundError("数据目录不属于当前组织")
        return target

    async def instruments(
        self, dataset_id: str, *, page: int, page_size: int
    ) -> tuple[list[dict[str, str]], int, int, int]:
        row = await DatasetRepository(self._session, self._scope).get(dataset_id)
        if row is None:
            raise NotFoundError("数据集不存在或不属于当前组织")
        try:
            items = read_instruments(self._data_root(row))
        except DataPathError as exc:
            raise ValidationAppError(str(exc)) from exc
        total = len(items)
        offset, limit = (page - 1) * page_size, page_size
        return items[offset : offset + limit], total, page, page_size

    async def universes(self, dataset_id: str) -> list[dict[str, object]]:
        """可用股票池清单（阶段 6 D6）：``instruments/*.txt`` 池名 + 标的数。"""
        row = await DatasetRepository(self._session, self._scope).get(dataset_id)
        if row is None:
            raise NotFoundError("数据集不存在或不属于当前组织")
        root = self._data_root(row)
        try:
            names = list_universes(root)
        except DataPathError as exc:
            raise ValidationAppError(str(exc)) from exc
        items: list[dict[str, object]] = []
        for name in names:
            try:
                count = len(read_universe(root, name))
            except DataPathError:  # 空文件/坏行池：列入但计 0（提交期会再校验）
                count = 0
            items.append({"name": name, "instruments": count})
        return items

    async def calendar(
        self, dataset_id: str, *, start: str | None, end: str | None
    ) -> tuple[int, str | None, str | None]:
        row = await DatasetRepository(self._session, self._scope).get(dataset_id)
        if row is None:
            raise NotFoundError("数据集不存在或不属于当前组织")
        try:
            dates = read_calendar(self._data_root(row), start=start, end=end)
        except DataPathError as exc:
            raise ValidationAppError(str(exc)) from exc
        return len(dates), dates[0] if dates else None, dates[-1] if dates else None

    async def preview(
        self,
        dataset_id: str,
        *,
        instrument: str,
        start: str | None,
        end: str | None,
        page: int,
        page_size: int,
    ) -> tuple[str, list[PreviewRow], int, int, int]:
        row = await DatasetRepository(self._session, self._scope).get(dataset_id)
        if row is None:
            raise NotFoundError("数据集不存在或不属于当前组织")
        offset = (page - 1) * page_size
        try:
            rows, total = read_ohlcv(
                self._data_root(row),
                instrument,
                freq=row.freq,
                start=start,
                end=end,
                limit=page_size,
                offset=offset,
            )
        except DataPathError as exc:
            raise ValidationAppError(str(exc)) from exc
        return instrument, rows, total, page, page_size


__all__ = ["DataLicenseService", "DataSourceService", "DatasetService"]
