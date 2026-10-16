"""任务只读 API 测试（阶段 4 子集：列表 + 详情 + 租户隔离）。"""

from __future__ import annotations

import sqlite3
import uuid

from fastapi.testclient import TestClient

from conftest import _TEST_DB, csrf_headers, login  # noqa: PLC2701
from qqlab.core.ids import stable_uuid


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _enqueue_import_job(client: TestClient) -> dict:
    """经数据集导入端点造一个真实 job（唯一不直连 DB 的入队路径）。"""
    source = client.post(
        "/api/v1/data-sources",
        json={"name": _unique("src")},
        headers=csrf_headers(client),
    ).json()["data"]
    license_row = client.post(
        "/api/v1/data-licenses",
        json={
            "data_source_id": source["id"],
            "license_ref": _unique("ToS"),
            "allowed_use": "internal research only",
            "granted_by": "unit-test",
        },
        headers=csrf_headers(client),
    ).json()["data"]
    dataset = client.post(
        "/api/v1/datasets",
        json={
            "data_source_id": source["id"],
            "license_id": license_row["id"],
            "name": _unique("ds"),
        },
        headers=csrf_headers(client),
    ).json()["data"]
    receipt = client.post(f"/api/v1/datasets/{dataset['id']}/import", headers=csrf_headers(client)).json()[
        "data"
    ]
    return receipt


class TestJobsRead:
    def test_list_and_get(self, client: TestClient) -> None:
        login(client, "admin")
        receipt = _enqueue_import_job(client)

        detail = client.get(f"/api/v1/jobs/{receipt['job_id']}").json()["data"]
        assert detail["id"] == receipt["job_id"]
        assert detail["kind"] == "dataset_import"
        assert detail["status"] == "queued"
        assert detail["progress"] == 0
        assert detail["attempts"] == 0

        listing = client.get("/api/v1/jobs", params={"kind": "dataset_import"}).json()["data"]
        assert listing["total"] >= 1
        assert receipt["job_id"] in {item["id"] for item in listing["items"]}

        empty_kind = client.get("/api/v1/jobs", params={"kind": "no_such_kind"}).json()["data"]
        assert empty_kind["total"] == 0

    def test_unknown_job_404(self, client: TestClient) -> None:
        login(client, "admin")
        assert client.get(f"/api/v1/jobs/{uuid.uuid4()}").status_code == 404

    def test_viewer_can_read_jobs(self, client: TestClient) -> None:
        login(client, "admin")
        receipt = _enqueue_import_job(client)
        client.post("/api/v1/auth/logout", headers=csrf_headers(client))
        login(client, "viewer")
        assert client.get(f"/api/v1/jobs/{receipt['job_id']}").status_code == 200

    def test_cross_tenant_job_404(self, client: TestClient) -> None:
        """另一组织的 job（直连 SQL 造数）对本组织不可见。"""
        login(client, "admin")
        foreign_id = uuid.uuid4()
        now = "2026-10-15 00:00:00.000000"
        conn = sqlite3.connect(_TEST_DB)
        try:
            conn.execute(
                """
                INSERT INTO jobs (id, org_id, kind, status, priority, payload, progress,
                                  attempts, max_attempts, requested_by, created_by,
                                  created_at, updated_at)
                VALUES (?, ?, 'dataset_import', 'queued', 100, '{}', 0, 0, 3, 'other', ?, ?, ?)
                """,
                (
                    foreign_id.hex,
                    stable_uuid("other-org").hex,
                    stable_uuid("other-user").hex,
                    now,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        assert client.get(f"/api/v1/jobs/{foreign_id}").status_code == 404
        listing = client.get("/api/v1/jobs", params={"page_size": 200}).json()["data"]
        assert foreign_id not in {uuid.UUID(item["id"]) for item in listing["items"]}


class TestJobLogs:
    def test_incremental_logs_empty_for_queued(self, client: TestClient) -> None:
        """阶段 5 轮询约定：GET /jobs/{id}/logs?since_seq=N → 状态 + 新日志 + next_seq。"""
        login(client, "admin")
        receipt = _enqueue_import_job(client)

        first = client.get(f"/api/v1/jobs/{receipt['job_id']}/logs")
        assert first.status_code == 200, first.text
        data = first.json()["data"]
        assert data["items"] == []  # 任务未开跑（API 测试无 worker）
        assert data["next_seq"] == 0
        assert data["status"] == "queued"
        assert data["progress"] == 0

        # since_seq 参数透传（无新日志仍是空切片）
        again = client.get(f"/api/v1/jobs/{receipt['job_id']}/logs", params={"since_seq": 0}).json()["data"]
        assert again["items"] == []

    def test_logs_cross_tenant_404(self, client: TestClient, other_org_client: TestClient) -> None:
        login(client, "admin")
        receipt = _enqueue_import_job(client)
        login(other_org_client, "admin")
        response = other_org_client.get(f"/api/v1/jobs/{receipt['job_id']}/logs")
        assert response.status_code == 404


class TestJobCancelRetry:
    def test_cancel_queued_then_conflict(self, client: TestClient) -> None:
        """queued → 原子 CAS 直接取消；二次取消/终态 → 409。"""
        login(client, "admin")
        receipt = _enqueue_import_job(client)

        canceled = client.post(f"/api/v1/jobs/{receipt['job_id']}/cancel", headers=csrf_headers(client))
        assert canceled.status_code == 200, canceled.text
        assert canceled.json()["data"]["status"] == "canceled"

        detail = client.get(f"/api/v1/jobs/{receipt['job_id']}").json()["data"]
        assert detail["status"] == "canceled"
        assert detail["finished_at"] is not None

        # 终态再取消 → 409
        again = client.post(f"/api/v1/jobs/{receipt['job_id']}/cancel", headers=csrf_headers(client))
        assert again.status_code == 409

    def test_retry_canceled_copies_payload(self, client: TestClient) -> None:
        """retry = 复制 payload + retry_of 标记重新入队（返回新任务）。"""
        login(client, "admin")
        receipt = _enqueue_import_job(client)
        client.post(f"/api/v1/jobs/{receipt['job_id']}/cancel", headers=csrf_headers(client))

        retried = client.post(f"/api/v1/jobs/{receipt['job_id']}/retry", headers=csrf_headers(client))
        assert retried.status_code == 200, retried.text
        new_job = retried.json()["data"]
        assert new_job["status"] == "queued"
        assert new_job["id"] != receipt["job_id"]

        detail = client.get(f"/api/v1/jobs/{new_job['id']}").json()["data"]
        assert detail["payload"]["retry_of"] == receipt["job_id"]
        # 原 payload 字段完整保留
        original = client.get(f"/api/v1/jobs/{receipt['job_id']}").json()["data"]
        for key, value in original["payload"].items():
            assert detail["payload"][key] == value

    def test_retry_running_or_queued_409(self, client: TestClient) -> None:
        """只有 failed/canceled 可重试：queued 拒绝（409）。"""
        login(client, "admin")
        receipt = _enqueue_import_job(client)
        response = client.post(f"/api/v1/jobs/{receipt['job_id']}/retry", headers=csrf_headers(client))
        assert response.status_code == 409
        assert "重试" in response.json()["message"]

    def test_cancel_cross_tenant_404(self, client: TestClient, other_org_client: TestClient) -> None:
        login(client, "admin")
        receipt = _enqueue_import_job(client)
        login(other_org_client, "admin")
        response = other_org_client.post(
            f"/api/v1/jobs/{receipt['job_id']}/cancel", headers=csrf_headers(other_org_client)
        )
        assert response.status_code == 404
        # 原任务未被动过
        login(client, "admin")
        detail = client.get(f"/api/v1/jobs/{receipt['job_id']}").json()["data"]
        assert detail["status"] == "queued"

    def test_viewer_cannot_control_jobs(self, client: TestClient) -> None:
        login(client, "admin")
        receipt = _enqueue_import_job(client)
        client.post("/api/v1/auth/logout", headers=csrf_headers(client))
        login(client, "viewer")
        assert client.get(f"/api/v1/jobs/{receipt['job_id']}").status_code == 200  # 可读
        denied = client.post(f"/api/v1/jobs/{receipt['job_id']}/cancel", headers=csrf_headers(client))
        assert denied.status_code == 403
        denied_retry = client.post(f"/api/v1/jobs/{receipt['job_id']}/retry", headers=csrf_headers(client))
        assert denied_retry.status_code == 403
