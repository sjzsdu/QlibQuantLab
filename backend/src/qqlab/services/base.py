"""服务层公共件：审计上下文与常用异常重导出。"""

from __future__ import annotations

from dataclasses import dataclass

from qqlab.core.errors import (
    ConfirmationRequiredError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationAppError,
)

__all__ = [
    "AuditContext",
    "ConfirmationRequiredError",
    "ConflictError",
    "ForbiddenError",
    "NotFoundError",
    "UnauthorizedError",
    "ValidationAppError",
]


@dataclass(frozen=True, slots=True)
class AuditContext:
    """从请求上下文透传给审计的环境信息（服务层不 import FastAPI）。"""

    request_id: str | None = None
    ip: str | None = None
    user_agent: str | None = None

    @classmethod
    def empty(cls) -> AuditContext:
        return cls()
