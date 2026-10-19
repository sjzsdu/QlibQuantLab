"""适配器（Adapters）：端口的具体实现。

铁律：第三方 SDK（redis / aio_pika / boto3 / qlib / casdoor / socketio）只能出现在本包内。
"""

from qqlab.adapters.audit.db_audit_writer import DbAuditWriter
from qqlab.adapters.audit.platform_audit_trail import PlatformAuditTrail
from qqlab.adapters.auth.casdoor_provider import CasdoorAuthProvider
from qqlab.adapters.auth.mock_provider import MockAuthProvider
from qqlab.adapters.cache.memory_cache import MemoryCacheProvider
from qqlab.adapters.cache.redis_cache import RedisCacheProvider
from qqlab.adapters.database.sqlalchemy_db import SQLAlchemyDatabaseProvider, redact_url
from qqlab.adapters.mq.memory_mq import MemoryMessageQueueProvider
from qqlab.adapters.mq.rabbitmq_mq import RabbitMQProvider
from qqlab.adapters.storage.local_storage import LocalStorageProvider
from qqlab.adapters.storage.s3_storage import S3StorageProvider

__all__ = [
    "CasdoorAuthProvider",
    "DbAuditWriter",
    "LocalStorageProvider",
    "MemoryCacheProvider",
    "MemoryMessageQueueProvider",
    "MockAuthProvider",
    "PlatformAuditTrail",
    "RabbitMQProvider",
    "RedisCacheProvider",
    "S3StorageProvider",
    "SQLAlchemyDatabaseProvider",
    "redact_url",
]
