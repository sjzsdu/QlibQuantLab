"""对象存储端口。实现可切换 s3 / minio / local。

所有 key 由调用方（``core.tenant.OrgScope``）加 ``{org_id}/`` 前缀，端口层不做租户处理。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO, Protocol, runtime_checkable


class ObjectNotFoundError(KeyError):
    """对象不存在：所有存储实现必须抛同一个类型，调用方无需感知底层 SDK。"""


@dataclass(frozen=True, slots=True)
class ObjectStat:
    size: int
    content_type: str | None = None
    etag: str | None = None


@runtime_checkable
class StorageProvider(Protocol):
    name: str  # "s3" | "minio" | "local"

    async def put(self, key: str, data: bytes | BinaryIO, *, content_type: str | None = None) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def stat(self, key: str) -> ObjectStat: ...

    async def list(self, prefix: str) -> list[str]: ...

    async def delete(self, key: str) -> None: ...

    async def presign_get(self, key: str, expires: int = 600) -> str: ...

    async def ping(self) -> bool: ...
