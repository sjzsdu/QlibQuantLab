"""令牌桶限流（基于可替换的 CacheProvider）。"""

from __future__ import annotations

import pytest

from qqlab.adapters.cache.memory_cache import MemoryCacheProvider
from qqlab.core.ratelimit import TokenBucketLimiter
from qqlab.ports.cache import LockNotAcquired


@pytest.fixture
def cache() -> MemoryCacheProvider:
    return MemoryCacheProvider()


@pytest.mark.asyncio
async def test_allow_up_to_limit_then_block(cache: MemoryCacheProvider) -> None:
    limiter = TokenBucketLimiter(cache, prefix="test")
    for i in range(5):
        assert await limiter.allow("u1", 5) is True, f"第 {i + 1} 次应放行"
    assert await limiter.allow("u1", 5) is False
    # 另一个身份不受影响
    assert await limiter.allow("u2", 5) is True


@pytest.mark.asyncio
async def test_cache_roundtrip_and_ttl(cache: MemoryCacheProvider) -> None:
    await cache.set("k", b"v", ttl=60)
    assert await cache.get("k") == b"v"
    await cache.delete("k")
    assert await cache.get("k") is None


@pytest.mark.asyncio
async def test_incr(cache: MemoryCacheProvider) -> None:
    assert await cache.incr("c", ttl=60) == 1
    assert await cache.incr("c", ttl=60) == 2
    assert await cache.get("c") == b"2"


@pytest.mark.asyncio
async def test_lock_exclusive(cache: MemoryCacheProvider) -> None:
    async with cache.lock("lock-1", ttl=5):
        with pytest.raises(LockNotAcquired):
            async with cache.lock("lock-1", ttl=5, blocking_timeout=0.05):
                pass
    # 释放后可以再次获取
    async with cache.lock("lock-1", ttl=5):
        pass
