"""应用入口：FastAPI app、中间件装配、异常处理。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from qqlab.api.router import api_router
from qqlab.config import Settings, load_settings
from qqlab.container import Container
from qqlab.core.errors import AppError
from qqlab.core.logging import get_logger, setup_logging
from qqlab.core.middleware import (
    CsrfCookieMiddleware,
    CSRFMiddleware,
    RateLimitMiddleware,
    RequestContextMiddleware,
)

logger = get_logger("qqlab")

SERVICE_NAME = "qqlab"


def _envelope(request: Request, code: int, message: str, data: object = None) -> dict:
    return {
        "code": code,
        "message": message,
        "data": data,
        "request_id": getattr(request.state, "request_id", "-"),
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    setup_logging(settings.LOG_LEVEL)
    container = Container.build(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("startup", extra=container.describe())
        yield
        await container.dispose()
        logger.info("shutdown")

    app = FastAPI(
        title="QlibQuantLab API",
        version="0.1.0",
        description=(
            "量化研究平台 API。仅供研究与教育用途，不提供投资建议。"
            "所有接口按组织（org_id）隔离，敏感操作写审计日志。"
        ),
        lifespan=lifespan,
        docs_url="/api/docs" if not settings.is_production else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if not settings.is_production else None,
    )
    app.state.settings = settings
    app.state.container = container

    # ---- 异常处理（统一信封） ----
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=_envelope(request, exc.code, exc.message, exc.detail or None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # model_validator 抛出的 ValueError 会原样躺在 ctx.error 里 —— JSON 序列化前字符串化
        errors = exc.errors()
        for item in errors:
            if isinstance(item.get("ctx"), dict):
                item["ctx"] = {
                    k: (v if isinstance(v, str | int | float | bool | None) else str(v))
                    for k, v in item["ctx"].items()
                }
        return JSONResponse(
            status_code=422,
            content=_envelope(request, 1422, "请求参数校验失败", {"errors": errors}),
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", extra={"path": request.url.path})
        return JSONResponse(status_code=500, content=_envelope(request, 1500, "服务器内部错误"))

    # ---- 中间件：先加入的在内层，后加入的在外层 ----
    # 外 → 内：CORS → 请求上下文 → 限流 → CSRF cookie → CSRF 校验
    app.add_middleware(CSRFMiddleware, settings=settings)
    app.add_middleware(CsrfCookieMiddleware, settings=settings)
    app.add_middleware(RateLimitMiddleware, settings=settings, cache=container.cache)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    app.include_router(api_router)

    @app.get("/", include_in_schema=False)
    async def root() -> dict:
        return {
            "service": SERVICE_NAME,
            "docs": "/api/docs" if not settings.is_production else None,
        }

    return app


app = create_app()


def run() -> None:  # pragma: no cover - 进程入口
    import uvicorn

    from qqlab.config import load_settings

    settings = load_settings()
    uvicorn.run(
        "qqlab.main:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        reload=False,
    )
