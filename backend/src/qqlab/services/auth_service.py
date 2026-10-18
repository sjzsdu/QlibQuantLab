"""登录 / 登出 / 回调编排。

认证端口只负责**给身份**；把身份落到平台自己的 org/users/org_members、
签发会话令牌、写审计，都在这里完成（阶段 7 换 Casdoor 时本文件零改动）。
"""

from __future__ import annotations

from dataclasses import dataclass

from qqlab.config import Settings
from qqlab.core.errors import UnauthorizedError, ValidationAppError
from qqlab.core.security import issue_session_token, new_token
from qqlab.ports.audit import AuditAction, AuditWriter
from qqlab.ports.auth import AuthProvider, CurrentUser
from qqlab.ports.cache import CacheProvider
from qqlab.ports.database import DatabaseProvider
from qqlab.repositories import IdentityRepository
from qqlab.services.base import AuditContext

_STATE_TTL = 600
_STATE_KEY = "qqlab:auth:state"


@dataclass(frozen=True, slots=True)
class LoginStart:
    url: str
    state: str


@dataclass(frozen=True, slots=True)
class SessionBundle:
    user: CurrentUser
    token: str
    ttl_seconds: int
    redirect_to: str = "/"
    csrf_token: str = ""


class AuthService:
    def __init__(
        self,
        *,
        settings: Settings,
        provider: AuthProvider,
        cache: CacheProvider,
        database: DatabaseProvider,
        audit: AuditWriter,
    ) -> None:
        self._settings = settings
        self._provider = provider
        self._cache = cache
        self._database = database
        self._audit = audit

    # ------------------------------------------------------------ 登录前
    async def begin_login(self, redirect_to: str | None) -> LoginStart:
        redirect_to = safe_redirect(redirect_to)
        state = new_token()
        await self._cache.set(f"{_STATE_KEY}:{state}", redirect_to.encode(), ttl=_STATE_TTL)
        return LoginStart(url=self._provider.get_login_url(state, redirect_to), state=state)

    async def _consume_state(self, state: str) -> str | None:
        if not state:
            return None
        key = f"{_STATE_KEY}:{state}"
        raw = await self._cache.get(key)
        if raw is None:
            return None
        await self._cache.delete(key)
        return raw.decode()

    # --------------------------------------------------- 回调 / 一键进入
    async def handle_callback(
        self, code: str, state: str, *, ip: str | None = None
    ) -> SessionBundle:
        """OIDC 回调入口：state 必须由本平台签发且未使用过。"""
        redirect_to = await self._consume_state(state)
        if state and redirect_to is None:
            await self._audit.record(
                action=AuditAction.AUTH_LOGIN_FAILED,
                resource_type="auth",
                resource_id=None,
                outcome="failure",
                detail={"reason": "invalid_state"},
                ip=ip,
            )
            raise ValidationAppError("登录 state 无效或已过期，请重新发起登录")
        user = await self._fetch_identity(code, state)
        return await self._complete_login(user, redirect_to=redirect_to or "/")

    async def login_for_identity(self, user: CurrentUser, *, redirect_to: str | None = None) -> SessionBundle:
        """mock 一键进入：身份已由 MockAuthProvider 构造，无需 state。"""
        return await self._complete_login(user, redirect_to=safe_redirect(redirect_to))

    async def _fetch_identity(self, code: str, state: str) -> CurrentUser:
        try:
            user = await self._provider.handle_callback(code, state)
        except NotImplementedError as exc:  # casdoor 骨架
            raise ValidationAppError(str(exc)) from exc
        if user is None or not user.is_authenticated:
            raise UnauthorizedError("身份验证失败")
        return user

    async def _complete_login(self, user: CurrentUser, *, redirect_to: str = "/") -> SessionBundle:
        await self._persist_identity(user)
        token = issue_session_token(user, self._settings)
        await self._audit.record(
            action=AuditAction.AUTH_LOGIN,
            resource_type="auth",
            resource_id=user.user_id,
            outcome="success",
            detail={"provider": user.provider, "roles": [r.value for r in user.roles]},
            user=user,
        )
        return SessionBundle(
            user=user,
            token=token,
            ttl_seconds=self._settings.APP_JWT_TTL_SECONDS,
            redirect_to=redirect_to,
            csrf_token=new_token(),
        )

    async def _persist_identity(self, user: CurrentUser) -> None:
        """把外部身份落到平台自己的 org / users / org_members。"""
        slug = self._settings.MOCK_ORG_SLUG if user.provider == "mock" else f"org-{user.org_id[:12]}"
        name = (
            self._settings.MOCK_ORG_NAME
            if user.provider == "mock"
            else (user.org_name or f"Org {user.org_id[:8]}")
        )
        async with self._database.session() as session:
            identity = IdentityRepository(session)
            # org_name 为空 = 外部 IdP 未携带组织显示名（Casdoor JWT 只有 owner 名）：
            # 回落名只用于新建，绝不覆盖既有组织名（防止 ORG_MAP 映射进既有组织时被改名）
            await identity.ensure_org(
                user.org_id, slug=slug, name=name, rename_existing=user.org_name is not None
            )
            await identity.upsert_user(
                user_id=user.user_id,
                username=user.username,
                email=user.email,
                display_name=user.display_name,
                provider=user.provider,
            )
            await identity.upsert_membership(
                org_id=user.org_id,
                user_id=user.user_id,
                roles=[r.value for r in user.roles],
            )

    async def logout(self, user: CurrentUser | None, ctx: AuditContext) -> None:
        await self._audit.record(
            action=AuditAction.AUTH_LOGOUT,
            resource_type="auth",
            resource_id=user.user_id if user else None,
            outcome="success",
            detail={},
            user=user,
            request_id=ctx.request_id,
            ip=ctx.ip,
            org_id=user.org_id if user else None,
        )


def safe_redirect(value: str | None) -> str:
    """只允许站内相对路径，拒绝 ``//evil.com`` 之类的开放重定向。"""
    raw = (value or "/").strip()
    if not raw.startswith("/"):
        return "/"
    if raw.startswith("//") or "\\" in raw or "://" in raw:
        return "/"
    return raw
