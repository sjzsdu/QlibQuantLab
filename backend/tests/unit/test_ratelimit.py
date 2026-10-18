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
async def test_memory_cache_ttl_expiry_semantics(cache: MemoryCacheProvider) -> None:
    """锁死过期语义（阶段 7 补强 ①）：TTL 到期后 get 必须返回 None（惰性删除）。

    CasdoorAuthProvider 的 JWKS 缓存（TTL 1h）依赖此行为 —— 若过期后仍返回旧值，
    已轮换的签名密钥会被永久信任。
    """
    import asyncio

    await cache.set("exp", b"v", ttl=1)
    assert await cache.get("exp") == b"v"
    # 等过期（ttl=1 → monotonic 过期点在 set 后 1s）
    await asyncio.sleep(1.05)
    assert await cache.get("exp") is None
    # 过期读取后从存储里清除（不泄漏）；未过期键不受影响
    assert "exp" not in cache.keys()  # noqa: SIM118 - keys() 是测试辅助方法
    await cache.set("keep", b"v2", ttl=60)
    assert await cache.get("keep") == b"v2"


@pytest.mark.asyncio
async def test_memory_cache_ttl_zero_means_no_expiry(cache: MemoryCacheProvider) -> None:
    """ttl 缺省/0 → 永不过期（与 Redis 适配器语义一致）。"""
    await cache.set("forever", b"v")
    assert await cache.get("forever") == b"v"


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
