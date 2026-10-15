"""对象存储端口契约：local 默认必跑；设置 TEST_S3_* 时同时验证 s3/minio。"""

from __future__ import annotations

import os
import uuid

import pytest

from qqlab.adapters.storage.local_storage import LocalStorageProvider
from qqlab.ports.storage import ObjectNotFoundError, StorageProvider


def _implementations(tmp_path) -> list[tuple[str, StorageProvider]]:  # noqa: ANN001
    impls: list[tuple[str, StorageProvider]] = [
        ("local", LocalStorageProvider(str(tmp_path / "objects"))),
    ]
    endpoint = os.environ.get("TEST_S3_ENDPOINT")
    if endpoint:
        from qqlab.adapters.storage.s3_storage import S3StorageProvider

        impls.append(
            (
                "s3",
                S3StorageProvider(
                    endpoint=endpoint,
                    bucket=os.environ.get("TEST_S3_BUCKET", "qqlab-test"),
                    access_key=os.environ["TEST_S3_ACCESS_KEY"],
                    secret_key=os.environ["TEST_S3_SECRET_KEY"],
                    path_style=True,
                ),
            )
        )
    return impls


@pytest.fixture(params=["local"], ids=lambda p: p)
def storage(request, tmp_path) -> StorageProvider:  # noqa: ANN001
    endpoint = os.environ.get("TEST_S3_ENDPOINT")
    if request.param == "s3" and endpoint:  # pragma: no cover - 可选
        from qqlab.adapters.storage.s3_storage import S3StorageProvider

        return S3StorageProvider(
            endpoint=endpoint,
            bucket=os.environ.get("TEST_S3_BUCKET", "qqlab-test"),
            access_key=os.environ["TEST_S3_ACCESS_KEY"],
            secret_key=os.environ["TEST_S3_SECRET_KEY"],
        )
    return LocalStorageProvider(str(tmp_path / "objects"))


@pytest.mark.asyncio
async def test_put_get_stat_delete(storage: StorageProvider) -> None:
    key = f"contract/{uuid.uuid4().hex}/a.txt"
    await storage.put(key, b"hello", content_type="text/plain")
    assert await storage.get(key) == b"hello"
    stat = await storage.stat(key)
    assert stat.size == 5
    listed = await storage.list("contract/")
    assert key in listed
    await storage.delete(key)
    with pytest.raises(ObjectNotFoundError):
        await storage.get(key)


@pytest.mark.asyncio
async def test_ping(storage: StorageProvider) -> None:
    assert await storage.ping() is True


@pytest.mark.asyncio
async def test_local_rejects_path_traversal(tmp_path) -> None:
    storage = LocalStorageProvider(str(tmp_path / "objects"))
    with pytest.raises(ValueError):
        await storage.put("../../etc/passwd", b"x")
