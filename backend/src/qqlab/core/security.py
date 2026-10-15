"""会话令牌与 CSRF。

- 无论 mock 还是 casdoor，**本平台只认自己签发的会话 cookie**，
  IdP 令牌只在后端留存。因此阶段 7 切换认证时前端零改动。
- CSRF 采用双提交 cookie：非安全方法必须带 ``X-CSRF-Token``，值等于 ``qqlab_csrf`` cookie。
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from qqlab.config import Settings
from qqlab.ports.auth import CurrentUser, Role

ALGORITHM = "HS256"
CSRF_HEADER = "X-CSRF-Token"


@dataclass(frozen=True, slots=True)
class SessionClaims:
    user_id: str
    username: str
    display_name: str | None
    email: str | None
    org_id: str
    org_name: str | None
    roles: tuple[Role, ...]
    provider: str
    jti: str

    def to_user(self) -> CurrentUser:
        return CurrentUser(
            user_id=self.user_id,
            username=self.username,
            org_id=self.org_id,
            roles=self.roles,
            email=self.email,
            display_name=self.display_name,
            org_name=self.org_name,
            is_authenticated=True,
            provider=self.provider,
        )


def new_token() -> str:
    return secrets.token_urlsafe(32)


def issue_session_token(user: CurrentUser, settings: Settings) -> str:
    now = datetime.now(tz=UTC)
    payload = {
        "sub": user.user_id,
        "uname": user.username,
        "disp": user.display_name,
        "email": user.email,
        "org": user.org_id,
        "org_name": user.org_name,
        "roles": [r.value for r in user.roles],
        "prov": user.provider,
        "jti": new_token(),
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(seconds=settings.APP_JWT_TTL_SECONDS),
    }
    return jwt.encode(payload, settings.APP_JWT_SECRET, algorithm=ALGORITHM)


def decode_session_token(token: str, settings: Settings) -> SessionClaims | None:
    """校验会话令牌，任何失败都返回 None（调用方转 401，不泄露细节）。"""
    try:
        data = jwt.decode(token, settings.APP_JWT_SECRET, algorithms=[ALGORITHM])
        raw_roles = data.get("roles", [])
        if not isinstance(raw_roles, (list, tuple)):
            return None
        known = {role.value for role in Role}
        if any(str(value) not in known for value in raw_roles):
            # 未知角色 → 整个令牌作废（fail-closed，避免静默丢权限后继续用旧会话）
            return None
        roles = Role.parse_all(raw_roles)
        user_id = data.get("sub")
        org_id = data.get("org")
        username = data.get("uname")
        if not user_id or not org_id or not username:
            return None
        return SessionClaims(
            user_id=str(user_id),
            username=str(username),
            display_name=data.get("disp"),
            email=data.get("email"),
            org_id=str(org_id),
            org_name=data.get("org_name"),
            roles=roles,
            provider=str(data.get("prov", "mock")),
            jti=str(data.get("jti", "")),
        )
    except jwt.PyJWTError:
        return None
    except (TypeError, ValueError):
        return None
