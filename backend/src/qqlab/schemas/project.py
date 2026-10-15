"""项目域补充 schema：项目成员管理与可见性切换（阶段 4）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProjectMemberAddIn(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    role: str = Field(default="viewer", pattern="^(viewer|researcher|admin)$")


class ProjectMemberOut(BaseModel):
    user_id: str
    username: str
    role: str
    added_at: datetime | None = None


class VisibilityChangeIn(BaseModel):
    visibility: str = Field(pattern="^(private|org|public)$")


__all__ = ["ProjectMemberAddIn", "ProjectMemberOut", "VisibilityChangeIn"]
