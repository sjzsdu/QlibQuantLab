"""进程内内存缓存：单测 / 单机开发用。

语义与 Redis 适配器保持一致（TTL、计数器、锁），保证可互换。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from qqlab.ports.cache import Lock, LockNotAcquired


class _MemoryLock:
    def __init__(self, store: dict[str, tuple[bytes, float | None]], key: str, ttl: int) -> None:
        self._store = store
        self._key = key
        self._ttl = ttl

    async def reentrant_acquire(self) -> None:
        self._store[self._key] = (b"1", time.monotonic() + self._ttl)

    async def release(self) -> None:
        self._store.pop(self._key, None)


class MemoryCacheProvider:
    name = "memory"

    def __init__(self) -> None:
        self._data: dict[str, tuple[bytes, float | None]] = {}
        self._counter: dict[str, int] = {}
        self._lock = asyncio.Lock()

    # ---- 内部：统一过期处理 ----
    def _alive(self, key: str) -> tuple[bytes, float | None] | None:
        item = self._data.get(key)
        if item is None:
            return None
        value, expires = item
        if expires is not None and expires <= time.monotonic():
            self._data.pop(key, None)
            self._counter.pop(key, None)
            return None
        return value, expires

    async def get(self, key: str) -> bytes | None:
        item = self._alive(key)
        return item[0] if item else None

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        expires = time.monotonic() + ttl if ttl else None
        self._data[key] = (value, expires)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)
        self._counter.pop(key, None)

    async def incr(self, key: str, ttl: int | None = None) -> int:
        async with self._lock:
            item = self._alive(key)
            if item is None:
                self._counter[key] = 1
                self._data[key] = (b"1", time.monotonic() + ttl if ttl else None)
                return 1
            value = int(item[0]) + 1
            self._counter[key] = value
            self._data[key] = (str(value).encode(), item[1])
            return value

    @asynccontextmanager
    async def lock(self, key: str, *, ttl: int, blocking_timeout: float = 0.0) -> AsyncIterator[Lock]:
        deadline = time.monotonic() + blocking_timeout
        while True:
            existing = self._alive(key)
            if existing is None:
                self._data[key] = (b"1", time.monotonic() + ttl)
                break
            if time.monotonic() >= deadline:
                raise LockNotAcquired(f"未能在 {blocking_timeout}s 内取得锁: {key}")
            await asyncio.sleep(0.02)
        try:
            yield _MemoryLock(self._data, key, ttl)
        finally:
            self._alive(key)  # 刷新过期检查
            self._data.pop(key, None)

    async def ping(self) -> bool:
        return True

    # ---- 测试辅助 ----
    def keys(self) -> list[str]:
        return [k for k in list(self._data) if self._alive(k) is not None]

    async def clear(self) -> None:
        self._data.clear()
        self._counter.clear()
