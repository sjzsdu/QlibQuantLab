"""worker handler 注册表（阶段 3：dataset_import + backtest；阶段 5 + train；阶段 6 + factor_compute）。"""

from __future__ import annotations

from qqlab.worker.handlers.backtest import make_backtest_handler
from qqlab.worker.handlers.dataset_import import make_dataset_import_handler, probe_dataset
from qqlab.worker.handlers.factor_compute import make_factor_compute_handler
from qqlab.worker.handlers.train import make_train_handler

__all__ = [
    "make_backtest_handler",
    "make_dataset_import_handler",
    "make_factor_compute_handler",
    "make_train_handler",
    "probe_dataset",
]
