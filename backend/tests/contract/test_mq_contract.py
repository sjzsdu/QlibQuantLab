"""消息队列端口契约：memory 默认必跑；设置 TEST_MQ_URL 时同时验证 rabbitmq。"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from qqlab.adapters.mq.memory_mq import MemoryMessageQueueProvider
from qqlab.ports.message_queue import Message, MessageQueueProvider


@pytest.fixture(params=["memory"], ids=lambda p: p)
def queue(request) -> MessageQueueProvider:  # noqa: ANN001
    if request.param == "rabbitmq":  # pragma: no cover - 可选集成
        from qqlab.adapters.mq.rabbitmq_mq import RabbitMQProvider

        return RabbitMQProvider(os.environ["TEST_MQ_URL"])
    return MemoryMessageQueueProvider()


@pytest.mark.asyncio
async def test_declare_publish_consume(queue: MessageQueueProvider) -> None:
    name = "contract_q"
    await queue.declare(name)
    handled: list[bytes] = []
    done = asyncio.Event()

    async def handler(message: Message) -> None:
        handled.append(message.body)
        await message.ack()
        done.set()

    await queue.publish(name, json.dumps({"kind": "ping"}).encode())
    task = asyncio.create_task(queue.consume(name, handler, concurrency=1))
    try:
        await asyncio.wait_for(done.wait(), timeout=5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await queue.close()
    assert handled, "应当消费到消息"


@pytest.mark.asyncio
async def test_ping(queue: MessageQueueProvider) -> None:
    assert await queue.ping() is True
    await queue.close()
