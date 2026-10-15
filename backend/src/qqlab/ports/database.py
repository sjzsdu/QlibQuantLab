"""数据库端口。业务代码不感知 asyncpg / aiosqlite / SQLAlchemy 的具体引擎配置。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@runtime_checkable
class DatabaseProvider(Protocol):
    name: str  # "postgres" | "sqlite"

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """带事务的会话：正常退出 commit，异常回滚。"""
        ...

    async def ping(self) -> bool:
        """就绪检查。"""
        ...

    async def dispose(self) -> None: ...

    @property
    def info(self) -> dict[str, Any]:
        """对外暴露的诊断信息（不含密码）。"""
        ...
