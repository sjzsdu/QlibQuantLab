"""健康检查与系统信息。"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request

from qqlab.api.deps import failure, get_settings, success
from qqlab.schemas import ReadyOut, SystemInfoOut

router = APIRouter(tags=["system"])


@router.get("/health/live")
async def health_live(request: Request) -> dict:
    """存活探针：进程活着就返回 200，不碰任何外部依赖。"""
    return success(request, {"status": "alive"})


@router.get("/health/ready")
async def health_ready(request: Request) -> dict:
    """就绪探针：数据库 / 缓存 / 队列 / 存储 / 认证 全部可用才算 ready。"""
    container = request.app.state.container
    checks = await container.healthcheck()
    payload = ReadyOut(
        status="ready" if checks.get("ready") else "degraded",
        checks={k: bool(v) for k, v in checks.items()},
    )
    if not checks.get("ready"):
        return failure(request, 1009, "部分依赖不可用", payload.model_dump())
    return success(request, payload.model_dump())


@router.get("/system/info")
async def system_info(request: Request) -> dict:
    """前端页脚展示的系统信息（不含任何密钥）。"""
    settings = get_settings(request)
    container = request.app.state.container
    info = SystemInfoOut(
        env=settings.APP_ENV,
        auth_provider=settings.AUTH_PROVIDER,
        database_backend=settings.DATABASE_BACKEND,
        cache_backend=settings.CACHE_BACKEND,
        mq_backend=settings.MQ_BACKEND,
        storage_backend=settings.STORAGE_BACKEND,
        qlib_server_ws_url=settings.QLIB_SERVER_WS_URL,
        uptime_seconds=round(time.monotonic() - container.started_at, 1),
    )
    return success(request, info.model_dump())
