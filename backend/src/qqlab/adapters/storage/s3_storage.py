"""S3 / MinIO 存储适配器（boto3，线程池执行阻塞调用）。

`STORAGE_BACKEND=s3` 与 `minio` 共用本实现，仅 endpoint 与寻址风格不同。
"""

from __future__ import annotations

import asyncio
from typing import Any, BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from qqlab.core.logging import get_logger
from qqlab.ports.storage import ObjectNotFoundError, ObjectStat


def _is_missing(exc: ClientError) -> bool:
    code = str(exc.response.get("Error", {}).get("Code", ""))
    status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0) or 0)
    return code in ("NoSuchKey", "404", "NotFound") or status == 404


logger = get_logger("qqlab.storage.s3")


class S3StorageProvider:
    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        path_style: bool = True,
        name: str = "s3",
    ) -> None:
        self.name = name
        self._bucket = bucket
        config = Config(
            s3={"addressing_style": "path" if path_style else "auto"},
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
        )
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=config,
        )

    async def put(self, key: str, data: bytes | BinaryIO, *, content_type: str | None = None) -> None:
        body = data if isinstance(data, bytes) else data.read()
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType=content_type or "application/octet-stream",
        )

    async def get(self, key: str) -> bytes:
        def _get() -> bytes:
            try:
                response = self._client.get_object(Bucket=self._bucket, Key=key)
            except ClientError as exc:
                if _is_missing(exc):
                    raise ObjectNotFoundError(key) from exc
                raise
            return response["Body"].read()

        return await asyncio.to_thread(_get)

    async def stat(self, key: str) -> ObjectStat:
        def _stat() -> ObjectStat:
            try:
                response = self._client.head_object(Bucket=self._bucket, Key=key)
            except ClientError as exc:
                if _is_missing(exc):
                    raise ObjectNotFoundError(key) from exc
                raise
            return ObjectStat(
                size=int(response["ContentLength"]),
                content_type=response.get("ContentType"),
                etag=str(response.get("ETag", "")).strip('"') or None,
            )

        return await asyncio.to_thread(_stat)

    async def list(self, prefix: str) -> list[str]:
        def _list() -> list[str]:
            keys: list[str] = []
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                for item in page.get("Contents", []):
                    keys.append(item["Key"])
            return keys

        return await asyncio.to_thread(_list)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)

    async def presign_get(self, key: str, expires: int = 600) -> str:
        return await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires,
        )

    async def ping(self) -> bool:
        """就绪检查 + 惰性建桶。

        任何失败（权限不足、端点不可达，例如 minio 容器未启动）都返回 False，
        **绝不抛异常** —— 否则 /health/ready 会变成 500 而不是「红灯」。
        """

        def _ping() -> bool:
            try:
                try:
                    self._client.head_bucket(Bucket=self._bucket)
                except ClientError:
                    self._client.create_bucket(Bucket=self._bucket)
            except Exception as exc:  # noqa: BLE001 - 健康检查不允许向外抛
                logger.warning(
                    "s3_unavailable",
                    extra={"bucket": self._bucket, "error": str(exc)},
                )
                return False
            return True

        return await asyncio.to_thread(_ping)

    @property
    def info(self) -> dict[str, Any]:
        return {"backend": self.name, "bucket": self._bucket}
