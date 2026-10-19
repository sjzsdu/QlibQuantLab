"""统一响应信封与依赖注入。

约定（见 docs/stage1/04-api-and-auth.md）：
``{ "code": 0, "message": "ok", "data": ..., "request_id": "..." }``
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from qqlab.config import Settings
from qqlab.container import Container
from qqlab.core.errors import UnauthorizedError
from qqlab.core.logging import bind_user, get_logger
from qqlab.core.rbac import has_permission, permissions_for
from qqlab.core.tenant import OrgScope
from qqlab.ports.auth import AuthProvider, CurrentUser, Role
from qqlab.services import AuditContext, AuthService

logger = get_logger("qqlab.api")


# --------------------------------------------------------------------- 信封
def success(request: Request, data: Any, *, message: str = "ok") -> dict[str, Any]:
    return {
        "code": 0,
        "message": message,
        "data": data,
        "request_id": getattr(request.state, "request_id", "-"),
    }


def failure(request: Request, code: int, message: str, data: Any = None) -> dict[str, Any]:
    """非 0 业务错误信封（HTTP 状态码由异常处理器决定）。"""
    return {
        "code": code,
        "message": message,
        "data": data,
        "request_id": getattr(request.state, "request_id", "-"),
    }


# ------------------------------------------------------------------ 容器 / 配置
def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_container(request: Request) -> Container:
    return request.app.state.container


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    container: Container = request.app.state.container
    async with container.database.session() as session:
        yield session


# ------------------------------------------------------------------ 身份
def _extract_token(request: Request, settings: Settings) -> str | None:
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if token:
        return token
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


async def get_optional_user(
    request: Request, settings: Settings = Depends(get_settings)
) -> CurrentUser | None:
    token = _extract_token(request, settings)
    if not token:
        return None
    provider: AuthProvider = request.app.state.container.auth
    try:
        user = await provider.verify_token(token)
    except NotImplementedError:  # pragma: no cover - casdoor 骨架已在启动期拦截
        user = None
    if user is None:
        return None
    bind_user(user.user_id, user.org_id)
    request.state.user = user
    return user


async def get_current_user(user: CurrentUser | None = Depends(get_optional_user)) -> CurrentUser:
    """**唯一的用户入口**：控制器不得直接读 cookie。未登录 → 401。"""
    if user is None or not user.is_authenticated:
        raise UnauthorizedError("未登录或会话已过期，请重新登录")
    return user


def get_scope(user: CurrentUser = Depends(get_current_user)) -> OrgScope:
    return OrgScope(org_id=user.org_id, user_id=user.user_id, roles=user.roles)


# ------------------------------------------------------------------ 权限校验
def require_permission(permission: str) -> Callable[..., Awaitable[CurrentUser]]:
    async def _guard(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not has_permission(user.roles, permission):
            logger.warning(
                "permission_denied",
                extra={"permission": permission, "roles": [r.value for r in user.roles]},
            )
            from qqlab.core.errors import ForbiddenError

            raise ForbiddenError(f"权限不足：需要 {permission}")
        return user

    # 供架构测试静态扫描（D6-2）：遍历 app.routes 时读取该标记，
    # 断言「非白名单路由必须挂权限点且该点 ∈ PERMISSIONS」。
    _guard.__qqlab_permission__ = permission  # type: ignore[attr-defined]
    return _guard


def require_roles(*roles: Role) -> Callable[..., Awaitable[CurrentUser]]:
    allowed = frozenset(roles)

    async def _guard(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not (allowed & set(user.roles)):
            from qqlab.core.errors import ForbiddenError

            raise ForbiddenError("权限不足：角色不匹配")
        return user

    # 角色级守卫的扫描标记（无权限点语义，测试按「已守卫」计）。
    _guard.__qqlab_roles__ = tuple(sorted(r.value for r in allowed))  # type: ignore[attr-defined]
    return _guard


# ------------------------------------------- 平台管理员（阶段 8 · D8-4）
def platform_admin_users(settings) -> frozenset[str]:  # noqa: ANN001 - Settings
    """PLATFORM_ADMIN_USERS 解析：逗号/空白分隔，去空。"""
    return frozenset(
        entry.strip()
        for entry in settings.PLATFORM_ADMIN_USERS.replace(",", " ").split()
        if entry.strip()
    )


def is_platform_admin(user: CurrentUser, settings) -> bool:  # noqa: ANN001 - Settings
    """平台管理员 = env 白名单（与组织内 RBAC 正交）。

    - mock：白名单留空 = 回落 MOCK_USER_ID / MOCK_USER_USERNAME（开发便利）；
    - casdoor：白名单留空 = 无人（fail-closed，不给默认跨租户面）。
    条目同时匹配 username 与 user_id（mock 身份两值不同，casdoor 用户名即条目）。
    """
    entries = platform_admin_users(settings)
    if not entries and settings.AUTH_PROVIDER == "mock":
        entries = frozenset({settings.MOCK_USER_ID, settings.MOCK_USER_USERNAME})
    return bool(entries) and (user.username in entries or user.user_id in entries)


async def require_platform_admin(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """平台端点守卫：白名单成员才放行，否则 403（身份不泄露给非平台管理员）。"""
    settings = get_settings(request)
    if not is_platform_admin(user, settings):
        logger.warning(
            "platform_admin_denied",
            extra={"user_id": user.user_id, "username": user.username},
        )
        from qqlab.core.errors import ForbiddenError

        raise ForbiddenError("需要平台管理员授权（PLATFORM_ADMIN_USERS）")
    return user


# 供架构测试静态扫描（D6-2）：按「已守卫」计（权限语义在 env 白名单，非 RBAC 表）
require_platform_admin.__qqlab_roles__ = ("platform_admin",)  # type: ignore[attr-defined]


def permissions_response(user: CurrentUser = Depends(get_current_user)) -> list[str]:
    return permissions_for(user.roles)


# ---------------------------------------------------------------- 服务装配
def get_auth_service(request: Request) -> AuthService:
    """按请求构造 AuthService（无重连接开销，只有轻量对象）。"""
    container: Container = request.app.state.container
    return AuthService(
        settings=container.settings,
        provider=container.auth,
        cache=container.cache,
        database=container.database,
        audit=container.audit,
    )


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def get_audit_ctx(request: Request) -> AuditContext:
    return AuditContext(
        request_id=getattr(request.state, "request_id", None),
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


async def require_confirmation(confirm: bool = False) -> None:
    """依赖式二次确认：高危接口声明 ``Depends(require_confirmation)``。"""
    from qqlab.core.errors import ConfirmationRequiredError

    if not confirm:
        raise ConfirmationRequiredError("该操作")
