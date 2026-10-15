"""ComputePort 实现的装配（worker 进程专用；API 进程永远不 import 本包的 qlib 实现）。

`build_compute` 只在 `qqlab.worker.main` 被调用 —— 结构上保证 API 进程
即使误 import 也不会加载 qlib（qlib_compute 的 qlib 依赖全部是函数内延迟导入）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qqlab.core.logging import get_logger
from qqlab.ports.compute import ComputePort

if TYPE_CHECKING:
    from qqlab.config import Settings
    from qqlab.ports.storage import StorageProvider

logger = get_logger("qqlab.compute")

VALID_BACKENDS = ("qlib", "stub")


def build_compute(settings: Settings, storage: StorageProvider | None = None) -> ComputePort:
    backend = settings.COMPUTE_BACKEND
    if backend == "qlib":
        from qqlab.adapters.compute.qlib_compute import QlibComputeProvider  # noqa: PLC0415

        logger.info("compute_backend_selected", extra={"backend": "qlib"})
        return QlibComputeProvider(settings, storage)
    if backend == "stub":
        from qqlab.adapters.compute.stub_compute import StubComputeProvider  # noqa: PLC0415

        logger.info("compute_backend_selected", extra={"backend": "stub"})
        return StubComputeProvider(storage)
    raise ValueError(f"未知 COMPUTE_BACKEND={backend!r}（可选：{VALID_BACKENDS}）")


__all__ = ["VALID_BACKENDS", "build_compute"]
