"""Alembic 迁移链的端到端验证：全量业务表 + 开发种子数据。

单独跑一个 alembic 子进程（而不是复用测试库），确保 `alembic/env.py` 的 async engine
与 seed 逻辑在真实 CLI 下也能工作。
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]

BUSINESS_TABLES = {
    "projects",
    "project_members",
    "data_sources",
    "data_licenses",
    "datasets",
    "factors",
    "models",
    "training_runs",
    "strategies",
    "backtests",
    "jobs",
    "job_logs",
    "audit_logs",
    "system_configs",
    "org_members",
}
IDENTITY_TABLES = {"organizations", "users"}
#: 全局表（无 org_id，阶段 8 · D8-5）
PLATFORM_TABLES = {"platform_audit_events"}


@pytest.fixture(scope="module")
def migrated_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    db_path = tmp_path_factory.mktemp("alembic") / "migrate.db"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
        "DATABASE_BACKEND": "sqlite",
        "APP_ENV": "test",
    }
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"alembic 失败:\n{result.stdout}\n{result.stderr}"
    assert db_path.exists()
    return db_path


def _tables(db_path: Path) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    finally:
        conn.close()
    return {name for (name,) in rows if not name.startswith("sqlite_")}


def test_migration_creates_all_tables(migrated_db: Path) -> None:
    tables = _tables(migrated_db)
    missing = (BUSINESS_TABLES | IDENTITY_TABLES | PLATFORM_TABLES) - tables
    assert not missing, f"缺少表: {sorted(missing)}"
    assert "alembic_version" in tables


def test_migration_seeds_dev_org_and_user(migrated_db: Path) -> None:
    conn = sqlite3.connect(migrated_db)
    conn.row_factory = sqlite3.Row
    try:
        org = conn.execute("SELECT * FROM organizations WHERE slug = 'dev'").fetchone()
        assert org is not None, "缺少 dev-org 种子"
        user = conn.execute("SELECT * FROM users WHERE username = 'dev'").fetchone()
        assert user is not None, "缺少 dev-user 种子"
        member = conn.execute(
            "SELECT roles FROM org_members WHERE org_id = ? AND user_id = ?",
            (org["id"], user["id"]),
        ).fetchone()
        assert member is not None, "缺少 dev 成员关系种子"
        assert set(json.loads(member["roles"])) == {"admin", "researcher"}

        configs = conn.execute(
            "SELECT config_key FROM system_configs WHERE org_id = ?", (org["id"],)
        ).fetchall()
        keys = {row["config_key"] for row in configs}
        assert keys == {"compliance.notice_shown", "backtest.default_benchmark"}
    finally:
        conn.close()


def test_migration_is_idempotent(tmp_path_factory: pytest.TempPathFactory) -> None:
    """重复执行 upgrade head 不应报错，也不应产生重复种子。"""
    db_path = tmp_path_factory.mktemp("alembic-twice") / "twice.db"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
        "DATABASE_BACKEND": "sqlite",
        "APP_ENV": "test",
    }
    for _ in range(2):
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert result.returncode == 0, f"alembic 失败:\n{result.stdout}\n{result.stderr}"

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM system_configs").fetchone()[0] == 2
    finally:
        conn.close()
