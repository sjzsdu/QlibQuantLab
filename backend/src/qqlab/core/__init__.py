"""核心层：横切关注点（错误、日志、权限、租户、安全、限流、中间件）。"""

from qqlab.core.errors import (
    AppError,
    ConfigError,
    ConfirmationRequiredError,
    ConflictError,
    DependencyUnavailableError,
    ForbiddenError,
    NotFoundError,
    NotImplementedYetError,
    RateLimitedError,
    UnauthorizedError,
    ValidationAppError,
)
from qqlab.core.tenant import OrgScope

__all__ = [
    "AppError",
    "ConfigError",
    "ConfirmationRequiredError",
    "ConflictError",
    "DependencyUnavailableError",
    "ForbiddenError",
    "NotFoundError",
    "NotImplementedYetError",
    "OrgScope",
    "RateLimitedError",
    "UnauthorizedError",
    "ValidationAppError",
]
