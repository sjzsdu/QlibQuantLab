"""Ports（端口）：应用对外部世界的所有抽象。

铁律（由 tests/architecture/test_import_boundaries.py 强制）：
- 本包只能 import 标准库与 typing，**不得** import 任何第三方 SDK；
- 业务代码（api/services/repositories/models/core）只能依赖本包，不得依赖 adapters。
"""

from qqlab.ports.audit import AuditAction, AuditWriter
from qqlab.ports.auth import AuthProvider, CurrentUser, Role
from qqlab.ports.cache import CacheProvider, Lock, LockNotAcquired
from qqlab.ports.compute import BacktestResult, BacktestSpec, ComputePort, CostConfig
from qqlab.ports.database import DatabaseProvider
from qqlab.ports.message_queue import Message, MessageQueueProvider
from qqlab.ports.storage import ObjectStat, StorageProvider

__all__ = [
    "AuditAction",
    "AuditWriter",
    "AuthProvider",
    "BacktestResult",
    "BacktestSpec",
    "CacheProvider",
    "ComputePort",
    "CostConfig",
    "CurrentUser",
    "DatabaseProvider",
    "Lock",
    "LockNotAcquired",
    "Message",
    "MessageQueueProvider",
    "ObjectStat",
    "Role",
    "StorageProvider",
]
