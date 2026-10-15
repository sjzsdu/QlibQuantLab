"""Pydantic v2 出入参模型（信封之外的 payload）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PageOut[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class OkOut(BaseModel):
    deleted: bool = True
    id: str | None = None


# ------------------------------------------------------------------ 用户 / 组织
class CurrentUserOut(BaseModel):
    user_id: str
    username: str
    display_name: str | None = None
    email: str | None = None
    org_id: str
    org_name: str | None = None
    roles: list[str] = []
    is_authenticated: bool = True
    provider: str = "mock"


class PermissionsOut(BaseModel):
    permissions: list[str] = []


class LoginStartOut(BaseModel):
    url: str
    state: str | None = None


class MockEnterIn(BaseModel):
    profile: str | None = None
    redirect_to: str = Field(default="/")


class LogoutOut(BaseModel):
    redirect_to: str = "/login"


class OrgOut(BaseModel):
    id: str
    slug: str
    name: str
    status: str = "active"


# ------------------------------------------------------------------------ 项目
class ProjectCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ProjectUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str | None = None
    visibility: str = "private"
    default_benchmark: str = "SH000300"
    created_by: str = ""
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------ 成员 / 配置
class MemberOut(BaseModel):
    user_id: str
    username: str
    display_name: str | None = None
    email: str | None = None
    roles: list[str] = []
    status: str = "active"
    joined_at: datetime


class MemberAddIn(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    roles: list[str] = Field(min_length=1)
    display_name: str | None = None
    email: str | None = None


class MemberRoleUpdateIn(BaseModel):
    roles: list[str] = Field(min_length=1)


class ConfigOut(BaseModel):
    config_key: str
    value: dict
    is_secret: bool = False
    updated_by: str | None = None
    updated_at: datetime


class ConfigUpdateIn(BaseModel):
    value: dict
    is_secret: bool = False


# -------------------------------------------------------------------- 审计日志
class AuditLogOut(BaseModel):
    id: str
    action: str
    resource_type: str
    resource_id: str | None = None
    outcome: str
    actor_username: str
    detail: dict = {}
    ip: str | None = None
    request_id: str | None = None
    created_at: datetime


# ------------------------------------------------------------------------ 法务
class LegalMetaOut(BaseModel):
    code: str
    title: str
    version: str
    effective_at: str


class LegalDocOut(BaseModel):
    code: str
    title: str
    version: str
    effective_at: str
    content: str


# -------------------------------------------------------------------- 系统信息
class SystemInfoOut(BaseModel):
    service: str = "qqlab-api"
    env: str
    version: str = "0.1.0"
    auth_provider: str
    database_backend: str
    cache_backend: str
    mq_backend: str
    storage_backend: str
    qlib_server_ws_url: str
    uptime_seconds: float = 0.0


class ReadyOut(BaseModel):
    status: str
    checks: dict[str, bool] = {}
