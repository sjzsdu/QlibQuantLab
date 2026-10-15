"""项目 CRUD 与跨租户隔离。"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from conftest import csrf_headers, login


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_create_project_defaults_to_private(client: TestClient) -> None:
    login(client, "admin")
    name = _name("private")
    response = client.post(
        "/api/v1/projects",
        json={"name": name, "description": "首个项目"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["name"] == name
    assert data["visibility"] == "private"  # 默认私有
    assert data["created_by"] == "dev"  # 返回 username 而非 UUID
    assert data["id"]


def test_duplicate_name_conflicts(client: TestClient) -> None:
    login(client, "admin")
    name = _name("dup")
    payload = {"name": name}
    assert client.post("/api/v1/projects", json=payload, headers=csrf_headers(client)).status_code == 200
    second = client.post("/api/v1/projects", json=payload, headers=csrf_headers(client))
    assert second.status_code == 409
    assert second.json()["code"] == 1004


def test_list_filters_by_keyword(client: TestClient) -> None:
    login(client, "admin")
    name = _name("findme")
    client.post("/api/v1/projects", json={"name": name}, headers=csrf_headers(client))
    body = client.get("/api/v1/projects", params={"keyword": name}).json()["data"]
    assert body["total"] >= 1
    assert {item["name"] for item in body["items"]} == {name}


def test_update_project(client: TestClient) -> None:
    login(client, "admin")
    name = _name("edit")
    created = client.post("/api/v1/projects", json={"name": name}, headers=csrf_headers(client)).json()[
        "data"
    ]
    response = client.patch(
        f"/api/v1/projects/{created['id']}",
        json={"description": "改过了"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["description"] == "改过了"
    assert response.json()["data"]["name"] == name


def test_delete_requires_confirmation(client: TestClient) -> None:
    login(client, "admin")
    name = _name("del")
    created = client.post("/api/v1/projects", json={"name": name}, headers=csrf_headers(client)).json()[
        "data"
    ]

    refused = client.delete(f"/api/v1/projects/{created['id']}", headers=csrf_headers(client))
    assert refused.status_code == 400
    assert refused.json()["code"] == 1007  # ConfirmationRequiredError
    assert "confirm=true" in refused.json()["message"]

    confirmed = client.delete(f"/api/v1/projects/{created['id']}?confirm=true", headers=csrf_headers(client))
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["deleted"] is True

    gone = client.get(f"/api/v1/projects/{created['id']}")
    assert gone.status_code == 404


def test_viewer_cannot_write(client: TestClient) -> None:
    login(client, "viewer")
    response = client.post(
        "/api/v1/projects",
        json={"name": _name("viewer")},
        headers=csrf_headers(client),
    )
    assert response.status_code == 403
    assert response.json()["code"] == 1002


def test_researcher_can_create_but_not_delete(client: TestClient) -> None:
    login(client, "researcher")
    created = client.post(
        "/api/v1/projects",
        json={"name": _name("researcher")},
        headers=csrf_headers(client),
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["data"]["id"]

    refused = client.delete(f"/api/v1/projects/{project_id}?confirm=true", headers=csrf_headers(client))
    assert refused.status_code == 403
    assert refused.json()["code"] == 1002


def test_unauthenticated_cannot_list_projects(client: TestClient) -> None:
    assert client.get("/api/v1/projects").status_code == 401


def test_cross_tenant_is_isolated(client: TestClient, other_org_client: TestClient) -> None:
    """A 组织创建的项目，B 组织不可见、不可读、不可删（统一 404）。"""
    login(client, "admin")
    name = _name("tenant")
    created = client.post("/api/v1/projects", json={"name": name}, headers=csrf_headers(client)).json()[
        "data"
    ]
    project_id = created["id"]

    other_user = login(other_org_client, "admin")
    assert other_user["org_id"] == "other-org"

    # 列表里看不到
    other_list = other_org_client.get("/api/v1/projects", params={"keyword": name}).json()["data"]
    assert all(item["name"] != name for item in other_list["items"])

    # 详情 404（与「不存在」同响应，避免探测）
    detail = other_org_client.get(f"/api/v1/projects/{project_id}")
    assert detail.status_code == 404
    assert detail.json()["code"] == 1003

    # 删除 404，且原项目仍在
    deleted = other_org_client.delete(
        f"/api/v1/projects/{project_id}?confirm=true", headers=csrf_headers(other_org_client)
    )
    assert deleted.status_code == 404
    assert client.get(f"/api/v1/projects/{project_id}").status_code == 200

    # A 组织自己的删除仍然可用
    assert (
        client.delete(f"/api/v1/projects/{project_id}?confirm=true", headers=csrf_headers(client)).status_code
        == 200
    )
