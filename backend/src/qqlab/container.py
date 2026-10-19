"""依赖装配根（Composition Root）。

**唯一**允许同时 import ``ports`` 与 ``adapters`` 的地方：
环境开关在这里被换成具体实现（Ports & Adapters 的「组装线」）。
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

from qqlab.adapters import (
    CasdoorAuthProvider,
    DbAuditWriter,
    LocalStorageProvider,
    MemoryCacheProvider,
    MemoryMessageQueueProvider,
    MockAuthProvider,
    PlatformAuditTrail,
    RabbitMQProvider,
    RedisCacheProvider,
    S3StorageProvider,
    SQLAlchemyDatabaseProvider,
)
from qqlab.config import Settings
from qqlab.core.errors import ConfigError
from qqlab.ports.audit import AuditWriter
from qqlab.ports.auth import AuthProvider
from qqlab.ports.cache import CacheProvider
from qqlab.ports.database import DatabaseProvider
from qqlab.ports.message_queue import MessageQueueProvider
from qqlab.ports.storage import StorageProvider


class Container:
    def __init__(
        self,
        settings: Settings,
        *,
        database: DatabaseProvider,
        cache: CacheProvider,
        queue: MessageQueueProvider,
        storage: StorageProvider,
        auth: AuthProvider,
        audit: AuditWriter,
    ) -> None:
        self.settings = settings
        self.database = database
        self.cache = cache
        self.queue = queue
        self.storage = storage
        self.auth = auth
        self.audit = audit
        self.started_at = time.monotonic()

    # ------------------------------------------------------------ 装配
    @classmethod
    def build(cls, settings: Settings) -> Container:
        # 1. 数据库
        database = SQLAlchemyDatabaseProvider(
            settings.DATABASE_URL,
            backend=settings.DATABASE_BACKEND,
            pool_size=settings.DATABASE_POOL_SIZE,
            echo=settings.DATABASE_ECHO,
        )

        # 2. 缓存
        cache: CacheProvider
        if settings.CACHE_BACKEND == "memory":
            cache = MemoryCacheProvider()
        else:
            cache = RedisCacheProvider(settings.CACHE_URL, name=settings.CACHE_BACKEND)

        # 3. 消息队列
        queue: MessageQueueProvider
        if settings.MQ_BACKEND == "memory":
            queue = MemoryMessageQueueProvider()
        else:
            queue = RabbitMQProvider(settings.MQ_URL, prefetch=settings.MQ_PREFETCH)

        # 4. 对象存储
        storage: StorageProvider
        if settings.STORAGE_BACKEND == "local":
            storage = LocalStorageProvider(settings.STORAGE_LOCAL_ROOT)
        else:
            storage = S3StorageProvider(
                endpoint=settings.STORAGE_S3_ENDPOINT,
                bucket=settings.STORAGE_S3_BUCKET,
                access_key=settings.STORAGE_S3_ACCESS_KEY,
                secret_key=settings.STORAGE_S3_SECRET_KEY,
                path_style=settings.STORAGE_S3_PATH_STYLE,
                name=settings.STORAGE_BACKEND,
            )

        # 5. 认证（未实现的实现 → 启动即失败，绝不静默降级成 mock）
        auth = cls._build_auth(settings, cache)

        # 6. 审计（阶段 8 · D8-5：装饰器把平台事件双写 platform_audit_events，
        #    剪枝节流；租户审计主路径行为不变）
        audit: AuditWriter = PlatformAuditTrail(
            DbAuditWriter(database),
            database,
            cache,
            retention_days=settings.PLATFORM_AUDIT_RETENTION_DAYS,
        )

        return cls(
            settings,
            database=database,
            cache=cache,
            queue=queue,
            storage=storage,
            auth=auth,
            audit=audit,
        )

    @staticmethod
    def _build_auth(settings: Settings, cache: CacheProvider) -> AuthProvider:
        if settings.AUTH_PROVIDER == "mock":
            return MockAuthProvider(settings)
        if settings.AUTH_PROVIDER == "casdoor":
            provider = CasdoorAuthProvider(settings, cache=cache)
            if not getattr(provider, "IMPLEMENTED", False):
                raise ConfigError(
                    "AUTH_PROVIDER=casdoor 但 CasdoorAuthProvider 尚未实现（阶段 7 交付）。"
                    "阶段 1-6 请使用 AUTH_PROVIDER=mock，或补全 OIDC 流程后将 IMPLEMENTED 置为 True。"
                )
            return provider
        raise ConfigError(f"不支持的 AUTH_PROVIDER: {settings.AUTH_PROVIDER}")

    # ------------------------------------------------------------ 健康检查
    async def healthcheck(self) -> dict[str, Any]:
        results: dict[str, Any] = {
            "database": await self.database.ping(),
            "cache": await self.cache.ping(),
            "queue": await self.queue.ping(),
            "storage": await self.storage.ping(),
            "auth": await self.auth.healthcheck(),
        }
        results["ready"] = all(bool(v) for v in results.values())
        return results

    async def dispose(self) -> None:
        """优雅关闭时释放外部连接。"""
        for closer in (getattr(self.queue, "close", None), getattr(self.cache, "close", None)):
            if callable(closer):
                with contextlib.suppress(Exception):
                    await closer()
        await self.database.dispose()

    def describe(self) -> dict[str, Any]:
        return {
            "auth_provider": self.auth.name,
            "database": self.database.info if hasattr(self.database, "info") else {},
            "cache_backend": self.cache.name,
            "mq_backend": self.queue.name,
            "storage_backend": self.storage.name,
        }
