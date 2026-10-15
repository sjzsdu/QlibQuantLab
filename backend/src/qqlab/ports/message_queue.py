"""消息队列端口。实现可切换 rabbitmq / memory。

注意：这是**应用自己的**任务队列（vhost /qqlab），与 Qlib-Server 内部的
task_queue / message_queue（vhost /，官方 pika 实现）是两套东西，后者不经过本端口。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class Message:
    body: bytes
    routing_key: str
    headers: dict[str, str] = field(default_factory=dict)
    redelivered: bool = False
    _acked: bool = False
    _requeued: bool = False

    async def ack(self) -> None:
        self._acked = True

    async def nack(self, requeue: bool = False) -> None:
        self._requeued = requeue

    @property
    def settled(self) -> bool:
        return self._acked or self._requeued


Handler = Callable[[Message], Awaitable[None]]

#: 应用自己的任务队列名（vhost 见 MQ_URL）。worker 消费、JobService 发布，
#: 两边共用本常量防命名漂移 —— 放端口模块而非 services，因为 worker（py3.11）
#: 不能 import services（其 __init__ 链到 schemas 的 PEP 695 语法，需 py3.12）。
JOB_QUEUE = "qqlab_jobs"


@runtime_checkable
class MessageQueueProvider(Protocol):
    name: str  # "rabbitmq" | "memory"

    async def publish(
        self,
        routing_key: str,
        body: bytes,
        *,
        headers: dict[str, str] | None = None,
        persistent: bool = True,
    ) -> None: ...

    async def consume(
        self,
        queue: str,
        handler: Handler,
        *,
        prefetch: int = 1,
        concurrency: int = 1,
    ) -> None:
        """阻塞式消费循环；handler 抛异常则 nack(requeue=False)。"""
        ...

    async def declare(self, queue: str, *, durable: bool = True) -> None: ...

    async def ping(self) -> bool: ...

    async def close(self) -> None: ...
