"""Qlib 在线模式环境配置（**只有 worker 会 import 本模块**）。

铁律：API 进程不 import qlib。本模块对 ``qlib`` 的导入是**函数内延迟导入**，
因此即使没装 qlib，API 侧 import ``qqlab.worker.qlib_env`` 也不会报错。

配置项来源：qlib 官方 client.rst 的 ``qlib.init`` 参数与在线模式
``init_by_cfg``（flask_server / flask_port / auto_mount），阶段 3 实测后定稿。
"""

from __future__ import annotations

from typing import Any

from qqlab.config import Settings

QLIB_ONLINE_IMPLEMENTED = False
_IMPLEMENT_MSG = (
    "Qlib 在线模式接入在阶段 3 交付：worker 镜像需安装 qlib[extra] 依赖，"
    "并用 build_qlib_config() 生成 qlib.init 参数。"
)


def build_qlib_config(settings: Settings) -> dict[str, Any]:
    """生成 Qlib 初始化参数（纯函数，阶段 2 可单测）。

    - provider_uri 指向**容器内本地**数据目录（官方 NFS 挂载在开发环境不可用，
      见 docs/stage1/06-qlib-integration.md 的风险 R3/R8）；
    - 在线模式由 qlib client 连接 Qlib-Server（flask_server/flask_port）。
    """
    host, port = settings.qlib_ws_host_port
    return {
        "provider_uri": settings.QLIB_DATA_ROOT,
        "region": settings.QLIB_REGION,
        "experiment_uri": settings.QLIB_EXPERIMENT_ROOT,
        "online": {
            "flask_server": host,
            "flask_port": port,
            "auto_mount": False,
            "timeout": settings.QLIB_INIT_TIMEOUT_SECONDS,
        },
        "redis": {
            "host": settings.QLIB_SERVER_REDIS_HOST,
            "port": settings.QLIB_SERVER_REDIS_PORT,
            "db": settings.QLIB_SERVER_REDIS_DB,
        },
        "queue": {
            "host": settings.QLIB_SERVER_QUEUE_HOST,
            "port": settings.QLIB_SERVER_QUEUE_PORT,
            "user": settings.QLIB_SERVER_QUEUE_USER,
            "password": settings.QLIB_SERVER_QUEUE_PASS,
        },
    }


def qlib_init(settings: Settings) -> None:
    """初始化 qlib（阶段 3 实装；未装 qlib 时给出清晰提示）。"""
    if not QLIB_ONLINE_IMPLEMENTED:
        raise NotImplementedError(_IMPLEMENT_MSG)
    import qlib  # noqa: PLC0415 - 延迟导入，API 进程永不触发

    cfg = build_qlib_config(settings)
    qlib.init(provider_uri=cfg["provider_uri"], region=cfg["region"])
