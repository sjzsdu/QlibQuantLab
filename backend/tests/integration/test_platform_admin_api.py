"""平台审计端点 /admin/platform-audit（阶段 8 · D8-4 白名单守卫 / D8-5 双写）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import login, make_settings
from qqlab.main import create_app


def test_mock_default_platform_admin_and_login_event_visible(client: TestClient) -> None:
    """D8-4：mock 白名单留空 = 回落 MOCK 身份即平台管理员；
    D8-5：登录动作（auth.login）已被 PlatformAuditTrail 双写进平台表。"""
    login(client)
    response = client.get("/api/v1/admin/platform-audit")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    actions = [item["action"] for item in data["items"]]
    assert "auth.login" in actions, actions
    assert data["total"] >= 1
    item = next(i for i in data["items"] if i["action"] == "auth.login")
    assert item["actor_username"] == "dev"
    assert item["outcome"] == "success"


def test_action_prefix_filter(client: TestClient) -> None:
    login(client)
    response = client.get("/api/v1/admin/platform-audit", params={"action": "admin."})
    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert all(item["action"].startswith("admin.") for item in items)


def test_pagination_shape(client: TestClient) -> None:
    login(client)
    response = client.get("/api/v1/admin/platform-audit", params={"page": 2, "page_size": 1})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["page"] == 2 and data["page_size"] == 1
    assert len(data["items"]) <= 1


def test_anonymous_is_401(client: TestClient) -> None:
    assert client.get("/api/v1/admin/platform-audit").status_code == 401


def test_org_admin_not_in_whitelist_is_403() -> None:
    """组织内 admin 角色 ≠ 平台管理员：白名单是唯一授权面（D8-4）。"""
    restricted = TestClient(create_app(make_settings(PLATFORM_ADMIN_USERS="someone-else")))
    login(restricted)
    assert restricted.get("/api/v1/admin/platform-audit").status_code == 403


def test_whitelist_matches_username_entry() -> None:
    """白名单条目按 username 匹配（mock 的 MOCK_USER_USERNAME=dev）。"""
    by_username = TestClient(create_app(make_settings(PLATFORM_ADMIN_USERS="dev")))
    login(by_username)
    assert by_username.get("/api/v1/admin/platform-audit").status_code == 200


def test_casdoor_empty_whitelist_is_fail_closed(monkeypatch) -> None:
    """casdoor 下白名单留空 = 无人（fail-closed）——不走 mock 回落。"""
    from conftest import TEST_DB_URL
    from qqlab.api.deps import is_platform_admin
    from qqlab.config import Settings
    from qqlab.ports.auth import CurrentUser, Role

    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        AUTH_PROVIDER="casdoor",
        DATABASE_URL=TEST_DB_URL,
        CACHE_URL="memory://",
        MQ_URL="memory://",
        QLIB_SERVER_WS_URL="ws://qlib-server:9710",
        CORS_ALLOW_ORIGINS="http://localhost:3000",
        APP_JWT_SECRET="test-secret-0123456789abcdef0123456789abcdef",
        CASDOOR_ISSUER="https://casdoor.example.com",
        CASDOOR_CLIENT_ID="cid",
        CASDOOR_CLIENT_SECRET="csecret",
        CASDOOR_REDIRECT_URI="http://localhost:3000/cb",
    )
    user = CurrentUser(
        user_id="u1", username="dev", org_id="o1", roles=(Role.ADMIN,), provider="casdoor"
    )
    assert not is_platform_admin(user, settings)
