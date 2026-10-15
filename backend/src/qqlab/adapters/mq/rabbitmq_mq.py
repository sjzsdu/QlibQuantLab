"""RabbitMQ 适配器（aio-pika）。

注意：这是**应用自己的**任务队列（vhost 由 MQ_URL 指定，默认 /qqlab），
与 Qlib-Server 内部的 task_queue / message_queue（vhost /，官方 pika 实现）是两套东西。
"""

from __future__ import annotations

import asyncio

import aio_pika
from aio_pika import DeliveryMode, IncomingMessage

from qqlab.core.logging import get_logger
from qqlab.ports.message_queue import Handler, Message

logger = get_logger("qqlab.mq.rabbitmq")


def _wrap(delivery: IncomingMessage) -> Message:
    headers = {str(k): str(v) for k, v in (delivery.headers or {}).items()}
    return Message(
        body=bytes(delivery.body),
        routing_key=delivery.routing_key,
        headers=headers,
        redelivered=delivery.message.redelivered,
    )


class RabbitMQProvider:
    name = "rabbitmq"

    def __init__(self, url: str, *, prefetch: int = 1) -> None:
        self._url = url
        self._prefetch = prefetch
        self._connection: aio_pika.RobustConnection | None = None
        self._channel: aio_pika.abc.AbstractChannel | None = None

    async def _ensure(self) -> aio_pika.abc.AbstractChannel:
        if self._channel is not None and not self._channel.is_closed:
            return self._channel
        self._connection = await aio_pika.connect_robust(self._url)
        self._channel = await self._connection.channel()
        await self._channel.set_qos(prefetch_count=self._prefetch)
        return self._channel

    async def declare(self, queue: str, *, durable: bool = True) -> None:
        channel = await self._ensure()
        await channel.declare_queue(queue, durable=durable)

    async def publish(
        self,
        routing_key: str,
        body: bytes,
        *,
        headers: dict[str, str] | None = None,
        persistent: bool = True,
    ) -> None:
        channel = await self._ensure()
        message = aio_pika.Message(
            body=body,
            delivery_mode=DeliveryMode.PERSISTENT if persistent else DeliveryMode.NOT_PERSISTENT,
            headers=headers or {},
        )
        await channel.default_exchange.publish(message, routing_key=routing_key)

    async def consume(
        self,
        queue: str,
        handler: Handler,
        *,
        prefetch: int = 1,
        concurrency: int = 1,
    ) -> None:
        channel = await self._ensure()
        await channel.set_qos(prefetch_count=prefetch)
        declared = await channel.declare_queue(queue, durable=True, auto_ack=False)
        sem = asyncio.Semaphore(max(1, concurrency))
        inflight: set[asyncio.Task] = set()

        async def _one(delivery: IncomingMessage) -> None:
            async with sem:
                try:
                    await handler(_wrap(delivery))
                except Exception:  # noqa: BLE001
                    logger.exception("mq_handler_failed", extra={"queue": queue})
                    await delivery.nack(requeue=False)
                else:
                    await delivery.ack()

        async with declared.iterator(timeout=30) as iterator:
            async for delivery in iterator:
                if concurrency <= 1:
                    await _one(delivery)
                else:
                    task = asyncio.create_task(_one(delivery))
                    inflight.add(task)
                    task.add_done_callback(inflight.discard)
        if inflight:  # pragma: no cover - 循环退出时通常已清空
            await asyncio.gather(*inflight, return_exceptions=True)

    async def ping(self) -> bool:
        try:
            channel = await self._ensure()
            return not channel.is_closed
        except Exception:  # noqa: BLE001
            return False

    async def close(self) -> None:
        try:
            if self._channel is not None and not self._channel.is_closed:
                await self._channel.close()
            if self._connection is not None and not self._connection.is_closed:
                await self._connection.close()
        except Exception:  # noqa: BLE001
            logger.warning("mq_close_failed", exc_info=True)
        finally:
            self._channel = None
            self._connection = None
