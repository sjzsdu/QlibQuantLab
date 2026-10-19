"""缓存端口契约测试：memory 默认必跑；设置 TEST_REDIS_URL 时同时验证 redis。

注意（阶段 8 · A 项实测踩坑）：provider **实例**不能在收集期建好后跨测试复用 ——
pytest-asyncio 每个测试函数一个事件循环，redis-py 连接池会把连接绑定在首个循环上，
第二个测试就报 ``Future attached to a different loop`` / ``Event loop is closed``。
因此这里参数化**工厂**，fixture 内每次新建、测完关闭。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable

import pytest

from qqlab.adapters.cache.memory_cache import MemoryCacheProvider
from qqlab.ports.cache import CacheProvider, LockNotAcquired


def _implementations() -> list[tuple[str, Callable[[], CacheProvider]]]:
    impls: list[tuple[str, Callable[[], CacheProvider]]] = [("memory", MemoryCacheProvider)]
    url = os.environ.get("TEST_REDIS_URL")
    if url:
        from qqlab.adapters.cache.redis_cache import RedisCacheProvider

        impls.append(("redis", lambda: RedisCacheProvider(url)))
    return impls


@pytest.fixture(params=_implementations(), ids=lambda p: p[0])
async def cache(request) -> AsyncIterator[CacheProvider]:  # noqa: ANN001
    provider = request.param[1]()
    try:
        yield provider
    finally:
        close = getattr(provider, "close", None)  # memory 无连接可关
        if close is not None:
            await close()


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
