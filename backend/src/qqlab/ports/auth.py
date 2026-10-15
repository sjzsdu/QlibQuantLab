"""认证端口（Port）：全系统唯一的用户上下文与认证抽象。

阶段 1-6 使用 ``MockAuthProvider``，阶段 7 换成 ``CasdoorAuthProvider``，
业务代码、数据库表、权限逻辑零改动（见 docs/stage1/04-api-and-auth.md）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class Role(StrEnum):
    """平台角色。与 Casdoor 侧角色名一致，便于阶段 7 映射。"""

    ADMIN = "admin"
    RESEARCHER = "researcher"
    VIEWER = "viewer"
    AUDITOR = "auditor"

    @classmethod
    def parse_all(cls, values: list[str] | tuple[str, ...] | set[str]) -> tuple[Role, ...]:
        """解析角色列表，未知角色直接报错（避免静默获得/丢失权限）。"""
        out: list[Role] = []
        for v in values:
            out.append(cls(str(v).strip().lower()))
        # 去重且保持顺序
        seen: set[Role] = set()
        uniq: list[Role] = []
        for r in out:
            if r not in seen:
                seen.add(r)
                uniq.append(r)
        return tuple(uniq)


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """统一用户上下文。``org_id`` 由认证层给出，业务代码永不从请求参数读组织。"""

    user_id: str
    username: str
    org_id: str
    roles: tuple[Role, ...] = ()
    email: str | None = None
    display_name: str | None = None
    org_name: str | None = None
    is_authenticated: bool = True
    provider: str = "mock"

    @property
    def is_admin(self) -> bool:
        return Role.ADMIN in self.roles

    def has_any(self, *roles: Role) -> bool:
        return any(r in self.roles for r in roles)

    def has_all(self, *roles: Role) -> bool:
        return all(r in self.roles for r in roles)


@runtime_checkable
class AuthProvider(Protocol):
    """身份认证端口。业务代码只依赖本接口，不感知 mock / casdoor。"""

    name: str

    def get_login_url(self, state: str, redirect_to: str) -> str:
        """返回登录跳转地址。mock 为站内地址，casdoor 为 OIDC authorize URL。"""
        ...

    async def handle_callback(self, code: str, state: str) -> CurrentUser:
        """处理（OIDC）回调，返回用户上下文。持久化由 auth_service 负责。"""
        ...

    async def verify_token(self, token: str) -> CurrentUser | None:
        """校验会话令牌，失败返回 None（调用方转 401）。"""
        ...

    def get_logout_url(self, redirect_to: str) -> str:
        """返回登出后跳转地址。"""
        ...

    async def healthcheck(self) -> bool:
        """IdP 是否可达（就绪检查）。"""
        ...
