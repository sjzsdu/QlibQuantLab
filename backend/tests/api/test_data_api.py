"""数据域 API 测试：数据源 / 授权台账 / 数据集 / 导入入队 / 预览。

合规链断言（阶段 1 设计）：无有效台账不可建数据集；吊销后即拒；
预览读取路径强制 org 前缀（越界/跨租户 404）。
"""

from __future__ import annotations

import sqlite3
import uuid
from array import array
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import _TEST_DB, csrf_headers, login, make_settings  # noqa: PLC2701
from qqlab.main import create_app

FIELDS = ("open", "high", "low", "close", "volume", "factor")


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _create_source(client: TestClient, name: str | None = None) -> dict:
    response = client.post(
        "/api/v1/data-sources",
        json={"name": name or _unique("source"), "kind": "market", "vendor": "测试供应商"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _create_license(client: TestClient, source_id: str, *, status: str = "active") -> dict:
    response = client.post(
        "/api/v1/data-licenses",
        json={
            "data_source_id": source_id,
            "license_ref": "TEST-ToS-仅供研究",
            "allowed_use": "internal research only",
            "granted_by": "unit-test",
        },
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    license_row = response.json()["data"]
    if status == "revoked":
        patched = client.patch(
            f"/api/v1/data-licenses/{license_row['id']}",
            json={"status": "revoked"},
            headers=csrf_headers(client),
        )
        assert patched.status_code == 200, patched.text
    return license_row


def _create_dataset(client: TestClient, source_id: str, license_id: str, name: str | None = None) -> dict:
    response = client.post(
        "/api/v1/datasets",
        json={
            "data_source_id": source_id,
            "license_id": license_id,
            "name": name or _unique("dataset"),
        },
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


class TestDataChain:
    def test_source_license_dataset_chain(self, client: TestClient) -> None:
        login(client, "admin")
        source = _create_source(client)
        license_row = _create_license(client, source["id"])
        dataset = _create_dataset(client, source["id"], license_row["id"])

        assert dataset["status"] == "pending"
        assert dataset["data_source_name"] == source["name"]
        assert dataset["license_ref"] == "TEST-ToS-仅供研究"

        detail = client.get(f"/api/v1/data-sources/{source['id']}").json()["data"]
        assert detail["dataset_count"] == 1

    def test_audit_trail_for_data_writes(self, client: TestClient) -> None:
        login(client, "admin")
        source = _create_source(client)
        license_row = _create_license(client, source["id"])
        _create_dataset(client, source["id"], license_row["id"])

        actions = {
            row["action"]
            for row in client.get("/api/v1/audit-logs", params={"page_size": 100}).json()["data"]["items"]
        }
        assert {"data_source.create", "data_license.create", "dataset.create"} <= actions

    def test_revoke_writes_revoke_audit(self, client: TestClient) -> None:
        login(client, "admin")
        source = _create_source(client)
        license_row = _create_license(client, source["id"])
        client.patch(
            f"/api/v1/data-licenses/{license_row['id']}",
            json={"status": "revoked"},
            headers=csrf_headers(client),
        )
        actions = {
            row["action"]
            for row in client.get("/api/v1/audit-logs", params={"page_size": 100}).json()["data"]["items"]
        }
        assert "data_license.revoke" in actions


class TestLicenseCompliance:
    def test_dataset_rejected_with_revoked_license(self, client: TestClient) -> None:
        login(client, "admin")
        source = _create_source(client)
        license_row = _create_license(client, source["id"], status="revoked")
        response = client.post(
            "/api/v1/datasets",
            json={
                "data_source_id": source["id"],
                "license_id": license_row["id"],
                "name": _unique("bad"),
            },
            headers=csrf_headers(client),
        )
        assert response.status_code == 400
        assert response.json()["code"] == 1005
        assert "授权" in response.json()["message"]

    def test_license_from_other_source_rejected(self, client: TestClient) -> None:
        login(client, "admin")
        source_a = _create_source(client)
        source_b = _create_source(client)
        license_b = _create_license(client, source_b["id"])
        response = client.post(
            "/api/v1/datasets",
            json={
                "data_source_id": source_a["id"],
                "license_id": license_b["id"],
                "name": _unique("mismatch"),
            },
            headers=csrf_headers(client),
        )
        assert response.status_code == 400
        assert "不属于该数据源" in response.json()["message"]

    def test_unknown_license_and_source_404(self, client: TestClient) -> None:
        login(client, "admin")
        ghost = str(uuid.uuid4())
        assert (
            client.post(
                "/api/v1/datasets",
                json={"data_source_id": ghost, "license_id": ghost, "name": _unique("g")},
                headers=csrf_headers(client),
            ).status_code
            == 404
        )
        assert client.get(f"/api/v1/data-sources/{ghost}").status_code == 404
        assert client.get(f"/api/v1/data-licenses/{ghost}").status_code == 404


class TestRbacAndTenancy:
    def test_viewer_is_readonly(self, client: TestClient) -> None:
        login(client, "viewer")
        assert client.get("/api/v1/data-sources").status_code == 200
        denied = client.post(
            "/api/v1/data-sources", json={"name": _unique("v")}, headers=csrf_headers(client)
        )
        assert denied.status_code == 403
        assert denied.json()["code"] == 1002

    def test_license_manage_requires_admin(self, client: TestClient) -> None:
        login(client, "admin")
        source = _create_source(client)
        license_row = _create_license(client, source["id"])

        client.post("/api/v1/auth/logout", headers=csrf_headers(client))
        login(client, "researcher")
        denied = client.post(
            "/api/v1/data-licenses",
            json={
                "data_source_id": source["id"],
                "license_ref": "x",
                "allowed_use": "x",
                "granted_by": "x",
            },
            headers=csrf_headers(client),
        )
        assert denied.status_code == 403
        denied_patch = client.patch(
            f"/api/v1/data-licenses/{license_row['id']}",
            json={"status": "revoked"},
            headers=csrf_headers(client),
        )
        assert denied_patch.status_code == 403

    def test_cross_tenant_404(self, client: TestClient, other_org_client: TestClient) -> None:
        login(client, "admin")
        source = _create_source(client)
        license_row = _create_license(client, source["id"])
        dataset = _create_dataset(client, source["id"], license_row["id"])

        login(other_org_client, "admin")
        assert other_org_client.get(f"/api/v1/data-sources/{source['id']}").status_code == 404
        assert other_org_client.get(f"/api/v1/data-licenses/{license_row['id']}").status_code == 404
        assert other_org_client.get(f"/api/v1/datasets/{dataset['id']}").status_code == 404
        assert (
            other_org_client.post(
                f"/api/v1/datasets/{dataset['id']}/import", headers=csrf_headers(other_org_client)
            ).status_code
            == 404
        )


class TestSourceDelete:
    def test_delete_requires_confirm(self, client: TestClient) -> None:
        login(client, "admin")
        source = _create_source(client)
        denied = client.delete(f"/api/v1/data-sources/{source['id']}", headers=csrf_headers(client))
        assert denied.status_code == 400
        assert denied.json()["code"] == 1007

    def test_delete_blocked_when_datasets_exist(self, client: TestClient) -> None:
        login(client, "admin")
        source = _create_source(client)
        license_row = _create_license(client, source["id"])
        _create_dataset(client, source["id"], license_row["id"])
        blocked = client.delete(
            f"/api/v1/data-sources/{source['id']}?confirm=true", headers=csrf_headers(client)
        )
        assert blocked.status_code == 409
        assert "关联数据集" in blocked.json()["message"]


class TestImportFlow:
    def test_import_enqueues_job_and_dedups(self, client: TestClient) -> None:
        login(client, "admin")
        source = _create_source(client)
        license_row = _create_license(client, source["id"])
        dataset = _create_dataset(client, source["id"], license_row["id"])

        response = client.post(f"/api/v1/datasets/{dataset['id']}/import", headers=csrf_headers(client))
        assert response.status_code == 200, response.text
        receipt = response.json()["data"]
        assert receipt["dataset_id"] == dataset["id"]
        assert receipt["job_id"]
        assert receipt["status"] == "queued"

        job = client.get(f"/api/v1/jobs/{receipt['job_id']}").json()["data"]
        assert job["kind"] == "dataset_import"
        assert job["status"] == "queued"
        assert job["payload"]["dataset_id"] == dataset["id"]

        # 活跃任务未结束时重复导入 → 活跃态 payload_hash 唯一索引拦截
        duplicate = client.post(f"/api/v1/datasets/{dataset['id']}/import", headers=csrf_headers(client))
        assert duplicate.status_code == 409


def _write_preview_data(root: Path) -> None:
    dates = ["2024-01-02", "2024-01-03", "2024-01-04"]
    (root / "calendars").mkdir(parents=True)
    (root / "instruments").mkdir(parents=True)
    (root / "calendars" / "day.txt").write_text("\n".join(dates) + "\n")
    (root / "instruments" / "all.txt").write_text("AAA.XSHE\t平安银行\n")
    inst_dir = root / "features" / "AAA.XSHE" / "day"
    inst_dir.mkdir(parents=True)
    for i, field in enumerate(FIELDS):
        (inst_dir / f"{field}.day.bin").write_bytes(array("f", [10.0 + i, 11.0 + i, 12.0 + i]).tobytes())


def _other_org_settings(**overrides):  # noqa: ANN201
    """另一组织的 Mock 身份（username/email 必须错开，users.email 有唯一约束）。"""
    return make_settings(
        MOCK_ORG_ID="other-org",
        MOCK_ORG_SLUG="other",
        MOCK_ORG_NAME="Other Org",
        MOCK_USER_ID="other-user",
        MOCK_USER_USERNAME="other",
        MOCK_USER_EMAIL="other@qlibquantlab.local",
        **overrides,
    )


class TestPreview:
    def _ready_dataset(self, tmp_path: Path) -> tuple[TestClient, dict]:
        """独立 app（QLIB_DATA_ROOT=tmp）+ 直连 SQL 回填 storage_uri（绕过 worker）。"""
        data_root = tmp_path / "qlib_data"
        org_dir = data_root / "dev-org" / "cn_data"
        _write_preview_data(org_dir)

        preview_client = TestClient(create_app(make_settings(QLIB_DATA_ROOT=str(data_root))))
        login(preview_client, "admin")
        source = _create_source(preview_client)
        license_row = _create_license(preview_client, source["id"])
        dataset = _create_dataset(preview_client, source["id"], license_row["id"])

        conn = sqlite3.connect(_TEST_DB)
        try:
            # SQLite 上 Uuid 列存 32 位无连字符 hex（SQLAlchemy Uuid 非原生方言）
            conn.execute(
                "UPDATE datasets SET storage_uri = ?, status = 'active' WHERE id = ?",
                (str(org_dir), dataset["id"].replace("-", "")),
            )
            conn.commit()
        finally:
            conn.close()
        return preview_client, dataset

    def test_instruments_calendar_preview(self, tmp_path: Path) -> None:
        client, dataset = self._ready_dataset(tmp_path)
        base = f"/api/v1/datasets/{dataset['id']}"

        instruments = client.get(f"{base}/instruments").json()["data"]
        assert instruments["total"] == 1
        assert instruments["items"][0]["instrument"] == "AAA.XSHE"

        calendar = client.get(f"{base}/calendar", params={"start": "2024-01-02", "end": "2024-01-03"}).json()[
            "data"
        ]
        assert calendar["total"] == 2
        assert calendar["start"] == "2024-01-02"
        assert calendar["end"] == "2024-01-03"

        preview = client.get(f"{base}/preview", params={"instrument": "AAA.XSHE", "page_size": 2}).json()[
            "data"
        ]
        assert preview["fields"] == list(FIELDS)
        assert preview["total"] == 3
        assert len(preview["items"]) == 2
        assert preview["items"][0]["date"] == "2024-01-02"
        assert preview["items"][0]["values"]["open"] == 10.0
        assert preview["items"][0]["values"]["factor"] == 15.0

        page2 = client.get(
            f"{base}/preview", params={"instrument": "AAA.XSHE", "page_size": 2, "page": 2}
        ).json()["data"]
        assert [row["date"] for row in page2["items"]] == ["2024-01-04"]

    def test_preview_requires_import(self, client: TestClient) -> None:
        login(client, "admin")
        source = _create_source(client)
        license_row = _create_license(client, source["id"])
        dataset = _create_dataset(client, source["id"], license_row["id"])
        response = client.get(f"/api/v1/datasets/{dataset['id']}/preview", params={"instrument": "AAA.XSHE"})
        assert response.status_code == 400
        assert "尚未导入" in response.json()["message"]

    def test_preview_traversal_rejected(self, tmp_path: Path) -> None:
        client, dataset = self._ready_dataset(tmp_path)
        response = client.get(
            f"/api/v1/datasets/{dataset['id']}/preview", params={"instrument": "../etc/passwd"}
        )
        assert response.status_code == 400

    def test_preview_cross_tenant_404(self, tmp_path: Path) -> None:
        client, dataset = self._ready_dataset(tmp_path)
        assert dataset["id"]
        # 切换到另一组织的 app，读不到本组织数据集（含其 storage_uri 路径）
        other = TestClient(create_app(_other_org_settings(QLIB_DATA_ROOT=str(tmp_path / "qlib_data"))))
        login(other, "admin")
        assert other.get(f"/api/v1/datasets/{dataset['id']}/instruments").status_code == 404
        assert other.get(f"/api/v1/datasets/{dataset['id']}/calendar").status_code == 404


def test_org_scoped_storage_path_is_enforced(tmp_path: Path) -> None:
    """storage_uri 指向其他 org 目录 → 404（fail-closed，即使行被篡改）。"""
    data_root = tmp_path / "qlib_data"
    _write_preview_data(data_root / "other-org" / "cn_data")
    client = TestClient(create_app(make_settings(QLIB_DATA_ROOT=str(data_root))))
    login(client, "admin")
    source = _create_source(client)
    license_row = _create_license(client, source["id"])
    dataset = _create_dataset(client, source["id"], license_row["id"])

    conn = sqlite3.connect(_TEST_DB)
    try:
        conn.execute(
            "UPDATE datasets SET storage_uri = ? WHERE id = ?",
            (str(data_root / "other-org" / "cn_data"), dataset["id"].replace("-", "")),
        )
        conn.commit()
    finally:
        conn.close()

    response = client.get(f"/api/v1/datasets/{dataset['id']}/preview", params={"instrument": "AAA.XSHE"})
    assert response.status_code == 404
    assert "不属于当前组织" in response.json()["message"]
