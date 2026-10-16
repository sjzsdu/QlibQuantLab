"""任务 schema：阶段 4 列表/详情 + 阶段 5 任务中心（日志增量 / cancel / retry）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class JobOut(BaseModel):
    id: str
    kind: str
    status: str
    progress: int
    attempts: int
    max_attempts: int
    error: str | None = None
    payload: dict = Field(default_factory=dict)
    requested_by: str = ""
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class JobLogOut(BaseModel):
    seq: int
    level: str
    message: str
    created_at: datetime


class JobLogsOut(BaseModel):
    """增量日志：``items`` 为 ``seq > since_seq`` 的切片，``next_seq`` 供下次轮询。"""

    items: list[JobLogOut] = Field(default_factory=list)
    next_seq: int = 0
    status: str
    progress: int


class JobActionOut(BaseModel):
    """cancel / retry 的统一返回。

    ``status``：``canceled``=已直接取消（queued）；``cancel_requested``=已置取消标记
    （running 协作式，任务在下个 progress 检查点落 canceled）；retry 返回新任务。
    """

    id: str
    status: str
    detail: str | None = None


__all__ = ["JobActionOut", "JobLogOut", "JobLogsOut", "JobOut"]
