"""统一业务异常与错误码。

约定：
- 业务异常一律继承 :class:`AppError`，由 main.py 的异常处理器转成统一响应信封。
- 跨租户访问返回 404（不泄露存在性），权限不足返回 403，未登录 401。
"""

from __future__ import annotations


class AppError(Exception):
    """业务异常基类。"""

    code: int = 1000
    http_status: int = 500

    def __init__(self, message: str, *, detail: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class UnauthorizedError(AppError):
    code = 1001
    http_status = 401


class ForbiddenError(AppError):
    code = 1002
    http_status = 403


class NotFoundError(AppError):
    code = 1003
    http_status = 404


class ConflictError(AppError):
    code = 1004
    http_status = 409


class ValidationAppError(AppError):
    """业务校验失败（与 FastAPI 的 422 请求体校验不同）。"""

    code = 1005
    http_status = 400


class RateLimitedError(AppError):
    code = 1006
    http_status = 429


class ConfirmationRequiredError(ValidationAppError):
    code = 1007
    http_status = 400

    def __init__(self, action: str) -> None:
        super().__init__(f"敏感操作需要二次确认：请传 confirm=true（{action}）")
        self.action = action


class ConfigError(AppError):
    """启动期配置错误（例如 AUTH_PROVIDER 指向未实现的实现）。"""

    code = 1008
    http_status = 500


class DependencyUnavailableError(AppError):
    code = 1009
    http_status = 503


class NotImplementedYetError(AppError):
    """阶段未到的占位能力。"""

    code = 1010
    http_status = 501
