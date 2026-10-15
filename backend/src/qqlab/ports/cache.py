"""缓存与分布式锁端口。实现可切换 redis / valkey / dragonfly / memory。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol, runtime_checkable


class Lock(Protocol):
    async def reentrant_acquire(self) -> None:
        """续租（心跳）。"""
        ...

    async def release(self) -> None: ...


@runtime_checkable
class CacheProvider(Protocol):
    name: str  # "redis" | "valkey" | "dragonfly" | "memory"

    async def get(self, key: str) -> bytes | None: ...

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def incr(self, key: str, ttl: int | None = None) -> int: ...

    @asynccontextmanager
    async def lock(
        self,
        key: str,
        *,
        ttl: int,
        blocking_timeout: float = 0.0,
    ) -> AsyncIterator[Lock]:
        """分布式锁：在 ``blocking_timeout`` 内拿不到锁则抛 ``LockNotAcquired``。"""
        ...

    async def ping(self) -> bool: ...


class LockNotAcquired(RuntimeError):
    """未能在超时内取得锁。"""
