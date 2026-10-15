"""进程内内存队列：单测 / 单机开发用，模拟 RabbitMQ 的 durable 队列语义。"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable

from qqlab.core.logging import get_logger
from qqlab.ports.message_queue import Handler, Message

logger = get_logger("qqlab.mq.memory")


class MemoryMessageQueueProvider:
    name = "memory"

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[Message]] = defaultdict(asyncio.Queue)
        self._declared: set[str] = set()
        self._consumers: list[asyncio.Task] = []
        self._closed = False

    async def declare(self, queue: str, *, durable: bool = True) -> None:
        self._declared.add(queue)
        _ = durable  # 内存队列无持久化概念

    async def publish(
        self,
        routing_key: str,
        body: bytes,
        *,
        headers: dict[str, str] | None = None,
        persistent: bool = True,
    ) -> None:
        _ = persistent
        msg = Message(body=body, routing_key=routing_key, headers=dict(headers or {}))
        await self._queues[routing_key].put(msg)

    async def consume(
        self,
        queue: str,
        handler: Handler,
        *,
        prefetch: int = 1,
        concurrency: int = 1,
    ) -> None:
        """阻塞式消费循环（测试里通过 asyncio.create_task 驱动）。"""
        _ = prefetch
        await self.declare(queue)
        bucket = self._queues[queue]

        async def _run() -> None:
            while not self._closed:
                try:
                    msg = await asyncio.wait_for(bucket.get(), timeout=0.2)
                except TimeoutError:
                    continue
                try:
                    await handler(msg)
                except Exception:  # noqa: BLE001
                    logger.exception("mq_handler_failed", extra={"queue": queue})
                    await msg.nack(requeue=False)
                else:
                    await msg.ack()

        if concurrency > 1:
            for _ in range(concurrency):
                self._consumers.append(asyncio.create_task(_run()))
        else:
            await _run()

    async def ping(self) -> bool:
        return not self._closed

    async def close(self) -> None:
        self._closed = True
        for task in self._consumers:
            task.cancel()
        self._consumers.clear()

    # ---- 测试辅助 ----
    def pending(self, queue: str) -> int:
        return self._queues[queue].qsize()

    async def drain(self, queue: str, handler: Callable[[Message], Awaitable[None]], limit: int = 100) -> int:
        """把队列里已有的消息一次性喂给 handler（不启动常驻消费者）。"""
        bucket = self._queues[queue]
        handled = 0
        while handled < limit and not bucket.empty():
            msg = bucket.get_nowait()
            await handler(msg)
            await msg.ack()
            handled += 1
        return handled
