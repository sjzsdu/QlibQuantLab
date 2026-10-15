"""因子 API 测试：表达式 CRUD + 静态校验 + version+1 + 发布二次确认。"""

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


def _create_factor(client: TestClient, project_id: str, *, name: str | None = None, expression: str = "$close / $open - 1") -> dict:
    response = client.post(
        "/api/v1/factors",
        json={"project_id": project_id, "name": name or _unique("factor"), "expression": expression},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


class TestFactorCrud:
    def test_create_defaults(self, client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        factor = _create_factor(client, project["id"])
        assert factor["version"] == 1
        assert factor["visibility"] == "private"
        assert factor["factor_type"] == "expression"
        assert factor["project_name"] == project["name"]

    def test_invalid_expression_rejected(self, client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        response = client.post(
            "/api/v1/factors",
            json={"project_id": project["id"], "name": _unique("bad"), "expression": "Mean($close, 10, 20)"},
            headers=csrf_headers(client),
        )
        assert response.status_code == 400
        assert "表达式校验未通过" in response.json()["message"]

    def test_unknown_project_404(self, client: TestClient) -> None:
        login(client, "admin")
        response = client.post(
            "/api/v1/factors",
            json={"project_id": str(uuid.uuid4()), "name": _unique("f"), "expression": "$close"},
            headers=csrf_headers(client),
        )
        assert response.status_code == 404

    def test_duplicate_name_conflicts(self, client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        name = _unique("same")
        _create_factor(client, project["id"], name=name)
        second = client.post(
            "/api/v1/factors",
            json={"project_id": project["id"], "name": name, "expression": "$open"},
            headers=csrf_headers(client),
        )
        assert second.status_code == 409

    def test_expression_change_bumps_version(self, client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        factor = _create_factor(client, project["id"])

        renamed = client.patch(
            f"/api/v1/factors/{factor['id']}",
            json={"description": "只改描述"},
            headers=csrf_headers(client),
        ).json()["data"]
        assert renamed["version"] == 1  # 非表达式改动不动版本

        reexpressed = client.patch(
            f"/api/v1/factors/{factor['id']}",
            json={"expression": "Ref($close, 5) / $close - 1"},
            headers=csrf_headers(client),
        ).json()["data"]
        assert reexpressed["version"] == 2

        invalid = client.patch(
            f"/api/v1/factors/{factor['id']}",
            json={"expression": "Bogus($close)"},
            headers=csrf_headers(client),
        )
        assert invalid.status_code == 400
        still = client.get(f"/api/v1/factors/{factor['id']}").json()["data"]
        assert still["version"] == 2  # 校验失败不落库

    def test_delete_requires_confirm(self, client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        factor = _create_factor(client, project["id"])
        denied = client.delete(f"/api/v1/factors/{factor['id']}", headers=csrf_headers(client))
        assert denied.status_code == 400
        assert denied.json()["code"] == 1007
        ok = client.delete(f"/api/v1/factors/{factor['id']}?confirm=true", headers=csrf_headers(client))
        assert ok.status_code == 200
        assert client.get(f"/api/v1/factors/{factor['id']}").status_code == 404


class TestValidateEndpoint:
    def test_validate_valid_expression(self, client: TestClient) -> None:
        login(client, "viewer")  # 只读用户也可用校验
        response = client.post(
            "/api/v1/factors/validate",
            json={"expression": "If(Ref($close, 1) > Mean($close, 20), Std($volume, 10), 0)"},
            headers=csrf_headers(client),
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["valid"] is True
        assert data["fields"] == ["close", "volume"]
        assert data["functions"] == ["If", "Mean", "Ref", "Std"]

    def test_validate_invalid_expression(self, client: TestClient) -> None:
        login(client, "viewer")
        data = client.post(
            "/api/v1/factors/validate",
            json={"expression": "($close / $open"},
            headers=csrf_headers(client),
        ).json()["data"]
        assert data["valid"] is False
        assert data["errors"]


class TestPublish:
    def test_publish_requires_confirm(self, client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        factor = _create_factor(client, project["id"])
        denied = client.post(f"/api/v1/factors/{factor['id']}/publish", headers=csrf_headers(client))
        assert denied.status_code == 400
        assert denied.json()["code"] == 1007

        ok = client.post(
            f"/api/v1/factors/{factor['id']}/publish?confirm=true", headers=csrf_headers(client)
        )
        assert ok.status_code == 200
        assert ok.json()["data"]["visibility"] == "public"

        actions = {row["action"] for row in client.get("/api/v1/audit-logs", params={"page_size": 100}).json()["data"]["items"]}
        assert "factor.publish" in actions

    def test_publish_requires_admin(self, client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        factor = _create_factor(client, project["id"])

        client.post("/api/v1/auth/logout", headers=csrf_headers(client))
        login(client, "researcher")
        denied = client.post(
            f"/api/v1/factors/{factor['id']}/publish?confirm=true", headers=csrf_headers(client)
        )
        assert denied.status_code == 403


class TestRbacAndTenancy:
    def test_viewer_cannot_write(self, client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)

        client.post("/api/v1/auth/logout", headers=csrf_headers(client))
        login(client, "viewer")
        assert client.get("/api/v1/factors").status_code == 200
        denied = client.post(
            "/api/v1/factors",
            json={"project_id": project["id"], "name": _unique("v"), "expression": "$close"},
            headers=csrf_headers(client),
        )
        assert denied.status_code == 403

    def test_cross_tenant_404(self, client: TestClient, other_org_client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        factor = _create_factor(client, project["id"])

        login(other_org_client, "admin")
        assert other_org_client.get(f"/api/v1/factors/{factor['id']}").status_code == 404
        assert (
            other_org_client.patch(
                f"/api/v1/factors/{factor['id']}",
                json={"description": "x"},
                headers=csrf_headers(other_org_client),
            ).status_code
            == 404
        )
        assert (
            other_org_client.delete(
                f"/api/v1/factors/{factor['id']}?confirm=true", headers=csrf_headers(other_org_client)
            ).status_code
            == 404
        )
