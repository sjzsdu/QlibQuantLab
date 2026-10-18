"""认证端点：登录发起 / mock 一键进入 / 回调 / 登出。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse

from qqlab.api.cookies import clear_session_cookies, set_session_cookies
from qqlab.api.deps import (
    client_ip,
    get_audit_ctx,
    get_auth_service,
    get_optional_user,
    get_settings,
    success,
)
from qqlab.core.errors import NotFoundError, UnauthorizedError
from qqlab.core.logging import get_logger
from qqlab.ports.audit import AuditAction
from qqlab.schemas import CurrentUserOut, LoginStartOut, LogoutOut, MockEnterIn
from qqlab.services import AuthService, safe_redirect

logger = get_logger("qqlab.api.auth")

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(user) -> dict:  # noqa: ANN001
    return CurrentUserOut(
        user_id=user.user_id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        org_id=user.org_id,
        org_name=user.org_name,
        roles=[r.value for r in user.roles],
        is_authenticated=user.is_authenticated,
        provider=user.provider,
    ).model_dump()


@router.get("/login", summary="发起登录，返回跳转地址")
async def login_start(
    request: Request,
    redirect_to: str | None = None,
    service: AuthService = Depends(get_auth_service),
) -> dict:
    start = await service.begin_login(redirect_to)
    return success(request, LoginStartOut(url=start.url, state=start.state).model_dump())


def _mock_guard(request: Request) -> None:
    settings = get_settings(request)
    if settings.AUTH_PROVIDER != "mock":
        raise NotFoundError("mock 登录未启用（当前 AUTH_PROVIDER 不是 mock）")


@router.get("/mock/enter", summary="mock 一键进入（302 跳回原页面）", include_in_schema=False)
async def mock_enter_get(
    request: Request,
    profile: str | None = None,
    redirect_to: str = "/",
    state: str | None = None,
) -> Response:
    """登录页「一键进入」：构造身份 → 落库 → 种 cookie → 302。"""
    _mock_guard(request)
    settings = get_settings(request)
    container = request.app.state.container
    service = get_auth_service(request)
    identity = await container.auth.handle_callback(profile or "", state or "")
    bundle = await service.login_for_identity(identity, redirect_to=redirect_to)
    response = RedirectResponse(safe_redirect(bundle.redirect_to), status_code=302)
    set_session_cookies(response, settings, bundle)
    logger.info("mock_login", extra={"username": bundle.user.username, "ip": client_ip(request)})
    return response


@router.post("/mock/enter", summary="mock 登录（JSON 返回，供脚本 / 测试使用）")
async def mock_enter_post(
    request: Request,
    payload: MockEnterIn,
    response: Response,
    service: AuthService = Depends(get_auth_service),
) -> dict:
    _mock_guard(request)
    settings = get_settings(request)
    container = request.app.state.container
    identity = await container.auth.handle_callback(payload.profile or "", "")
    bundle = await service.login_for_identity(identity, redirect_to=payload.redirect_to)
    set_session_cookies(response, settings, bundle)
    return success(request, _user_out(bundle.user))


@router.get("/callback", summary="OIDC 回调（阶段 7 使用；mock 亦可走此路径）")
async def auth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    service: AuthService = Depends(get_auth_service),
    ctx=Depends(get_audit_ctx),
) -> Response:
    # Casdoor 在用户拒绝授权 / 登录失败时会带 error= 回跳（OIDC 错误重定向）
    if error:
        logger.warning(
            "oidc_callback_error",
            extra={"error": error, "error_description": error_description},
        )
        await request.app.state.container.audit.record(
            action=AuditAction.AUTH_LOGIN_FAILED,
            resource_type="auth",
            resource_id=None,
            outcome="failure",
            detail={"reason": "oidc_error", "error": error},
            ip=ctx.ip,
        )
        raise UnauthorizedError(f"登录失败：{error_description or error}")
    settings = get_settings(request)
    bundle = await service.handle_callback(code or "", state or "", ip=ctx.ip)
    response = RedirectResponse(safe_redirect(bundle.redirect_to), status_code=302)
    set_session_cookies(response, settings, bundle)
    return response


@router.get("/logout", summary="登出")
async def logout(
    request: Request,
    response: Response,
    next: str | None = None,  # noqa: A002
    user=Depends(get_optional_user),
    service: AuthService = Depends(get_auth_service),
    ctx=Depends(get_audit_ctx),
) -> dict:
    settings = get_settings(request)
    container = request.app.state.container
    await service.logout(user, ctx)
    clear_session_cookies(response, settings)
    # mock → 站内 /login?logged_out=1；casdoor → Casdoor /api/logout（RP-initiated logout）
    return success(
        request,
        LogoutOut(redirect_to=container.auth.get_logout_url(safe_redirect(next))).model_dump(),
        message="已登出",
    )
