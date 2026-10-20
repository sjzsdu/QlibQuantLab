#!/usr/bin/env python
"""Qlib-Server 连通性 smoke（阶段 3 验收 A3-3）。

在 **worker 容器** 内运行（该镜像有 python-socketio 4.6.1/EIO3 与可选 pyqlib）：
  docker compose --profile qlib run --rm worker python /scripts/qlib_connectivity_smoke.py

三级探测，逐级深入，任一失败给出可读结论（不抛裸栈）：
  L1  socketio EIO3 握手（client → QLIB_SERVER_WS_URL，经 Traefik 入口；唯一经 server 的检查）
  L2  qlib.init + D.instruments("all")（读本地共享卷 LocalProvider——非 server 路径，见 stage1/06 §8.6）
  L3  D.features 抽样（同上，本地读取真实特征数据）

退出码：0 = 全通过；1 = 任一级失败。输出为结构化 JSON（便于脚本断言）。
"""

from __future__ import annotations

import json
import sys
import traceback


def _settings():
    from qqlab.config import Settings

    return Settings()  # 全部从环境变量读取（compose 注入）


def level1_ws_handshake(settings) -> dict:
    """L1：socketio 握手可达。"""
    from qqlab.worker.qlib_env import probe_qlib_server

    ok, detail = probe_qlib_server(settings, timeout=10.0)
    return {"level": "L1_ws_handshake", "ok": ok, "detail": detail}


def level2_instruments(settings) -> dict:
    """L2：列标的（本地共享卷 LocalProvider 读取；验证数据卷与租户路径）。"""
    from qqlab.worker.qlib_env import data_dir_for, qlib_online

    try:
        with qlib_online(settings, org_id=settings.MOCK_ORG_ID):
            from qlib.data import D

            instruments = D.list_instruments(instruments=D.instruments("all"), as_list=True)
        limit = settings.QLIB_DATA_SYMBOLS
        return {
            "level": "L2_instruments",
            "ok": bool(instruments),
            "instrument_count": len(instruments),
            "truncated_to": limit if limit > 0 else None,
            "detail": data_dir_for(settings, settings.MOCK_ORG_ID),
        }
    except ImportError:
        return {
            "level": "L2_instruments",
            "ok": False,
            "detail": "worker 未安装 pyqlib（应使用 worker 镜像 dev-worker/worker-runtime 运行本脚本）",
        }


def level3_features(settings) -> dict:
    """L3：抽样取真实特征（前 8 个标的的 $close）。"""
    from qqlab.worker.qlib_env import qlib_online

    try:
        with qlib_online(settings, org_id=settings.MOCK_ORG_ID):
            from qlib.data import D

            instruments = D.list_instruments(instruments=D.instruments("all"), as_list=True)
            limit = settings.QLIB_DATA_SYMBOLS
            if limit > 0:
                instruments = instruments[:limit]
            sample = instruments[:8]
            df = D.features(sample, ["$close"], start_time=None, end_time=None)
        ok = df is not None and not df.empty
        return {
            "level": "L3_features",
            "ok": ok,
            "rows": int(len(df)) if df is not None else 0,
            "sample_instruments": sample,
            "detail": "$close 特征抽样" if ok else "D.features 返回空（数据未导入或 provider_uri 不一致）",
        }
    except Exception as exc:  # noqa: BLE001 - smoke 脚本要结论不要栈
        return {"level": "L3_features", "ok": False, "detail": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    try:
        settings = _settings()
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"配置加载失败: {exc}"}, ensure_ascii=False))
        return 1

    results = [level1_ws_handshake(settings)]
    # L2/L3 只有 L1 通过才有意义
    if results[0]["ok"]:
        results.append(level2_instruments(settings))
        if results[-1]["ok"]:
            results.append(level3_features(settings))

    ok = all(r["ok"] for r in results)
    print(json.dumps({"ok": ok, "ws_url": settings.QLIB_SERVER_WS_URL, "levels": results}, ensure_ascii=False, indent=2))
    if not ok:
        failed = next(r for r in results if not r["ok"])
        print(f"\n[smoke] ✗ 失败于 {failed['level']}: {failed['detail']}", file=sys.stderr)
        if failed["level"] == "L1_ws_handshake":
            print("  排查：qlib-server 是否启动（--profile qlib）、rabbitmq-init 是否完成、端口 9710", file=sys.stderr)
        elif failed["level"] == "L2_instruments":
            print("  排查：make qlib-data 是否已导入、QLIB_DATA 指向 {org}/cn_data", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - smoke 脚本兜底
        traceback.print_exc()
        sys.exit(1)
