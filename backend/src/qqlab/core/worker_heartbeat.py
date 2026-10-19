"""worker 心跳共享键与读写（阶段 8 · B 项）。

放在 core（而非 worker 包）：**写方**是 worker 进程，**读方**是 API 的
``/api/v1/metrics`` —— API 不允许 import worker，worker 也不需要 import api，
双端只在 core 汇合。

单副本语义（与 ``WORKER_STALE_JOB_MINUTES`` 同一前提）：固定键、无 worker_id。
"""

from __future__ import annotations

import time

from qqlab.ports.cache import CacheProvider

#: 心跳键：value = epoch 秒（str），TTL = 3 倍间隔
HEARTBEAT_KEY = "qqlab:worker:heartbeat"
#: 启动时回收孤儿 running 任务的累计数（CacheProvider incr；缓存丢失即归零）
RECYCLED_KEY = "qqlab:worker:recycled_total"


async def write_heartbeat(cache: CacheProvider, *, interval: int) -> None:
    await cache.set(HEARTBEAT_KEY, str(time.time()).encode(), ttl=max(1, interval) * 3)


async def heartbeat_age(cache: CacheProvider, *, interval: int) -> float | None:
    """距最近心跳的秒数；无键/值非法返回 None（interval 供未来语义占位，当前不用）。"""
    raw = await cache.get(HEARTBEAT_KEY)
    if raw is None:
        return None
    try:
        ts = float(raw)
    except ValueError:
        return None
    return max(0.0, time.time() - ts)
