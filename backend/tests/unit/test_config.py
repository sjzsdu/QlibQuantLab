"""配置校验：生产环境拒绝 mock 认证、依赖地址必须注入。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from conftest import make_settings
from qqlab.container import Container
from qqlab.core.errors import ConfigError


def test_production_rejects_mock_auth() -> None:
    with pytest.raises(ValidationError) as exc:
        make_settings(APP_ENV="production", AUTH_PROVIDER="mock")
    assert "mock" in str(exc.value)


def test_production_requires_secure_cookie() -> None:
    with pytest.raises(ValidationError):
        make_settings(
            APP_ENV="production",
            AUTH_PROVIDER="casdoor",
            SESSION_COOKIE_SECURE=False,
            QLIB_SERVER_REDIS_HOST="redis",
            QLIB_SERVER_QUEUE_HOST="rabbitmq",
        )


def test_production_requires_qlib_hard_deps() -> None:
    """Qlib-Server 强依赖 Redis/RabbitMQ，生产必须显式配置。"""
    with pytest.raises(ValidationError) as exc:
        make_settings(
            APP_ENV="production",
            AUTH_PROVIDER="casdoor",
            SESSION_COOKIE_SECURE=True,
            QLIB_SERVER_REDIS_HOST="",
            QLIB_SERVER_QUEUE_HOST="",
        )
    assert "QLIB_SERVER" in str(exc.value)


def test_s3_storage_requires_credentials() -> None:
    with pytest.raises(ValidationError):
        make_settings(STORAGE_BACKEND="s3", STORAGE_S3_ENDPOINT="", STORAGE_S3_ACCESS_KEY="")


def test_empty_urls_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(DATABASE_URL="")
    with pytest.raises(ValidationError):
        make_settings(CACHE_URL="  ")


def test_cors_origins_parsed() -> None:
    settings = make_settings(CORS_ALLOW_ORIGINS="http://a.test, http://b.test")
    assert settings.cors_origins == ["http://a.test", "http://b.test"]


def test_qlib_ws_url_split() -> None:
    settings = make_settings(QLIB_SERVER_WS_URL="ws://qlib-server:9710")
    assert settings.qlib_ws_host_port == ("qlib-server", 9710)
    settings = make_settings(QLIB_SERVER_WS_URL="ws://qlib-server")
    assert settings.qlib_ws_host_port == ("qlib-server", 9710)


def test_casdoor_not_implemented_fails_fast() -> None:
    """AUTH_PROVIDER=casdoor 但骨架未实现 → 启动即报错，绝不静默降级成 mock。"""
    with pytest.raises(ConfigError) as exc:
        Container.build(make_settings(AUTH_PROVIDER="casdoor"))
    assert "阶段 7" in str(exc.value)


def test_mock_container_builds() -> None:
    container = Container.build(make_settings(AUTH_PROVIDER="mock"))
    assert container.auth.name == "mock"
    assert container.cache.name == "memory"
    assert container.queue.name == "memory"
    assert container.storage.name == "local"
