"""Redis / Valkey / Dragonfly 缓存适配器。

三者协议兼容，共用本实现（URL 前缀分别为 redis:// valkey:// dragonfly://，均由 redis-py 解析）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import LockError

from qqlab.ports.cache import Lock, LockNotAcquired


class _RedisLock:
    def __init__(self, lock: Any, ttl: int) -> None:
        self._lock = lock
        self._ttl = ttl

    async def reentrant_acquire(self) -> None:
        """续租：把锁的过期时间重置为 ttl。"""
        try:
            await self._lock.extend(self._ttl, replace_ttl=True)
        except AttributeError:  # pragma: no cover - 旧版 redis-py
            await self._lock.reacquire()

    async def release(self) -> None:
        # 已过期或已被释放：忽略
        with suppress(LockError):
            await self._lock.release()


class RedisCacheProvider:
    def __init__(self, url: str, *, name: str = "redis") -> None:
        self.name = name
        self._url = url
        self._redis: Redis = Redis.from_url(url, decode_responses=False)

    async def get(self, key: str) -> bytes | None:
        return await self._redis.get(key)

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        await self._redis.set(key, value, ex=ttl)

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    async def incr(self, key: str, ttl: int | None = None) -> int:
        value = int(await self._redis.incr(key))
        if ttl and value == 1:
            await self._redis.expire(key, ttl)
        return value

    @asynccontextmanager
    async def lock(self, key: str, *, ttl: int, blocking_timeout: float = 0.0) -> AsyncIterator[Lock]:
        lock = self._redis.lock(
            key,
            timeout=ttl,
            blocking_timeout=blocking_timeout if blocking_timeout > 0 else 0.001,
            thread_local=False,
        )
        try:
            acquired = await lock.acquire(blocking=blocking_timeout > 0)
        except LockError as exc:  # pragma: no cover - 版本差异
            raise LockNotAcquired(str(exc)) from exc
        if not acquired:
            raise LockNotAcquired(f"未能在 {blocking_timeout}s 内取得锁: {key}")
        try:
            yield _RedisLock(lock, ttl)
        finally:
            with suppress(LockError):  # pragma: no cover - 已过期
                await lock.release()

    async def ping(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except Exception:  # noqa: BLE001
            return False

    async def close(self) -> None:
        await self._redis.aclose()
