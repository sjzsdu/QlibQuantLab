"""HTTP 中间件：请求上下文（request_id）、CSRF、限流。

装配顺序在 main.py 中固定（外 → 内）：CORS → 请求上下文 → 限流 → CSRF cookie 播种 → CSRF 校验。
"""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from qqlab.config import Settings
from qqlab.core.logging import get_logger, set_request_context
from qqlab.core.metrics import MetricsRegistry
from qqlab.core.ratelimit import TokenBucketLimiter
from qqlab.core.security import CSRF_HEADER, decode_session_token
from qqlab.core.security import new_token as new_csrf_token
from qqlab.ports.cache import CacheProvider

logger = get_logger("qqlab.http")

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_EXEMPT_PREFIXES = ("/api/v1/health", "/api/v1/auth")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """为每个请求分配 request_id（支持上游透传）并输出访问日志。

    同时记录 RED 指标（阶段 8 · D8-2）：``qqlab_http_requests_total`` 与
    ``qqlab_http_request_duration_ms`` 直方图，route 取**路由模板**
    （``scope["route"].path``，如 ``/api/v1/projects/{id}``）—— 不用原始 path，
    否则每个 id 一个序列会把指标基数打爆；未匹配（404）归 ``unmatched``。
    """

    def __init__(self, app: ASGIApp, metrics: MetricsRegistry | None = None) -> None:
        super().__init__(app)
        self._metrics = metrics

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = rid
        set_request_context(rid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - started) * 1000
            self._observe(request, "500", elapsed)
            logger.exception("request_failed", extra={"path": request.url.path, "ms": round(elapsed, 2)})
            raise
        elapsed = (time.perf_counter() - started) * 1000
        self._observe(request, str(response.status_code), elapsed)
        response.headers["X-Request-ID"] = rid
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": round(elapsed, 2),
            },
        )
        return response

    def _observe(self, request: Request, status: str, elapsed_ms: float) -> None:
        """RED 记录：路由模板优先查全路径映射（id 稳定），未匹配归 unmatched。"""
        if self._metrics is None:
            return
        route = request.scope.get("route")
        template = None
        if route is not None:
            templates: dict[int, str] = getattr(request.app.state, "route_templates", None) or {}
            template = templates.get(id(route)) or getattr(route, "path", None)
        labels = {
            "route": template if isinstance(template, str) and template else "unmatched",
            "method": request.method,
            "status": status,
        }
        self._metrics.inc("qqlab_http_requests_total", labels)
        self._metrics.observe_ms(
            "qqlab_http_request_duration_ms",
            elapsed_ms,
            {"route": labels["route"], "method": request.method},
        )


class CSRFMiddleware(BaseHTTPMiddleware):
    """双提交 cookie 校验。

    规则：当请求携带会话 cookie 时，非安全方法必须带与 ``qqlab_csrf`` 一致的
    ``X-CSRF-Token``。没有会话的请求（如登录本身）不受限。
    """

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        if request.method in _SAFE_METHODS:
            return await call_next(request)
        if _is_exempt(request.url.path):
            return await call_next(request)
        session = request.cookies.get(self._settings.SESSION_COOKIE_NAME)
        if not session:
            return await call_next(request)
        csrf_cookie = request.cookies.get(self._settings.CSRF_COOKIE_NAME, "")
        header = request.headers.get(CSRF_HEADER.lower(), "") or request.headers.get(CSRF_HEADER, "")
        if not csrf_cookie or header != csrf_cookie:
            return _json_error(
                request,
                status=403,
                code=1002,
                message="CSRF 校验失败：缺少或不匹配的 X-CSRF-Token",
            )
        return await call_next(request)


class CsrfCookieMiddleware(BaseHTTPMiddleware):
    """保证**每个响应**都带 ``qqlab_csrf`` cookie（前端首个写请求需要读它）。"""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        response = await call_next(request)
        cookie_name = self._settings.CSRF_COOKIE_NAME
        if cookie_name in request.cookies:
            return response
        existing = response.headers.get("set-cookie", "")
        if f"{cookie_name}=" in existing:
            return response
        response.set_cookie(
            cookie_name,
            new_csrf_token(),
            max_age=self._settings.APP_JWT_TTL_SECONDS,
            path="/",
            httponly=False,  # 前端 JS 需要读取
            secure=self._settings.SESSION_COOKIE_SECURE,
            samesite="lax",
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """按 IP/用户做固定窗口限流，缓存故障时放行（可用性优先）。"""

    def __init__(self, app: ASGIApp, settings: Settings, cache: CacheProvider) -> None:
        super().__init__(app)
        self._settings = settings
        self._limiter = TokenBucketLimiter(cache, prefix="qqlab:rl")

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        settings = self._settings
        if not settings.RATE_LIMIT_ENABLED or settings.APP_ENV == "test":
            return await call_next(request)
        if request.method in _SAFE_METHODS and not _is_login_path(request.url.path):
            return await call_next(request)

        identity = _client_ip(request)
        token = request.cookies.get(settings.SESSION_COOKIE_NAME)
        if token:
            claims = decode_session_token(token, settings)
            if claims:
                identity = f"user:{claims.user_id}"

        if _is_login_path(request.url.path):
            limit, kind = settings.RATE_LIMIT_LOGIN_PER_MIN, "login"
        elif request.method in _SAFE_METHODS:
            limit, kind = settings.RATE_LIMIT_READ_PER_MIN, "read"
        else:
            limit, kind = settings.RATE_LIMIT_WRITE_PER_MIN, "write"

        if await self._limiter.allow(f"{kind}:{identity}", limit):
            return await call_next(request)
        logger.warning("rate_limited", extra={"kind": kind, "identity": identity})
        return _json_error(
            request,
            status=429,
            code=1006,
            message=f"请求过于频繁（{kind} 限制 {limit}/分钟），请稍后重试",
        )


def _is_exempt(path: str) -> bool:
    return path.startswith(_EXEMPT_PREFIXES)


def _is_login_path(path: str) -> bool:
    return path.startswith("/api/v1/auth")


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _json_error(request: Request, *, status: int, code: int, message: str) -> Response:
    import json

    return Response(
        content=json.dumps(
            {
                "code": code,
                "message": message,
                "data": None,
                "request_id": getattr(request.state, "request_id", "-"),
            },
            ensure_ascii=False,
        ),
        status_code=status,
        media_type="application/json",
    )
