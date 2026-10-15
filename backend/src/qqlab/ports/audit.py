"""审计端口：记录敏感操作，落库或转发到外部审计系统。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from qqlab.ports.auth import CurrentUser


class AuditAction:
    """审计动作枚举。集中定义，避免各处拼错字符串。"""

    AUTH_LOGIN = "auth.login"
    AUTH_LOGOUT = "auth.logout"
    AUTH_LOGIN_FAILED = "auth.login_failed"
    AUTH_TOKEN_INVALID = "auth.token_invalid"

    PROJECT_CREATE = "project.create"
    PROJECT_UPDATE = "project.update"
    PROJECT_DELETE = "project.delete"
    PROJECT_MEMBER_ADD = "project.member.add"
    PROJECT_MEMBER_REMOVE = "project.member.remove"
    PROJECT_VISIBILITY_CHANGE = "project.visibility.change"

    DATA_SOURCE_CREATE = "data_source.create"
    DATA_LICENSE_CREATE = "data_license.create"
    DATA_LICENSE_REVOKE = "data_license.revoke"
    DATASET_IMPORT = "dataset.import"

    FACTOR_CREATE = "factor.create"
    FACTOR_UPDATE = "factor.update"
    FACTOR_PUBLISH = "factor.publish"

    MODEL_CREATE = "model.create"
    MODEL_UPDATE = "model.update"
    TRAIN_SUBMIT = "train.submit"

    STRATEGY_CREATE = "strategy.create"
    STRATEGY_UPDATE = "strategy.update"
    STRATEGY_PUBLISH = "strategy.publish"

    BACKTEST_SUBMIT = "backtest.submit"
    BACKTEST_EXPORT = "backtest.export"

    JOB_CANCEL = "job.cancel"
    JOB_RETRY = "job.retry"

    ADMIN_CONFIG_UPDATE = "admin.config.update"
    ADMIN_MEMBER_ROLE_CHANGE = "admin.member.role_change"

    EXPORT_REQUEST = "export.request"


@runtime_checkable
class AuditWriter(Protocol):
    async def record(
        self,
        *,
        action: str,
        resource_type: str,
        resource_id: str | None,
        outcome: str = "success",
        detail: dict | None = None,
        user: CurrentUser | None = None,
        request_id: str | None = None,
        ip: str | None = None,
        org_id: str | None = None,
    ) -> None:
        """写一条审计记录。**不得**因审计失败影响主流程。"""
        ...
