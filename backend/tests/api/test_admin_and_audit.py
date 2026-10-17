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


# ------------------------------------------------------------------ 审计导出（阶段 6）
def test_audit_export_needs_confirmation(client: TestClient) -> None:
    login(client, "admin")
    refused = client.get("/api/v1/audit-logs/export")
    assert refused.status_code == 400
    assert refused.json()["code"] == 1007


def test_audit_export_streams_csv_and_records(client: TestClient) -> None:
    import csv as _csv
    import io as _io

    login(client, "admin")
    resp = client.get("/api/v1/audit-logs/export?format=csv&confirm=true")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment;" in resp.headers["content-disposition"]

    rows = list(_csv.reader(_io.StringIO(resp.text)))
    assert rows[0] == [
        "created_at",
        "action",
        "resource_type",
        "resource_id",
        "outcome",
        "actor_username",
        "ip",
        "user_agent",
        "request_id",
        "detail",
    ]
    assert len(rows) >= 2
    assert all(len(r) == 10 for r in rows)
    actions_in_csv = {r[1] for r in rows[1:]}
    assert "auth.login" in actions_in_csv

    # 导出动作本身也留痕
    body = client.get("/api/v1/audit-logs", params={"action": "audit.export"}).json()["data"]
    assert body["total"] >= 1
    assert body["items"][0]["detail"]["format"] == "csv"


def test_audit_export_rejects_unknown_format(client: TestClient) -> None:
    login(client, "admin")
    resp = client.get("/api/v1/audit-logs/export?format=xlsx&confirm=true")
    assert resp.status_code == 422


def test_audit_export_denied_for_researcher(client: TestClient) -> None:
    login(client, "researcher")
    assert client.get("/api/v1/audit-logs/export?confirm=true").status_code == 403


def test_audit_export_viewer_denied(client: TestClient) -> None:
    login(client, "viewer")
    assert client.get("/api/v1/audit-logs/export?confirm=true").status_code == 403


def test_audit_export_auditor_allowed(client: TestClient) -> None:
    login(client, "auditor")
    resp = client.get("/api/v1/audit-logs/export?confirm=true")
    assert resp.status_code == 200
    assert resp.text.splitlines()[0].startswith("created_at,")


def test_audit_export_is_tenant_scoped(client: TestClient, other_org_client: TestClient) -> None:
    login(client, "admin")
    marker = f"exptenant-{uuid.uuid4().hex[:8]}"
    client.post(
        "/api/v1/projects",
        json={"name": marker},
        headers=csrf_headers(client),
    )
    login(other_org_client, "admin")
    resp = other_org_client.get("/api/v1/audit-logs/export?confirm=true")
    assert resp.status_code == 200
    assert marker not in resp.text
    assert "project.create" not in resp.text
