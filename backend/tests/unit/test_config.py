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
            CASDOOR_ISSUER="https://idp.example.com",
            CASDOOR_CLIENT_ID="cid",
            CASDOOR_CLIENT_SECRET="csecret",
            CASDOOR_REDIRECT_URI="https://app.example.com/api/v1/auth/callback",
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
            CASDOOR_ISSUER="https://idp.example.com",
            CASDOOR_CLIENT_ID="cid",
            CASDOOR_CLIENT_SECRET="csecret",
            CASDOOR_REDIRECT_URI="https://app.example.com/api/v1/auth/callback",
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


def _casdoor_full(**overrides) -> dict:
    payload = dict(
        AUTH_PROVIDER="casdoor",
        CASDOOR_ISSUER="https://idp.example.com",
        CASDOOR_CLIENT_ID="cid",
        CASDOOR_CLIENT_SECRET="csecret",
        CASDOOR_REDIRECT_URI="https://app.example.com/api/v1/auth/callback",
    )
    payload.update(overrides)
    return payload


def test_casdoor_requires_oidc_config_any_env() -> None:
    """切到 casdoor 就必须给全 OIDC 四要素 —— 启动即失败，绝不带空 issuer 起服务。"""
    with pytest.raises(ValidationError) as exc:
        make_settings(AUTH_PROVIDER="casdoor")
    assert "CASDOOR_ISSUER" in str(exc.value)


def test_casdoor_missing_secret_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        make_settings(**_casdoor_full(CASDOOR_CLIENT_SECRET=""))
    assert "CASDOOR_CLIENT_SECRET" in str(exc.value)


def test_casdoor_container_builds() -> None:
    container = Container.build(make_settings(**_casdoor_full()))
    assert container.auth.name == "casdoor"
    assert getattr(container.auth, "IMPLEMENTED", False) is True


def test_unimplemented_provider_fails_fast(monkeypatch) -> None:  # noqa: ANN001
    """IMPLEMENTED=False 的实现 → 启动即报错，绝不静默降级成 mock（守卫逻辑保留）。"""
    from qqlab.adapters.auth.casdoor_provider import CasdoorAuthProvider

    monkeypatch.setattr(CasdoorAuthProvider, "IMPLEMENTED", False)
    with pytest.raises(ConfigError) as exc:
        Container.build(make_settings(**_casdoor_full()))
    assert "AUTH_PROVIDER=casdoor" in str(exc.value)


def test_casdoor_org_map_json_validated() -> None:
    with pytest.raises(ValidationError):
        make_settings(**_casdoor_full(CASDOOR_ORG_MAP="{not json"))
    with pytest.raises(ValidationError):
        make_settings(**_casdoor_full(CASDOOR_ORG_MAP='["a"]'))
    with pytest.raises(ValidationError):
        make_settings(**_casdoor_full(CASDOOR_ROLE_MAP='{"r": 1}'))
    ok = make_settings(**_casdoor_full(CASDOOR_ORG_MAP='{"qqlab": "org-1"}'))
    assert ok.casdoor_org_map == {"qqlab": "org-1"}
    assert ok.casdoor_role_map == {}


def test_casdoor_org_id_claim_defaults_to_owner() -> None:
    """Casdoor JWT 内嵌 user struct 的 owner 字段即组织名 —— 零 Casdoor 侧配置（D7-2）。"""
    assert make_settings(**_casdoor_full()).CASDOOR_ORG_ID_CLAIM == "owner"


def test_casdoor_issuers_whitelist() -> None:
    """iss 白名单含浏览器侧 issuer 与服务端侧地址（Casdoor iss 按 Host 派生，casdoor#1622）。"""
    s = make_settings(**_casdoor_full())
    assert s.casdoor_issuers == ("https://idp.example.com",)
    s2 = make_settings(**_casdoor_full(CASDOOR_INTERNAL_URL="http://casdoor:8000/"))
    assert s2.casdoor_issuers == ("https://idp.example.com", "http://casdoor:8000")


def test_mock_container_builds() -> None:
    container = Container.build(make_settings(AUTH_PROVIDER="mock"))
    assert container.auth.name == "mock"
    assert container.cache.name == "memory"
    assert container.queue.name == "memory"
    assert container.storage.name == "local"
