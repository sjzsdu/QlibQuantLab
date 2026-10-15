"""基于 CacheProvider 的令牌桶限流（不依赖任何具体缓存实现）。"""

from __future__ import annotations

from qqlab.ports.cache import CacheProvider


class TokenBucketLimiter:
    """固定窗口计数（按分钟）。实现简单、可被 Redis/Memory 一致实现。"""

    def __init__(self, cache: CacheProvider, *, prefix: str = "rl") -> None:
        self._cache = cache
        self._prefix = prefix

    async def allow(self, identity: str, limit_per_min: int) -> bool:
        """返回是否放行；超限返回 False。"""
        if limit_per_min <= 0:
            return False
        bucket = f"{self._prefix}:{identity}:{_window()}"
        try:
            count = await self._cache.incr(bucket, ttl=60)
        except Exception:  # noqa: BLE001 - 限流器故障不应阻断请求
            return True
        return count <= limit_per_min

    async def remaining(self, identity: str, limit_per_min: int) -> int:
        bucket = f"{self._prefix}:{identity}:{_window()}"
        raw = await self._cache.get(bucket)
        used = int(raw or 0)
        return max(0, limit_per_min - used)


def _window() -> str:
    """当前分钟窗口（UTC）。"""
    from datetime import UTC, datetime

    return datetime.now(tz=UTC).strftime("%Y%m%d%H%M")
