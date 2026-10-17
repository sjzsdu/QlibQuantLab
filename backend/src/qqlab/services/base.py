"""服务层公共件：审计上下文、股票池校验与常用异常重导出。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from qqlab.core.errors import (
    ConfirmationRequiredError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    UnprocessableInputError,
    ValidationAppError,
)
from qqlab.core.qlib_data import DataPathError, read_universe

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from qqlab.config import Settings

__all__ = [
    "AuditContext",
    "ConfirmationRequiredError",
    "ConflictError",
    "ForbiddenError",
    "NotFoundError",
    "UnprocessableInputError",
    "UnauthorizedError",
    "ValidationAppError",
    "ensure_universe",
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


def ensure_universe(
    settings: Settings,
    *,
    org_id: str,
    storage_uri: str | None,
    universe: str,
) -> None:
    """提交期校验股票池（阶段 6 D6，fail-closed）。

    - ``all`` 且数据集未导入（``storage_uri`` 空）→ 放行 —— 内置全市场语义，
      不因导入状态改变默认提交路径；
    - 非 ``all`` 且未导入 → 422：无法校验即拒绝（不盲信请求方）；
    - 已导入 → 强制 ``{QLIB_DATA_ROOT}/{org_id}/`` 前缀（越界 404）后，
      池名必须存在于数据集 ``instruments/*.txt`` → 否则 422（code 1011）
      并在消息里列出可用池。

    ``all`` 在已导入数据集上也走文件校验（缺 ``all.txt`` 说明数据目录不完整，
    早失败优于 worker 任务失败）。
    """
    if universe == "all" and not storage_uri:
        return
    if not storage_uri:
        raise UnprocessableInputError(
            f"数据集尚未导入，无法校验股票池「{universe}」——先执行「导入数据」，或改用默认 all"
        )
    root = (Path(settings.QLIB_DATA_ROOT) / org_id).resolve()
    target = Path(storage_uri).resolve()
    if not target.is_relative_to(root):
        raise NotFoundError("数据目录不属于当前组织")
    try:
        read_universe(target, universe)
    except DataPathError as exc:
        raise UnprocessableInputError(str(exc)) from exc
