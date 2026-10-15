"""管理端（成员 / 配置）与审计日志。"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from conftest import csrf_headers, login


def test_member_list_contains_self(client: TestClient) -> None:
    login(client, "admin")
    body = client.get("/api/v1/admin/members").json()["data"]
    usernames = {item["username"] for item in body["items"]}
    assert "dev" in usernames
    assert body["total"] >= 1


def test_researcher_cannot_manage_members(client: TestClient) -> None:
    login(client, "researcher")
    assert client.get("/api/v1/admin/members").status_code == 403


def test_add_and_update_member(client: TestClient) -> None:
    login(client, "admin")
    username = f"u{uuid.uuid4().hex[:8]}"
    added = client.post(
        "/api/v1/admin/members",
        json={"username": username, "roles": ["viewer"], "email": f"{username}@t.local"},
        headers=csrf_headers(client),
    )
    assert added.status_code == 200, added.text
    member = added.json()["data"]
    assert member["roles"] == ["viewer"]
    assert member["username"] == username

    updated = client.put(
        f"/api/v1/admin/members/{member['user_id']}/roles",
        json={"roles": ["researcher"]},
        headers=csrf_headers(client),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["roles"] == ["researcher"]


def test_unknown_role_rejected(client: TestClient) -> None:
    login(client, "admin")
    response = client.post(
        "/api/v1/admin/members",
        json={"username": "whatever", "roles": ["superadmin"]},
        headers=csrf_headers(client),
    )
    assert response.status_code == 400
    assert response.json()["code"] == 1005


def test_duplicate_member_rejected(client: TestClient) -> None:
    login(client, "admin")
    username = f"u{uuid.uuid4().hex[:8]}"
    payload = {"username": username, "roles": ["viewer"]}
    assert client.post("/api/v1/admin/members", json=payload, headers=csrf_headers(client)).status_code == 200
    second = client.post("/api/v1/admin/members", json=payload, headers=csrf_headers(client))
    assert second.status_code == 409


def test_remove_member_needs_confirmation(client: TestClient) -> None:
    login(client, "admin")
    username = f"u{uuid.uuid4().hex[:8]}"
    member = client.post(
        "/api/v1/admin/members",
        json={"username": username, "roles": ["viewer"]},
        headers=csrf_headers(client),
    ).json()["data"]

    refused = client.delete(f"/api/v1/admin/members/{member['user_id']}", headers=csrf_headers(client))
    assert refused.status_code == 400
    assert refused.json()["code"] == 1007

    confirmed = client.delete(
        f"/api/v1/admin/members/{member['user_id']}?confirm=true",
        headers=csrf_headers(client),
    )
    assert confirmed.status_code == 200, confirmed.text


def test_config_write_and_read(client: TestClient) -> None:
    login(client, "admin")
    key = f"test.{uuid.uuid4().hex[:8]}"
    written = client.put(
        f"/api/v1/admin/config/{key}",
        json={"value": {"foo": "bar"}, "is_secret": False},
        headers=csrf_headers(client),
    )
    assert written.status_code == 200, written.text
    assert written.json()["data"]["value"] == {"foo": "bar"}

    listed = client.get("/api/v1/admin/config").json()["data"]
    assert key in {row["config_key"] for row in listed}


def test_secret_config_is_redacted(client: TestClient) -> None:
    login(client, "admin")
    key = f"secret.{uuid.uuid4().hex[:8]}"
    client.put(
        f"/api/v1/admin/config/{key}",
        json={"value": {"token": "super-secret"}, "is_secret": True},
        headers=csrf_headers(client),
    )
    listed = client.get("/api/v1/admin/config").json()["data"]
    row = next(r for r in listed if r["config_key"] == key)
    assert row["is_secret"] is True
    assert row["value"] == {}


def test_audit_log_records_project_create(client: TestClient) -> None:
    login(client, "admin")
    client.post(
        "/api/v1/projects",
        json={"name": f"audited-{uuid.uuid4().hex[:8]}"},
        headers=csrf_headers(client),
    )
    body = client.get("/api/v1/audit-logs", params={"action": "project.create"}).json()["data"]
    assert body["total"] >= 1
    assert body["items"][0]["action"] == "project.create"
    assert body["items"][0]["actor_username"] == "dev"
    assert body["items"][0]["outcome"] == "success"
    assert body["items"][0]["request_id"]


def test_audit_login_recorded(client: TestClient) -> None:
    login(client, "auditor")
    body = client.get("/api/v1/audit-logs", params={"action": "auth.login"}).json()["data"]
    assert body["total"] >= 1


def test_researcher_cannot_read_audit(client: TestClient) -> None:
    login(client, "researcher")
    assert client.get("/api/v1/audit-logs").status_code == 403


def test_auditor_can_read_audit(client: TestClient) -> None:
    login(client, "auditor")
    assert client.get("/api/v1/audit-logs").status_code == 200


def test_audit_is_tenant_scoped(client: TestClient, other_org_client: TestClient) -> None:
    login(client, "admin")
    client.post(
        "/api/v1/projects",
        json={"name": f"org-a-{uuid.uuid4().hex[:8]}"},
        headers=csrf_headers(client),
    )
    login(other_org_client, "admin")
    body = other_org_client.get("/api/v1/audit-logs", params={"action": "project.create"}).json()
    assert body["data"]["total"] == 0
    actions = other_org_client.get("/api/v1/audit-logs/actions").json()["data"]
    assert "project.create" not in actions
