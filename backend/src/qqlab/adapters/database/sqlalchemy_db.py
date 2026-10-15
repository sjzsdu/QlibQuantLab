"""SQLAlchemy 异步数据库适配器（Postgres / SQLite 双后端）。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


def redact_url(url: str) -> str:
    """把 ``user:pass@`` 换成 ``user:***@``，用于日志与 /system/info。"""
    if "://" not in url or "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "@" not in rest:
        return url
    creds, host = rest.rsplit("@", 1)
    if ":" in creds:
        user = creds.split(":", 1)[0]
        return f"{scheme}://{user}:***@{host}"
    return f"{scheme}://***@{host}"


class SQLAlchemyDatabaseProvider:
    """实现 DatabaseProvider。业务代码只依赖端口，不感知引擎细节。"""

    def __init__(
        self,
        url: str,
        *,
        backend: str = "postgres",
        pool_size: int = 10,
        echo: bool = False,
    ) -> None:
        self.name = backend
        self._url = url
        kwargs: dict[str, Any]
        if url.startswith("sqlite"):
            # SQLite（测试）：单连接内存库，避免多个连接各看到一个空库
            kwargs = {
                "poolclass": StaticPool,
                "connect_args": {"check_same_thread": False},
            }
        else:
            kwargs = {"pool_size": pool_size, "max_overflow": pool_size * 2}
        self._engine: AsyncEngine = create_async_engine(url, echo=echo, **kwargs)
        self._factory = async_sessionmaker(self._engine, expire_on_commit=False, autoflush=False)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def ping(self) -> bool:
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:  # noqa: BLE001
            return False

    async def dispose(self) -> None:
        await self._engine.dispose()

    @property
    def info(self) -> dict[str, Any]:
        return {"backend": self.name, "url": redact_url(self._url)}
