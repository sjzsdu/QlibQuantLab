"""数据域 schema：数据源 / 授权台账 / 数据集 / 预览。"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from qqlab.core.qlib_data import OHLCV_FIELDS

_EMPTY = "（空）"


class DataSourceCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="market", max_length=32)
    vendor: str | None = Field(default=None, max_length=200)
    homepage: str | None = Field(default=None, max_length=500)
    notes: str | None = None


class DataSourceUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    vendor: str | None = Field(default=None, max_length=200)
    homepage: str | None = Field(default=None, max_length=500)
    notes: str | None = None
    status: str | None = Field(default=None, pattern="^(active|disabled)$")


class DataSourceOut(BaseModel):
    id: str
    name: str
    kind: str
    vendor: str | None = None
    homepage: str | None = None
    notes: str | None = None
    status: str
    dataset_count: int = 0
    created_by: str = _EMPTY
    created_at: datetime
    updated_at: datetime


class DataLicenseCreateIn(BaseModel):
    data_source_id: str
    scope: str = Field(default="internal_research", max_length=64)
    license_ref: str = Field(min_length=1, max_length=200)
    allowed_use: str = Field(min_length=1, max_length=2000)
    redistribution_allowed: bool = False
    granted_by: str = Field(min_length=1, max_length=200)
    granted_at: datetime | None = None
    expires_at: datetime | None = None
    evidence_uri: str | None = Field(default=None, max_length=500)


class DataLicenseUpdateIn(BaseModel):
    allowed_use: str | None = Field(default=None, min_length=1, max_length=2000)
    redistribution_allowed: bool | None = None
    expires_at: datetime | None = None
    evidence_uri: str | None = Field(default=None, max_length=500)
    #: active ⇄ revoked；到期由服务层按 expires_at 判定
    status: str | None = Field(default=None, pattern="^(active|revoked)$")


class DataLicenseOut(BaseModel):
    id: str
    data_source_id: str
    data_source_name: str | None = None
    scope: str
    license_ref: str
    allowed_use: str
    redistribution_allowed: bool
    granted_by: str
    granted_at: datetime | None = None
    expires_at: datetime | None = None
    evidence_uri: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class DatasetCreateIn(BaseModel):
    project_id: str | None = None
    data_source_id: str
    license_id: str
    name: str = Field(min_length=1, max_length=200)
    qlib_region: str = Field(default="cn", max_length=32)
    freq: str = Field(default="day", max_length=8)


class DatasetOut(BaseModel):
    id: str
    project_id: str | None = None
    project_name: str | None = None
    data_source_id: str
    data_source_name: str | None = None
    license_id: str
    license_ref: str | None = None
    name: str
    qlib_region: str
    freq: str
    start_date: date | None = None
    end_date: date | None = None
    instrument_count: int
    storage_uri: str
    status: str
    created_by: str = _EMPTY
    created_at: datetime
    updated_at: datetime


class DatasetImportOut(BaseModel):
    """导入请求受理回执：任务已入队，进度经 GET /jobs/{id} 轮询。"""

    dataset_id: str
    job_id: str
    status: str


class PreviewRowOut(BaseModel):
    date: str
    values: dict[str, float]


class PreviewOut(BaseModel):
    dataset_id: str
    instrument: str
    fields: list[str] = list(OHLCV_FIELDS)
    items: list[PreviewRowOut]
    total: int
    page: int
    page_size: int


class InstrumentsOut(BaseModel):
    dataset_id: str
    items: list[dict[str, str]]
    total: int
    page: int
    page_size: int


class CalendarOut(BaseModel):
    dataset_id: str
    total: int
    start: str | None = None
    end: str | None = None


__all__ = [
    "CalendarOut",
    "DataLicenseCreateIn",
    "DataLicenseOut",
    "DataLicenseUpdateIn",
    "DataSourceCreateIn",
    "DataSourceOut",
    "DataSourceUpdateIn",
    "DatasetCreateIn",
    "DatasetImportOut",
    "DatasetOut",
    "InstrumentsOut",
    "PreviewOut",
    "PreviewRowOut",
]
