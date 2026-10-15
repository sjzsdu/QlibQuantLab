"""CasdoorAuthProvider —— 阶段 7 实装（骨架）。

容器在启动时会检测 ``IMPLEMENTED``，若为 False 则**直接拒绝启动**并给出清晰提示，
避免「配置写了 casdoor 但实际还在跑 mock」这种静默降级。
"""

from __future__ import annotations

from qqlab.config import Settings
from qqlab.ports.auth import CurrentUser

_NOT_IMPLEMENTED = (
    "CasdoorAuthProvider 尚未实现（阶段 7 交付）。"
    "请在阶段 1-6 使用 AUTH_PROVIDER=mock，或完成 OIDC 授权码流程 + JWKS 校验后将 IMPLEMENTED 置为 True。"
)


class CasdoorAuthProvider:
    name = "casdoor"
    IMPLEMENTED = False

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def get_login_url(self, state: str, redirect_to: str) -> str:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def get_logout_url(self, redirect_to: str) -> str:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def handle_callback(self, code: str, state: str) -> CurrentUser:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def verify_token(self, token: str) -> CurrentUser | None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def healthcheck(self) -> bool:
        return False
