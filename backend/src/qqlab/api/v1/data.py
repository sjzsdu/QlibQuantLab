"""数据域 API：数据源 / 授权台账 / 数据集（导入 + 预览）。

合规链在服务层强制：无有效台账不可创建数据集；预览读取强制 org 前缀（越界 404）。
导入经 JobService 入队（阶段 3 链路），进度用 ``GET /api/v1/jobs/{id}`` 轮询。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from qqlab.api.deps import (
    get_audit_ctx,
    get_container,
    get_db_session,
    require_permission,
    success,
)
from qqlab.container import Container
from qqlab.core.errors import ConfirmationRequiredError
from qqlab.core.qlib_data import OHLCV_FIELDS
from qqlab.core.tenant import OrgScope
from qqlab.ports.auth import CurrentUser
from qqlab.schemas import (
    CalendarOut,
    DataLicenseCreateIn,
    DataLicenseUpdateIn,
    DatasetCreateIn,
    DatasetImportOut,
    DataSourceCreateIn,
    DataSourceUpdateIn,
    InstrumentsOut,
    OkOut,
    PreviewOut,
    PreviewRowOut,
)
from qqlab.services import (
    AuditContext,
    DataLicenseService,
    DatasetService,
    DataSourceService,
    JobService,
)

router = APIRouter(tags=["data"])


def _scope(user: CurrentUser) -> OrgScope:
    return OrgScope(org_id=user.org_id, user_id=user.user_id, roles=user.roles)


def _source_service(request: Request, session, user: CurrentUser, ctx: AuditContext):  # noqa: ANN001
    return DataSourceService(
        session=session,
        scope=_scope(user),
        user=user,
        audit=request.app.state.container.audit,
        ctx=ctx,
    )


def _license_service(request: Request, session, user: CurrentUser, ctx: AuditContext):  # noqa: ANN001
    return DataLicenseService(
        session=session,
        scope=_scope(user),
        user=user,
        audit=request.app.state.container.audit,
        ctx=ctx,
    )


def _dataset_service(request: Request, session, user: CurrentUser, ctx: AuditContext):  # noqa: ANN001
    container: Container = request.app.state.container
    return DatasetService(
        session=session,
        scope=_scope(user),
        user=user,
        audit=container.audit,
        ctx=ctx,
        settings=container.settings,
    )


# ------------------------------------------------------------------ 数据源
@router.get("/data-sources", summary="数据源列表")
async def list_data_sources(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, max_length=100),
    user=Depends(require_permission("data.read")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _source_service(request, session, user, ctx)
    return success(
        request, (await service.list(page=page, page_size=page_size, keyword=keyword)).model_dump()
    )


@router.post("/data-sources", summary="登记数据源")
async def create_data_source(
    request: Request,
    payload: DataSourceCreateIn,
    user=Depends(require_permission("data.write")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _source_service(request, session, user, ctx)
    return success(request, (await service.create(payload)).model_dump(), message="数据源已登记")


@router.get("/data-sources/{source_id}", summary="数据源详情")
async def get_data_source(
    request: Request,
    source_id: str,
    user=Depends(require_permission("data.read")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _source_service(request, session, user, ctx)
    return success(request, (await service.get(source_id)).model_dump())


@router.patch("/data-sources/{source_id}", summary="更新数据源")
async def update_data_source(
    request: Request,
    source_id: str,
    payload: DataSourceUpdateIn,
    user=Depends(require_permission("data.write")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _source_service(request, session, user, ctx)
    return success(request, (await service.update(source_id, payload)).model_dump(), message="数据源已更新")


@router.delete("/data-sources/{source_id}", summary="删除数据源（二次确认；有关联数据集时拒绝）")
async def delete_data_source(
    request: Request,
    source_id: str,
    confirm: bool = Query(False, description="高危操作需传 confirm=true"),
    user=Depends(require_permission("resource.delete")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    if not confirm:
        raise ConfirmationRequiredError("data_source.delete")
    service = _source_service(request, session, user, ctx)
    deleted = await service.delete(source_id, confirm=confirm)
    return success(request, OkOut(deleted=deleted).model_dump(), message="数据源已删除")


# ------------------------------------------------------------------ 授权台账
@router.get("/data-licenses", summary="授权台账列表")
async def list_data_licenses(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    data_source_id: str | None = Query(None),
    status: str | None = Query(None, pattern="^(active|revoked)$"),
    user=Depends(require_permission("data.read")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _license_service(request, session, user, ctx)
    page_out = await service.list(
        page=page, page_size=page_size, data_source_id=data_source_id, status=status
    )
    return success(request, page_out.model_dump())


@router.post("/data-licenses", summary="登记授权台账（仅 admin）")
async def create_data_license(
    request: Request,
    payload: DataLicenseCreateIn,
    user=Depends(require_permission("data.license.manage")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _license_service(request, session, user, ctx)
    return success(request, (await service.create(payload)).model_dump(), message="授权台账已登记")


@router.get("/data-licenses/{license_id}", summary="授权台账详情")
async def get_data_license(
    request: Request,
    license_id: str,
    user=Depends(require_permission("data.read")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _license_service(request, session, user, ctx)
    return success(request, (await service.get(license_id)).model_dump())


@router.patch("/data-licenses/{license_id}", summary="更新授权台账（续期/吊销，仅 admin）")
async def update_data_license(
    request: Request,
    license_id: str,
    payload: DataLicenseUpdateIn,
    user=Depends(require_permission("data.license.manage")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _license_service(request, session, user, ctx)
    return success(
        request, (await service.update(license_id, payload)).model_dump(), message="授权台账已更新"
    )


# ------------------------------------------------------------------ 数据集
@router.get("/datasets", summary="数据集列表")
async def list_datasets(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, max_length=100),
    status: str | None = Query(None, pattern="^(pending|active|failed)$"),
    user=Depends(require_permission("data.read")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _dataset_service(request, session, user, ctx)
    page_out = await service.list(page=page, page_size=page_size, keyword=keyword, status=status)
    return success(request, page_out.model_dump())


@router.post("/datasets", summary="创建数据集（须有有效授权台账）")
async def create_dataset(
    request: Request,
    payload: DatasetCreateIn,
    user=Depends(require_permission("data.write")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _dataset_service(request, session, user, ctx)
    return success(request, (await service.create(payload)).model_dump(), message="数据集已创建（待导入）")


@router.get("/datasets/{dataset_id}", summary="数据集详情")
async def get_dataset(
    request: Request,
    dataset_id: str,
    user=Depends(require_permission("data.read")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _dataset_service(request, session, user, ctx)
    return success(request, (await service.get(dataset_id)).model_dump())


@router.post("/datasets/{dataset_id}/import", summary="导入数据集（入队任务，进度经 /jobs 轮询）")
async def import_dataset(
    request: Request,
    dataset_id: str,
    user=Depends(require_permission("data.write")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
    container: Container = Depends(get_container),
) -> dict:
    service = _dataset_service(request, session, user, ctx)
    job_service = JobService(container=container, scope=_scope(user))
    dataset_id, job_id = await service.enqueue_import(dataset_id, job_service=job_service)
    out = DatasetImportOut(dataset_id=dataset_id, job_id=job_id, status="queued")
    return success(request, out.model_dump(), message="导入任务已入队")


@router.get("/datasets/{dataset_id}/instruments", summary="数据集标的列表（只读挂卷解析）")
async def dataset_instruments(
    request: Request,
    dataset_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    user=Depends(require_permission("data.read")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _dataset_service(request, session, user, ctx)
    items, total, page, page_size = await service.instruments(dataset_id, page=page, page_size=page_size)
    out = InstrumentsOut(dataset_id=dataset_id, items=items, total=total, page=page, page_size=page_size)
    return success(request, out.model_dump())


@router.get("/datasets/{dataset_id}/calendar", summary="数据集交易日历（区间统计）")
async def dataset_calendar(
    request: Request,
    dataset_id: str,
    start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    user=Depends(require_permission("data.read")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _dataset_service(request, session, user, ctx)
    total, first, last = await service.calendar(dataset_id, start=start, end=end)
    out = CalendarOut(dataset_id=dataset_id, total=total, start=first, end=last)
    return success(request, out.model_dump())


@router.get("/datasets/{dataset_id}/preview", summary="OHLCV 预览（float32 bin 只读解析）")
async def dataset_preview(
    request: Request,
    dataset_id: str,
    instrument: str = Query(..., max_length=32),
    start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    user=Depends(require_permission("data.read")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
) -> dict:
    service = _dataset_service(request, session, user, ctx)
    instrument, rows, total, page, page_size = await service.preview(
        dataset_id, instrument=instrument, start=start, end=end, page=page, page_size=page_size
    )
    out = PreviewOut(
        dataset_id=dataset_id,
        instrument=instrument,
        fields=list(OHLCV_FIELDS),
        items=[PreviewRowOut(date=r.date, values=r.values) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
    return success(request, out.model_dump())


__all__ = ["router"]
