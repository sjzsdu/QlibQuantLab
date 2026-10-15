"""worker 入口：消费应用自己的任务队列并分发 handler。

阶段 2 只交付骨架与分发器；阶段 3 起注册 ``dataset_import`` / ``train`` /
``backtest`` / ``factor_compute`` handler（跑在独立容器里，API 进程不 import qlib）。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from qqlab.config import Settings, load_settings
from qqlab.container import Container
from qqlab.core.errors import ValidationAppError
from qqlab.core.logging import get_logger, setup_logging
from qqlab.ports.message_queue import Message

logger = get_logger("qqlab.worker")

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

#: 阶段 2 默认任务队列（应用自己的 vhost，不是 Qlib-Server 的 task_queue）
DEFAULT_QUEUE = "qqlab_jobs"


class Worker:
    def __init__(self, settings: Settings, container: Container, *, queue_name: str = DEFAULT_QUEUE) -> None:
        self.settings = settings
        self.container = container
        self.queue_name = queue_name
        self._handlers: dict[str, Handler] = {}

    def register(self, kind: str, handler: Handler) -> None:
        self._handlers[kind] = handler
        logger.info("handler_registered", extra={"kind": kind})

    @property
    def registered_kinds(self) -> list[str]:
        return sorted(self._handlers)

    async def dispatch(self, message: Message) -> None:
        """把一条消息路由到已注册 handler；未知类型 nack 且不重投。"""
        try:
            payload = json.loads(message.body.decode("utf-8"))
            kind = str(payload.get("kind", ""))
        except (ValueError, UnicodeDecodeError) as exc:
            logger.error("job_payload_invalid", extra={"error": str(exc)})
            await message.nack(requeue=False)
            return

        handler = self._handlers.get(kind)
        if handler is None:
            logger.error(
                "job_kind_unhandled",
                extra={"kind": kind, "known": self.registered_kinds},
            )
            await message.nack(requeue=False)
            return

        try:
            result = await handler(payload)
        except ValidationAppError as exc:
            logger.error("job_rejected", extra={"kind": kind, "error": exc.message})
            await message.nack(requeue=False)
        except Exception as exc:  # noqa: BLE001 - 单条任务失败不应终止消费者
            logger.exception("job_failed", extra={"kind": kind, "error": str(exc)})
            await message.nack(requeue=False)
        else:
            logger.info("job_done", extra={"kind": kind, "result": result})
            await message.ack()

    async def run(self) -> None:
        concurrency = max(1, self.settings.QLIB_WORKER_CONCURRENCY)
        logger.info(
            "worker_start",
            extra={
                "queue": self.queue_name,
                "concurrency": concurrency,
                "kinds": self.registered_kinds,
            },
        )
        await self.container.queue.declare(self.queue_name)
        await self.container.queue.consume(
            self.queue_name,
            self.dispatch,
            prefetch=self.settings.MQ_PREFETCH,
            concurrency=concurrency,
        )


def build_worker(settings: Settings | None = None) -> Worker:
    settings = settings or load_settings()
    container = Container.build(settings)
    worker = Worker(settings, container)
    # 阶段 3 在这里注册：worker.register(JobKind.DATASET_IMPORT, ...)
    return worker


def main() -> None:  # pragma: no cover - 进程入口
    settings = load_settings()
    setup_logging(settings.LOG_LEVEL)
    worker = build_worker(settings)
    try:
        asyncio.run(worker.run())
    except KeyboardInterrupt:  # pragma: no cover
        logger.info("worker_interrupted")


if __name__ == "__main__":  # pragma: no cover
    main()
