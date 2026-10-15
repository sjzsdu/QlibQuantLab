"""会话与 CSRF Cookie 读写。

规则（前端契约）：
- ``qqlab_csrf`` **不是** HttpOnly，前端要读它并回填 ``X-CSRF-Token``；
- 每个响应只要还没有该 cookie 就要种上（见 CsrfCookieMiddleware）；
- ``qqlab_session`` 是 HttpOnly，前端只管带上 ``credentials: "include"``。
"""

from __future__ import annotations

from starlette.responses import Response

from qqlab.config import Settings
from qqlab.core.security import new_token
from qqlab.services import SessionBundle


def new_csrf_token() -> str:
    return new_token()


def set_session_cookies(response: Response, settings: Settings, bundle: SessionBundle) -> str:
    secure = settings.SESSION_COOKIE_SECURE
    csrf = bundle.csrf_token or new_csrf_token()
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        bundle.token,
        max_age=bundle.ttl_seconds,
        path="/",
        httponly=True,
        secure=secure,
        samesite="lax",
    )
    response.set_cookie(
        settings.CSRF_COOKIE_NAME,
        csrf,
        max_age=bundle.ttl_seconds,
        path="/",
        httponly=False,  # 前端需要读取
        secure=secure,
        samesite="lax",
    )
    return csrf


def ensure_csrf_cookie(response: Response, settings: Settings, existing: str | None) -> str:
    """响应里没有 CSRF cookie 时补种一个（保证首个写请求能带上 token）。"""
    if existing:
        return existing
    token = new_csrf_token()
    response.set_cookie(
        settings.CSRF_COOKIE_NAME,
        token,
        max_age=settings.APP_JWT_TTL_SECONDS,
        path="/",
        httponly=False,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite="lax",
    )
    return token


def clear_session_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(settings.CSRF_COOKIE_NAME, path="/")
