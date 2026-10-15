"""认证流程：未登录 401 → 一键进入 → /me → 权限 → CSRF → 登出。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import csrf_headers, login


def test_me_requires_auth(client: TestClient) -> None:
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == 1001
    assert body["message"]


def test_login_start_returns_mock_url(client: TestClient) -> None:
    response = client.get("/api/v1/auth/login", params={"redirect_to": "/projects"})
    assert response.status_code == 200
    url = response.json()["data"]["url"]
    assert url.startswith("/api/v1/auth/mock/enter")
    assert "state=" in url
    assert "redirect_to=/projects" in url


def test_mock_enter_is_redirect_and_sets_cookies(client: TestClient) -> None:
    response = client.get(
        "/api/v1/auth/mock/enter",
        params={"profile": "researcher"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/"
    cookies = response.headers.get("set-cookie", "")
    assert "qqlab_session=" in cookies
    assert "qqlab_csrf=" in cookies


def test_login_then_me(client: TestClient) -> None:
    user = login(client, "admin")
    assert user["user_id"] == "dev-user"
    assert user["org_id"] == "dev-org"
    assert "admin" in user["roles"]
    assert user["is_authenticated"] is True
    assert user["provider"] == "mock"

    me = client.get("/api/v1/me").json()["data"]
    assert me["username"] == "dev"
    assert me["org_id"] == "dev-org"


def test_profile_switch_changes_identity(client: TestClient) -> None:
    viewer = login(client, "viewer")
    assert viewer["user_id"] == "dev-user-viewer"
    assert viewer["roles"] == ["viewer"]

    perms = client.get("/api/v1/me/permissions").json()["data"]["permissions"]
    assert "project.read" in perms
    assert "project.write" not in perms
    assert "admin.member" not in perms


def test_permissions_endpoint_for_admin(client: TestClient) -> None:
    login(client, "admin")
    perms = client.get("/api/v1/me/permissions").json()["data"]["permissions"]
    assert "project.delete" in perms
    assert "audit.read" in perms


def test_current_org_endpoint(client: TestClient) -> None:
    login(client, "admin")
    org = client.get("/api/v1/orgs/current").json()["data"]
    assert org["id"] == "dev-org"
    assert org["slug"] == "dev"
    assert org["name"] == "Dev Organization"


def test_write_without_csrf_rejected(client: TestClient) -> None:
    login(client, "admin")
    response = client.post("/api/v1/projects", json={"name": "no-csrf"})
    assert response.status_code == 403
    assert response.json()["code"] != 0


def test_write_with_csrf_accepted(client: TestClient) -> None:
    login(client, "admin")
    response = client.post(
        "/api/v1/projects",
        json={"name": "with-csrf"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    assert response.json()["code"] == 0


def test_logout_clears_session(client: TestClient) -> None:
    login(client, "admin")
    response = client.get("/api/v1/auth/logout")
    assert response.status_code == 200
    assert response.json()["data"]["redirect_to"].startswith("/login")
    assert "qqlab_session=" in response.headers.get("set-cookie", "")
    assert client.cookies.get("qqlab_session") is None
    assert client.get("/api/v1/me").status_code == 401


@pytest.mark.parametrize("profile", ["admin", "researcher", "viewer", "auditor"])
def test_every_profile_can_read_me(client: TestClient, profile: str) -> None:
    login(client, profile)
    assert client.get("/api/v1/me").status_code == 200


def test_open_redirect_is_neutralized(client: TestClient) -> None:
    response = client.get(
        "/api/v1/auth/login",
        params={"redirect_to": "https://evil.example/x"},
    )
    url = response.json()["data"]["url"]
    assert "evil.example" not in url
    assert "redirect_to=/" in url
