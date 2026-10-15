"""MockAuthProvider —— 阶段 1~6 的默认身份提供者。

- 不跳转外部站点，登录页一键进入；
- 会话 token 由平台自己签发（HS256），与 Casdoor 的会话机制完全一致，
  所以阶段 7 切换时前端与业务代码零改动。
"""

from __future__ import annotations

from urllib.parse import quote

from qqlab.config import Settings
from qqlab.core.security import decode_session_token
from qqlab.ports.auth import CurrentUser, Role

#: 各 profile 预置角色。admin 额外带 researcher，便于验证「最高权限者也得有读权限」。
_PROFILE_ROLES: dict[str, tuple[Role, ...]] = {
    "admin": (Role.ADMIN, Role.RESEARCHER),
    "researcher": (Role.RESEARCHER,),
    "viewer": (Role.VIEWER,),
    "auditor": (Role.AUDITOR,),
}

DEFAULT_PROFILE = "admin"


class MockAuthProvider:
    name = "mock"
    IMPLEMENTED = True

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # ---------------------------------------------------------------- 内部
    def _identity(self, profile: str) -> CurrentUser:
        settings = self._settings
        profile = (profile or DEFAULT_PROFILE).strip().lower() or DEFAULT_PROFILE
        if profile == "default":
            roles = Role.parse_all(settings.MOCK_USER_ROLES.split(","))
            user_id, username = settings.MOCK_USER_ID, settings.MOCK_USER_USERNAME
            display, email = settings.MOCK_USER_DISPLAY_NAME, settings.MOCK_USER_EMAIL
        else:
            roles = _PROFILE_ROLES.get(profile) or Role.parse_all(settings.MOCK_USER_ROLES.split(","))
            suffix = "" if profile == "admin" else f"-{profile}"
            user_id = f"{settings.MOCK_USER_ID}{suffix}"
            username = f"{settings.MOCK_USER_USERNAME}{suffix}"
            display = (
                settings.MOCK_USER_DISPLAY_NAME
                if suffix == ""
                else f"{settings.MOCK_USER_DISPLAY_NAME} ({profile})"
            )
            # users.email 有唯一约束：不同 profile 必须是不同邮箱
            domain = settings.MOCK_USER_EMAIL.partition("@")[2] or "qlibquantlab.local"
            email = f"{username}@{domain}"
        return CurrentUser(
            user_id=user_id,
            username=username,
            email=email,
            org_id=settings.MOCK_ORG_ID,
            org_name=settings.MOCK_ORG_NAME,
            display_name=display,
            roles=roles,
            is_authenticated=True,
            provider=self.name,
        )

    # ---------------------------------------------------------------- 端口
    def get_login_url(self, state: str, redirect_to: str) -> str:
        return (
            "/api/v1/auth/mock/enter"
            f"?redirect_to={quote(redirect_to or '/')}&profile={DEFAULT_PROFILE}&state={quote(state)}"
        )

    def get_logout_url(self, redirect_to: str) -> str:
        return f"/login?logged_out=1&next={quote(redirect_to or '/')}"

    async def handle_callback(self, code: str, state: str) -> CurrentUser:
        _ = state
        return self._identity(code or DEFAULT_PROFILE)

    async def verify_token(self, token: str) -> CurrentUser | None:
        claims = decode_session_token(token, self._settings)
        return claims.to_user() if claims else None

    async def healthcheck(self) -> bool:
        return True
