"""外部地址必须来自环境变量：源码里不允许出现具体主机名 / IP。"""

from __future__ import annotations

import re
from pathlib import Path

SRC_PKG = Path(__file__).resolve().parents[2] / "src" / "qqlab"

#: 允许 0.0.0.0（监听全部网卡的绑定地址，不是「去连接谁」）
_IP = re.compile(r"\b(?<![\w.])((?:\d{1,3}\.){3}\d{1,3})(?![\w.])")
_HOST_WORDS = ("localhost", "127.0.0.1")


def _py_files() -> list[Path]:
    return sorted(p for p in SRC_PKG.rglob("*.py") if p.is_file())


def test_no_hardcoded_host_or_ip() -> None:
    """任何模块都不得写死主机名/IP：地址一律来自 Settings（环境变量）。"""
    offenders: list[str] = []
    for path in _py_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            lowered = line.lower()
            if any(word in lowered for word in _HOST_WORDS):
                offenders.append(f"{path.relative_to(SRC_PKG)}:{lineno} -> {line.strip()}")
                continue
            for ip in _IP.findall(line):
                if ip == "0.0.0.0":
                    continue  # 绑定地址
                offenders.append(f"{path.relative_to(SRC_PKG)}:{lineno} -> {line.strip()}")
                break
    assert not offenders, "外部地址必须来自环境变量，禁止硬编码：\n" + "\n".join(offenders)


def test_only_config_reads_environment() -> None:
    """业务代码不得直接读 os.environ，只能通过 Settings。"""
    allowed = {SRC_PKG / "config.py"}
    offenders: list[str] = []
    for path in _py_files():
        if path in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        if "os.environ" in text or "os.getenv" in text:
            offenders.append(str(path.relative_to(SRC_PKG)))
    assert not offenders, "只有 config.py 允许读环境变量，其他模块请走 Settings：\n" + "\n".join(offenders)


def test_settings_required_fields_have_no_defaults() -> None:
    """六个连接串类字段必须是必填：没配置就在启动时失败，而不是静默连到错误地址。"""
    from qqlab.config import Settings

    required = {name for name, field in Settings.model_fields.items() if field.is_required()}
    assert required == {
        "DATABASE_URL",
        "CACHE_URL",
        "MQ_URL",
        "APP_JWT_SECRET",
        "CORS_ALLOW_ORIGINS",
        "QLIB_SERVER_WS_URL",
    }
