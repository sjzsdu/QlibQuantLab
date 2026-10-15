"""架构约束测试：业务代码只能依赖 Ports，不得依赖具体 SDK / adapters。"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "qqlab"

#: 只允许出现在 adapters / worker.qlib_env 的第三方 SDK（端口铁律）
FORBIDDEN_SDKS = frozenset(
    {
        "redis",
        "aio_pika",
        "pika",
        "boto3",
        "botocore",
        "qlib",
        "socketio",
        "engineio",
        "casdoor",
        "minio",
        "aioboto3",
    }
)

#: 不得 import adapters 的业务包（唯一例外是 container.py）
BUSINESS_PKGS = ("api", "services", "repositories", "models", "core", "schemas")

#: ports 包必须零第三方依赖
PORTS_PKG = "ports"

#: 显式豁免（装配点 / 入口）
EXEMPT_FILES = frozenset({"container.py", "main.py"})


def _py_files(*rel_parts: str) -> list[Path]:
    root = SRC.joinpath(*rel_parts)
    return sorted(p for p in root.rglob("*.py") if p.is_file()) if root.exists() else []


def _imported_modules(path: Path) -> set[str]:
    """收集**运行期** import；``if TYPE_CHECKING:`` 块内的纯类型导入跳过。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    stack: list[ast.AST] = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.If):
            guard = node.test
            if isinstance(guard, ast.Name) and guard.id == "TYPE_CHECKING":
                stack.extend(node.orelse)  # 只跳过 then 分支
            else:
                stack.extend(node.body)
                stack.extend(node.orelse)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                found.add(node.module)
        else:
            stack.extend(ast.iter_child_nodes(node))
    return found


def _rel(path: Path) -> str:
    return str(path.relative_to(SRC))


@pytest.mark.parametrize(
    "pkg",
    BUSINESS_PKGS,
    ids=BUSINESS_PKGS,
)
def test_business_does_not_import_adapters(pkg: str) -> None:
    """业务代码只依赖端口：不得出现 ``qqlab.adapters``。"""
    offenders = []
    for path in _py_files(pkg):
        if _rel(path) in EXEMPT_FILES:
            continue
        for module in _imported_modules(path):
            if module == "qqlab.adapters" or module.startswith("qqlab.adapters."):
                offenders.append(f"{_rel(path)} -> {module}")
    assert not offenders, "业务代码禁止依赖 adapters，应改用 ports:\n" + "\n".join(offenders)


@pytest.mark.parametrize(
    "pkg",
    BUSINESS_PKGS,
    ids=BUSINESS_PKGS,
)
def test_business_does_not_import_sdk(pkg: str) -> None:
    """第三方基础设施 SDK 只能出现在 adapters（与 worker.qlib_env）。"""
    offenders = []
    for path in _py_files(pkg):
        for module in _imported_modules(path):
            root = module.split(".")[0]
            if root in FORBIDDEN_SDKS:
                offenders.append(f"{_rel(path)} -> {module}")
    assert not offenders, "业务代码禁止直接 import 基础设施 SDK:\n" + "\n".join(offenders)


def test_ports_are_dependency_free() -> None:
    """端口层只依赖标准库与自身：保证可被任何实现替换。"""
    stdlib = set(sys.stdlib_module_names)
    offenders = []
    for path in _py_files(PORTS_PKG):
        for module in _imported_modules(path):
            root = module.split(".")[0]
            if root in stdlib or root == "qqlab":
                continue
            offenders.append(f"{_rel(path)} -> {module}")
    assert not offenders, "ports 只允许 import 标准库与 qqlab.ports:*\n" + "\n".join(offenders)


def test_forbidden_sdks_only_in_adapters() -> None:
    """全仓扫描：这些 SDK 只允许在 adapters 里出现（worker.qlib_env 走延迟导入）。"""
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        rel = _rel(path)
        if rel.startswith("adapters/") or rel in {"container.py", "worker/qlib_env.py"}:
            continue
        for module in _imported_modules(path):
            root = module.split(".")[0]
            if root in FORBIDDEN_SDKS:
                offenders.append(f"{rel} -> {module}")
    assert not offenders, "发现越界的 SDK 依赖:\n" + "\n".join(offenders)


def test_api_does_not_import_qlib() -> None:
    """硬约束：Qlib 不进 Web 进程。"""
    offenders = []
    for path in _py_files("api"):
        for module in _imported_modules(path):
            if module.split(".")[0] == "qlib":
                offenders.append(f"{_rel(path)} -> {module}")
    assert not offenders, "API 进程禁止 import qlib:\n" + "\n".join(offenders)
