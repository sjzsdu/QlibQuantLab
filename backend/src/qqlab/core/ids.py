"""ID 生成：外部字符串 id（如 mock 的 ``dev-user``）→ 确定性 UUID。

用户、组织、审计三处必须用同一套映射，否则外键对不上。
"""

from __future__ import annotations

import uuid


def stable_uuid(value: str) -> uuid.UUID:
    """把任意稳定字符串映射成固定 UUID。

    - 本身是合法 UUID 的原样返回；
    - 否则用 URL 命名空间做 uuid5（同一输入永远得到同一 UUID）。
    """
    text = str(value).strip()
    try:
        return uuid.UUID(text)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"qqlab:external:{text}")


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()
