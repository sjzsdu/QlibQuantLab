"""worker 入口：消费应用自己的任务队列并分发 handler。

阶段 3 注册 ``dataset_import`` / ``backtest`` handler（训练在阶段 5）。
计算实现由 ``COMPUTE_BACKEND`` 决定（qlib 真数据 / stub 合成对照）；
API 进程永远不 import qlib —— 本模块只在 worker 容器执行。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from qqlab.adapters.compute import build_compute
from qqlab.config import Settings, load_settings
from qqlab.container import Container
from qqlab.core.errors import ValidationAppError
from qqlab.core.logging import get_logger, setup_logging
from qqlab.models import JobKind
from qqlab.ports.message_queue import JOB_QUEUE, Message
from qqlab.repositories.job import recover_stale_running_jobs
from qqlab.worker.handlers import (
    make_backtest_handler,
    make_dataset_import_handler,
    make_factor_compute_handler,
    make_train_handler,
)

logger = get_logger("qqlab.worker")

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class Worker:
    def __init__(self, settings: Settings, container: Container, *, queue_name: str = JOB_QUEUE) -> None:
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
                "compute_backend": self.settings.COMPUTE_BACKEND,
            },
        )
        if self.settings.COMPUTE_BACKEND == "qlib":
            # 启动探测：qlib-server 不可达只告警不退出（消费循环继续，
            # 具体任务会在 run_backtest 里快速失败并把 job 标记 failed —— 见阶段 1 §7）
            from qqlab.worker.qlib_env import probe_qlib_server  # noqa: PLC0415

            ok, detail = probe_qlib_server(self.settings)
            logger.info("qlib_server_probe", extra={"ok": ok, "detail": detail})
        # R6-2：消费前先回收孤儿 running 任务（单副本前提见 recover_stale_running_jobs 注释）
        try:
            async with self.container.database.session() as session:
                stats = await recover_stale_running_jobs(
                    session, stale_minutes=self.settings.WORKER_STALE_JOB_MINUTES
                )
            if stats["requeued"] or stats["failed"]:
                logger.warning("stale_running_recovered", extra=stats)
        except Exception:  # noqa: BLE001 - 回收失败不阻断消费（只是孤儿任务暂留 running）
            logger.exception("stale_running_recover_failed")
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
    compute = build_compute(settings, container.storage)
    worker.register(JobKind.DATASET_IMPORT, make_dataset_import_handler(settings, container))
    worker.register(JobKind.BACKTEST, make_backtest_handler(settings, container, compute))
    worker.register(JobKind.TRAIN, make_train_handler(settings, container, compute))
    worker.register(JobKind.FACTOR_COMPUTE, make_factor_compute_handler(settings, container, compute))
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
