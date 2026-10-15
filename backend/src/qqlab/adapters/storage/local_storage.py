"""本地文件系统存储适配器（STORAGE_BACKEND=local，开发/单机用）。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import BinaryIO

from qqlab.ports.storage import ObjectNotFoundError, ObjectStat


class LocalStorageProvider:
    name = "local"

    def __init__(self, root: str) -> None:
        self._root = Path(root).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        """防目录穿越：解析后必须仍在 root 之下。"""
        target = (self._root / key.lstrip("/")).resolve()
        if not target.is_relative_to(self._root):
            raise ValueError(f"非法的存储 key（越界）: {key}")
        return target

    async def put(self, key: str, data: bytes | BinaryIO, *, content_type: str | None = None) -> None:
        _ = content_type
        target = self._resolve(key)
        payload = data if isinstance(data, bytes) else await asyncio.to_thread(data.read)

        def _write() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)

        await asyncio.to_thread(_write)

    async def get(self, key: str) -> bytes:
        def _read() -> bytes:
            try:
                return self._resolve(key).read_bytes()
            except FileNotFoundError as exc:
                raise ObjectNotFoundError(key) from exc

        return await asyncio.to_thread(_read)

    async def stat(self, key: str) -> ObjectStat:
        def _stat() -> ObjectStat:
            path = self._resolve(key)
            try:
                info = path.stat()
            except FileNotFoundError as exc:
                raise ObjectNotFoundError(key) from exc
            return ObjectStat(size=info.st_size)

        return await asyncio.to_thread(_stat)

    async def list(self, prefix: str) -> list[str]:
        def _list() -> list[str]:
            base = self._root / prefix.strip("/") if prefix.strip("/") else self._root
            if not base.exists():
                return []
            paths = [p for p in base.rglob("*") if p.is_file()] if base.is_dir() else [base]
            return sorted(str(p.relative_to(self._root)) for p in paths)

        return await asyncio.to_thread(_list)

    async def delete(self, key: str) -> None:
        def _delete() -> None:
            path = self._resolve(key)
            if path.exists():
                path.unlink()

        await asyncio.to_thread(_delete)

    async def presign_get(self, key: str, expires: int = 600) -> str:
        _ = expires
        # 本地存储没有预签名，返回可直接访问的相对路径（由 API 层决定是否暴露）
        return f"local://{key.lstrip('/')}"

    async def ping(self) -> bool:
        return self._root.exists()
