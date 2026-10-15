"""缓存端口契约测试：memory 默认必跑；设置 TEST_REDIS_URL 时同时验证 redis。"""

from __future__ import annotations

import os

import pytest

from qqlab.adapters.cache.memory_cache import MemoryCacheProvider
from qqlab.ports.cache import CacheProvider, LockNotAcquired


def _implementations() -> list[tuple[str, CacheProvider]]:
    impls: list[tuple[str, CacheProvider]] = [("memory", MemoryCacheProvider())]
    url = os.environ.get("TEST_REDIS_URL")
    if url:
        from qqlab.adapters.cache.redis_cache import RedisCacheProvider

        impls.append(("redis", RedisCacheProvider(url)))
    return impls


@pytest.fixture(params=_implementations(), ids=lambda p: p[0])
def cache(request) -> CacheProvider:  # noqa: ANN001
    return request.param[1]


@pytest.mark.asyncio
async def test_set_get_delete(cache: CacheProvider) -> None:
    key = "contract:k1"
    await cache.delete(key)
    assert await cache.get(key) is None
    await cache.set(key, b"hello")
    assert await cache.get(key) == b"hello"
    await cache.delete(key)
    assert await cache.get(key) is None


@pytest.mark.asyncio
async def test_incr(cache: CacheProvider) -> None:
    key = "contract:counter"
    await cache.delete(key)
    assert await cache.incr(key) == 1
    assert await cache.incr(key) == 2
    await cache.delete(key)


@pytest.mark.asyncio
async def test_lock_exclusive(cache: CacheProvider) -> None:
    key = "contract:lock"
    async with cache.lock(key, ttl=5):
        with pytest.raises(LockNotAcquired):
            async with cache.lock(key, ttl=5, blocking_timeout=0.05):
                pass
    async with cache.lock(key, ttl=5):
        pass


@pytest.mark.asyncio
async def test_ping(cache: CacheProvider) -> None:
    assert await cache.ping() is True
