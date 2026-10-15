"""健康检查 / 系统信息 / 静态法务文档。"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_live(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["status"] == "alive"
    assert body["request_id"]


def test_ready_all_green(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")
    body = response.json()
    assert response.status_code == 200, body
    assert body["data"]["status"] == "ready"
    assert all(body["data"]["checks"].values())


def test_system_info_has_no_secrets(client: TestClient) -> None:
    response = client.get("/api/v1/system/info")
    body = response.json()
    assert response.status_code == 200
    data = body["data"]
    assert data["auth_provider"] == "mock"
    assert data["storage_backend"] == "local"
    assert data["env"] == "test"
    # 不得泄露任何密钥
    blob = response.text
    assert "test-secret" not in blob
    assert "password" not in blob.lower()


def test_first_response_seeds_csrf_cookie(client: TestClient) -> None:
    """前端契约：每个响应都要带可读的 qqlab_csrf cookie。"""
    response = client.get("/api/v1/health/live")
    header = response.headers.get("set-cookie", "")
    assert "qqlab_csrf=" in header
    assert "HttpOnly" not in header.split("qqlab_csrf=", 1)[1]


def test_legal_meta(client: TestClient) -> None:
    response = client.get("/api/v1/legal/meta")
    assert response.status_code == 200
    codes = {item["code"] for item in response.json()["data"]}
    assert codes == {"terms", "risk", "disclaimer"}


def test_legal_content_public_and_compliant(client: TestClient) -> None:
    for code in ("terms", "risk", "disclaimer"):
        response = client.get(f"/api/v1/legal/{code}")
        assert response.status_code == 200, code
        data = response.json()["data"]
        assert data["content"].strip()
        assert data["version"]
        assert data["effective_at"]
    # 风险提示必须包含核心警示语
    risk = client.get("/api/v1/legal/risk").json()["data"]["content"]
    assert "投资有风险" in risk
    disclaimer = client.get("/api/v1/legal/disclaimer").json()["data"]["content"]
    assert "不构成" in disclaimer


def test_legal_unknown_code_404(client: TestClient) -> None:
    response = client.get("/api/v1/legal/secrets")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == 1003
    assert body["message"]


def test_openapi_available_in_dev(client: TestClient) -> None:
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/projects" in paths
    assert "/api/v1/me" in paths
