"""任务只读 schema（阶段 4 子集：列表 + 详情，支撑导入进度轮询）。

任务中心完整功能（cancel / retry / logs / SSE 流）属阶段 5。
"""

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


__all__ = ["JobOut"]
