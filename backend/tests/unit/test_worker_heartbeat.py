"""worker 心跳与回收计数（阶段 8 · B 项，core/worker_heartbeat + Worker 循环）。"""

from __future__ import annotations

import asyncio
import contextlib

from conftest import make_settings
from qqlab.adapters.cache.memory_cache import MemoryCacheProvider
from qqlab.container import Container
from qqlab.core.worker_heartbeat import (
    HEARTBEAT_KEY,
    RECYCLED_KEY,
    heartbeat_age,
    write_heartbeat,
)
from qqlab.worker.main import Worker


async def test_write_then_read_age_and_invalid_value() -> None:
    cache = MemoryCacheProvider()
    assert await heartbeat_age(cache, interval=10) is None  # 无键
    await write_heartbeat(cache, interval=10)
    age = await heartbeat_age(cache, interval=10)
    assert age is not None and 0 <= age < 5
    await cache.set(HEARTBEAT_KEY, b"not-a-timestamp")
    assert await heartbeat_age(cache, interval=10) is None  # 值非法不炸


async def test_heartbeat_loop_writes_immediately_then_cancels_cleanly() -> None:
    settings = make_settings(WORKER_HEARTBEAT_INTERVAL_SECONDS=30)
    container = Container.build(settings)
    try:
        worker = Worker(settings, container)
        task = asyncio.create_task(worker._heartbeat_loop())
        await asyncio.sleep(0.05)  # 循环首轮在 sleep 前就写
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        age = await heartbeat_age(container.cache, interval=30)
        assert age is not None and age < 5
    finally:
        await container.dispose()


async def test_record_recycled_increments_cache_counter() -> None:
    settings = make_settings()
    container = Container.build(settings)
    try:
        worker = Worker(settings, container)
        assert await container.cache.get(RECYCLED_KEY) is None
        await worker._record_recycled(3)
        assert int(await container.cache.get(RECYCLED_KEY)) == 3  # type: ignore[arg-type]
        await worker._record_recycled(1)
        assert int(await container.cache.get(RECYCLED_KEY)) == 4  # type: ignore[arg-type]
    finally:
        await container.dispose()
