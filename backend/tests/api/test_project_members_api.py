"""项目成员与可见性 API 测试（阶段 4）。"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from conftest import csrf_headers, login


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _create_project(client: TestClient, name: str | None = None) -> dict:
    response = client.post(
        "/api/v1/projects",
        json={"name": name or _unique("proj")},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _add_org_member(client: TestClient, username: str) -> None:
    response = client.post(
        "/api/v1/admin/members",
        json={"username": username, "roles": ["researcher"]},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text


class TestProjectMembers:
    def test_creator_is_auto_member_and_list_returns_username(self, client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        members = client.get(f"/api/v1/projects/{project['id']}/members").json()["data"]
        assert members["total"] == 1
        assert members["items"][0]["username"] == "dev"
        assert members["items"][0]["role"] == "owner"

    def test_add_member_flow(self, client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        _add_org_member(client, "alice")

        added = client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"username": "alice", "role": "researcher"},
            headers=csrf_headers(client),
        )
        assert added.status_code == 200, added.text
        assert added.json()["data"]["username"] == "alice"
        assert added.json()["data"]["role"] == "researcher"

        duplicate = client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"username": "alice"},
            headers=csrf_headers(client),
        )
        assert duplicate.status_code == 409

        actions = {
            row["action"]
            for row in client.get("/api/v1/audit-logs", params={"page_size": 100}).json()["data"]["items"]
        }
        assert "project.member.add" in actions

    def test_add_unknown_or_out_of_org_user_404(self, client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        response = client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"username": "ghost-user"},
            headers=csrf_headers(client),
        )
        assert response.status_code == 404
        assert "不属于当前组织" in response.json()["message"]

    def test_remove_requires_confirm_and_no_self_removal(self, client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        _add_org_member(client, "bob")
        client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"username": "bob"},
            headers=csrf_headers(client),
        )
        member_id = next(
            m["user_id"]
            for m in client.get(f"/api/v1/projects/{project['id']}/members").json()["data"]["items"]
            if m["username"] == "bob"
        )

        denied = client.delete(
            f"/api/v1/projects/{project['id']}/members/{member_id}", headers=csrf_headers(client)
        )
        assert denied.status_code == 400
        assert denied.json()["code"] == 1007

        ok = client.delete(
            f"/api/v1/projects/{project['id']}/members/{member_id}?confirm=true",
            headers=csrf_headers(client),
        )
        assert ok.status_code == 200
        remaining = client.get(f"/api/v1/projects/{project['id']}/members").json()["data"]
        assert all(m["username"] != "bob" for m in remaining["items"])

        # 不能移除自己（创建者 = admin 登录的 dev）
        own_id = next(m["user_id"] for m in remaining["items"] if m["username"] == "dev")
        self_removal = client.delete(
            f"/api/v1/projects/{project['id']}/members/{own_id}?confirm=true",
            headers=csrf_headers(client),
        )
        assert self_removal.status_code == 400
        assert "不能移除自己" in self_removal.json()["message"]

    def test_member_manage_requires_staff(self, client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        _add_org_member(client, "carol")
        client.post("/api/v1/auth/logout", headers=csrf_headers(client))
        login(client, "viewer")
        denied = client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"username": "carol"},
            headers=csrf_headers(client),
        )
        assert denied.status_code == 403


class TestVisibility:
    def test_visibility_change_requires_confirm_and_admin(self, client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        assert project["visibility"] == "private"

        denied = client.post(
            f"/api/v1/projects/{project['id']}/visibility",
            json={"visibility": "public"},
            headers=csrf_headers(client),
        )
        assert denied.status_code == 400
        assert denied.json()["code"] == 1007

        ok = client.post(
            f"/api/v1/projects/{project['id']}/visibility?confirm=true",
            json={"visibility": "public"},
            headers=csrf_headers(client),
        )
        assert ok.status_code == 200
        assert ok.json()["data"]["visibility"] == "public"

        actions = {
            row["action"]
            for row in client.get("/api/v1/audit-logs", params={"page_size": 100}).json()["data"]["items"]
        }
        assert "project.visibility.change" in actions

    def test_invalid_visibility_value_rejected(self, client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        response = client.post(
            f"/api/v1/projects/{project['id']}/visibility?confirm=true",
            json={"visibility": "everyone"},
            headers=csrf_headers(client),
        )
        assert response.status_code == 422  # pydantic pattern 校验

    def test_cross_tenant_404(self, client: TestClient, other_org_client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        login(other_org_client, "admin")
        assert other_org_client.get(f"/api/v1/projects/{project['id']}/members").status_code == 404
        assert (
            other_org_client.post(
                f"/api/v1/projects/{project['id']}/members",
                json={"username": "dev"},
                headers=csrf_headers(other_org_client),
            ).status_code
            == 404
        )
        assert (
            other_org_client.post(
                f"/api/v1/projects/{project['id']}/visibility?confirm=true",
                json={"visibility": "public"},
                headers=csrf_headers(other_org_client),
            ).status_code
            == 404
        )
