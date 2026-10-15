"""Qlib 在线模式环境（**全仓唯一**允许 `import qlib` 的文件之一）。

铁律：API 进程不 import qlib。本模块对 ``qlib`` 的导入全部是**函数内延迟导入**，
即使 worker 镜像装了 qlib，API 侧 import 本模块也不会加载 qlib。

设计依据：docs/stage1/06-qlib-integration.md §3（不走 NFS：共享卷 + 本地
provider_uri + auto_mount=False）；实测结论见 docs/stage1/06 §8。
"""

from __future__ import annotations

import contextlib
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from collections.abc import Iterator

    from qqlab.config import Settings

#: qlib 是**进程级单例**（C 配置与缓存全局共享）→ 初始化必须串行（R6）。
#: `QLIB_WORKER_CONCURRENCY=1` 是第一道防线，这里是第二道。
_init_lock = threading.Lock()


def data_dir_for(settings: Settings, org_id: str) -> str:
    """某 org 的 qlib 数据目录（worker 与 qlib-server 必须一致，compose 里 QLIB_DATA 同源）。"""
    return f"{settings.QLIB_DATA_ROOT}/{org_id}/{settings.QLIB_DATA_SUBDIR}"


def build_qlib_config(settings: Settings, org_id: str) -> dict[str, Any]:
    """生成**扁平**的 ``qlib.init`` 参数（纯函数，可单测，不 import qlib）。

    - provider_uri/mount_path 指向容器内本地共享卷（官方在线模式的 NFS 挂载
      在 Docker 中不可用，见风险 R4）；
    - auto_mount=False：本地路径 → qlib 直接判 LOCAL_URI，跳过 mount；
    - flask_server/flask_port 从 ``QLIB_SERVER_WS_URL`` 解析（所有外部地址来自环境变量）。
    """
    host, port = settings.qlib_ws_host_port
    data_root = data_dir_for(settings, org_id)
    return {
        "provider_uri": data_root,
        "mount_path": data_root,
        "region": settings.QLIB_REGION,
        "experiment_uri": f"{settings.QLIB_EXPERIMENT_ROOT}/{org_id}",
        "auto_mount": False,
        "flask_server": host,
        "flask_port": port,
        "redis_host": settings.QLIB_SERVER_REDIS_HOST or "redis",
        "redis_port": settings.QLIB_SERVER_REDIS_PORT,
        "redis_task_db": settings.QLIB_SERVER_REDIS_DB,
    }


def _clear_caches() -> None:
    """尽力释放 qlib 进程级缓存（任何失败都不影响任务结果）。"""
    try:  # noqa: SIM105 - 清理逻辑必须吞掉一切异常
        from qlib.data.cache import H  # noqa: PLC0415

        H.clear()
    except Exception:  # noqa: BLE001
        pass


@contextlib.contextmanager
def qlib_online(settings: Settings, *, org_id: str) -> Iterator[dict[str, Any]]:
    """按 org 切换 qlib 配置的上下文管理器（进程级互斥）。

    每次进入都会重新 ``qlib.init``（官方入口会重置全局 C），
    退出时尽力清理缓存。同一 worker 进程内**不允许嵌套并发**使用。
    """
    import qlib  # noqa: PLC0415 - 全仓唯一 import 点

    cfg = build_qlib_config(settings, org_id)
    with _init_lock:
        qlib.init(**cfg)
        try:
            yield cfg
        finally:
            _clear_caches()


def probe_qlib_server(settings: Settings, *, timeout: float = 5.0) -> tuple[bool, str]:
    """探测 Qlib-Server WS 连通性（socketio 客户端直连，与冒烟脚本同协议）。

    只验证握手可达，不验证数据（数据由 dataset_import 任务校验）。

    注意 python-socketio 4.6.1（EIO3 客户端）的同步 ``Client.connect`` **没有**
    ``wait_timeout`` 形参（5.x 才有）—— 直接传会 ``TypeError``。这里用后台线程
    + ``join(timeout)`` 自行实现有界超时，避免服务器半开时探测无限挂起。
    """
    import threading  # noqa: PLC0415

    import socketio  # noqa: PLC0415 - worker 镜像专属依赖（EIO3 代际）

    host, port = settings.qlib_ws_host_port
    url = f"ws://{host}:{port}"
    client = socketio.Client(reconnection=False)
    outcome: dict[str, str] = {}

    def _probe() -> None:
        try:
            client.connect(url)
        except Exception as exc:  # noqa: BLE001 - 探测失败必须给原因而非抛异常
            outcome["error"] = str(exc)
        else:
            outcome["ok"] = url
        finally:
            with contextlib.suppress(Exception):  # 断开失败不影响探测结论
                client.disconnect()

    worker = threading.Thread(target=_probe, daemon=True, name="qlib-probe")
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        return False, f"{url}: 握手超时（>{timeout}s，服务器可能半开）"
    if "ok" in outcome:
        return True, outcome["ok"]
    return False, f"{url}: {outcome.get('error', '未知错误')}"


def probe_dataset_via_qlib(settings: Settings, org_id: str) -> dict[str, Any]:
    """用 qlib 校验数据可用性并返回快照（instrument_count / start / end）。

    ``ImportError`` 原样上抛（stub 环境由调用方降级为文件系统解析）；
    数据缺失/为空抛 ``RuntimeError``（属于**真实失败**，不应降级掩盖）。
    """
    with qlib_online(settings, org_id=org_id):
        from qlib.data import D  # noqa: PLC0415

        data_root = data_dir_for(settings, org_id)
        instruments = D.list_instruments(instruments=D.instruments("all"), as_list=True)
        if not instruments:
            raise RuntimeError(f"qlib instruments 为空（{data_root}）")
        df = D.features(instruments[:8], ["$close"], start_time=None, end_time=None)
        dates = sorted({str(index[1])[:10] for index in df.index}) if df is not None and not df.empty else []
        if not dates:
            raise RuntimeError(f"qlib features 为空（{data_root}）")
        return {
            "instrument_count": len(instruments),
            "start": dates[0],
            "end": dates[-1],
            "via": "qlib",
        }
