"""测试夹具：内存缓存 + 文件 SQLite + Mock 认证，全部不依赖外部服务。

**必须**在导入 qqlab 之前设置环境变量（qqlab.main 在导入时会读取 Settings）。
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

_TMP = Path(tempfile.mkdtemp(prefix="qqlab-test-"))
_TEST_DB = _TMP / "test.db"

os.environ.update(
    {
        "APP_ENV": "test",
        "LOG_LEVEL": "WARNING",
        "RATE_LIMIT_ENABLED": "false",
        "DATABASE_BACKEND": "sqlite",
        "DATABASE_URL": f"sqlite+aiosqlite:///{_TEST_DB}",
        "CACHE_BACKEND": "memory",
        "CACHE_URL": "memory://",
        "MQ_BACKEND": "memory",
        "MQ_URL": "memory://",
        "STORAGE_BACKEND": "local",
        "STORAGE_LOCAL_ROOT": str(_TMP / "objects"),
        "QLIB_SERVER_WS_URL": "ws://qlib-server:9710",
        "CORS_ALLOW_ORIGINS": "http://localhost:3000",
        "APP_JWT_SECRET": "test-secret-0123456789abcdef0123456789abcdef",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

from qqlab.config import Settings  # noqa: E402
from qqlab.main import create_app  # noqa: E402
from qqlab.models import Base  # noqa: E402

TEST_DB_URL = f"sqlite+aiosqlite:///{_TEST_DB}"


def make_settings(**overrides: Any) -> Settings:
    payload: dict[str, Any] = dict(
        _env_file=None,
        APP_ENV="test",
        LOG_LEVEL="WARNING",
        RATE_LIMIT_ENABLED=False,
        DATABASE_BACKEND="sqlite",
        DATABASE_URL=TEST_DB_URL,
        CACHE_BACKEND="memory",
        CACHE_URL="memory://",
        MQ_BACKEND="memory",
        MQ_URL="memory://",
        STORAGE_BACKEND="local",
        STORAGE_LOCAL_ROOT=str(_TMP / "objects"),
        QLIB_SERVER_WS_URL="ws://qlib-server:9710",
        CORS_ALLOW_ORIGINS="http://localhost:3000",
        APP_JWT_SECRET="test-secret-0123456789abcdef0123456789abcdef",
    )
    payload.update(overrides)
    return Settings(**payload)


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Any:
    engine = create_engine(f"sqlite:///{_TEST_DB}")
    Base.metadata.create_all(engine)
    yield
    engine.dispose()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(scope="session")
def app():  # noqa: ANN201
    """会话级 app：引擎常驻，测试函数复用同一个库（顺序执行）。"""
    return create_app(make_settings())


@pytest.fixture
def client(app) -> TestClient:  # noqa: ANN001
    return TestClient(app)


@pytest.fixture
def other_org_client() -> TestClient:  # noqa: ANN201
    """另一个组织的客户端（同库不同 org → 验证租户隔离）。"""
    other = create_app(
        make_settings(
            MOCK_ORG_ID="other-org",
            MOCK_ORG_SLUG="other",
            MOCK_ORG_NAME="Other Org",
            MOCK_USER_ID="other-user",
            MOCK_USER_USERNAME="other",
            MOCK_USER_EMAIL="other@qlibquantlab.local",
        )
    )
    return TestClient(other)


def login(client: TestClient, profile: str = "admin") -> dict[str, Any]:
    response = client.post(
        "/api/v1/auth/mock/enter",
        json={"profile": profile, "redirect_to": "/"},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("qqlab_csrf")
    return {"X-CSRF-Token": token} if token else {}
