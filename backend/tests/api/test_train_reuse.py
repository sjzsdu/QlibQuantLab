"""训练复用因子值（阶段 6 切片⑥）：显式 opt-in + 同版本计算记录校验。

- 默认 ``reuse_factor_values=False``：payload 不带复用源（重算，行为不变）；
- opt-in 但因子无已完成计算记录（含 values 对象）→ 400 code 1005（不静默回退）；
- opt-in 且有**同版本**已完成记录 → payload.factor_value_sources 带 run_id/values_uri 快照；
- 版本不匹配（记录是旧版本）→ 400；
- 审计 ``train.submit`` detail 记 ``reuse_factor_values``。
"""

from __future__ import annotations

import sqlite3
import uuid

from fastapi.testclient import TestClient
from test_study_api import _seed_model  # noqa: PLC2701

from conftest import _TEST_DB, csrf_headers, login  # noqa: PLC2701
from qqlab.core.ids import stable_uuid


def _job_payload(client: TestClient, job_id: str) -> dict:
    job = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert job["kind"] == "train"
    return dict(job["payload"])


def _seed_compute_run(
    factor_id: str,
    project_id: str,
    dataset_id: str,
    *,
    version: int = 1,
    finished: bool = True,
) -> str:
    """sqlite 直插一条因子计算记录（与共享测试库同根）。

    ``finished=True`` → finished_at + values_uri 齐备（可复用）；
    ``finished=False`` → 未完成（不可复用）。
    """

    run_id = uuid.uuid4().hex
    conn = sqlite3.connect(_TEST_DB)
    try:
        conn.execute(
            "INSERT INTO factor_compute_runs "
            "(id, org_id, created_by, created_at, updated_at, project_id, factor_id, dataset_id, "
            " metrics, data_range, ic_uri, values_uri, started_at, finished_at) "
            "VALUES (?, ?, ?, datetime('now'), datetime('now'), ?, ?, ?, '{}', ?, NULL, ?, "
            " datetime('now'), " + ("datetime('now')" if finished else "NULL") + ")",
            (
                run_id,
                stable_uuid("dev-org").hex,
                stable_uuid("dev-user").hex,
                uuid.UUID(project_id).hex,
                uuid.UUID(factor_id).hex,
                uuid.UUID(dataset_id).hex,
                f'{{"version": {version}}}',
                f"dev-org/factors/{factor_id}/runs/{run_id}/values.csv.gz" if finished else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return run_id


class TestTrainReuse:
    def test_default_is_recompute(self, client: TestClient) -> None:
        """默认关闭：payload 记 reuse_factor_values=False + 空复用源（行为不变）。"""
        login(client, "admin")
        seeded = _seed_model(client)
        response = client.post(
            f"/api/v1/models/{seeded['model']['id']}/train", json={}, headers=csrf_headers(client)
        )
        assert response.status_code == 200, response.text
        payload = _job_payload(client, response.json()["data"]["job_id"])
        assert payload["reuse_factor_values"] is False
        assert payload["factor_value_sources"] == []

    def test_reuse_without_compute_run_400(self, client: TestClient) -> None:
        login(client, "admin")
        seeded = _seed_model(client)
        response = client.post(
            f"/api/v1/models/{seeded['model']['id']}/train",
            json={"reuse_factor_values": True},
            headers=csrf_headers(client),
        )
        assert response.status_code == 400, response.text
        body = response.json()
        assert body["code"] == 1005
        assert "计算" in body["message"]

    def test_reuse_with_matching_run_carries_sources(self, client: TestClient) -> None:
        """同版本已完成记录 → payload 带 run_id/values_uri 快照。"""
        login(client, "admin")
        seeded = _seed_model(client)
        factor_id = seeded["factor"]["id"]
        run_id = _seed_compute_run(
            factor_id, seeded["project"]["id"], seeded["dataset"]["id"], version=1
        )
        response = client.post(
            f"/api/v1/models/{seeded['model']['id']}/train",
            json={"reuse_factor_values": True},
            headers=csrf_headers(client),
        )
        assert response.status_code == 200, response.text
        payload = _job_payload(client, response.json()["data"]["job_id"])
        assert payload["reuse_factor_values"] is True
        sources = payload["factor_value_sources"]
        assert len(sources) == 1
        assert sources[0]["factor_id"] == factor_id
        assert sources[0]["run_id"] and uuid.UUID(sources[0]["run_id"]).hex == run_id
        assert sources[0]["values_uri"].endswith("values.csv.gz")
        assert sources[0]["expression"] == seeded["factor"]["expression"]
        assert sources[0]["version"] == 1

    def test_reuse_version_mismatch_400(self, client: TestClient) -> None:
        """记录版本与模型快照版本不一致 → 422（只认同版本）。"""
        login(client, "admin")
        seeded = _seed_model(client)
        _seed_compute_run(
            seeded["factor"]["id"],
            seeded["project"]["id"],
            seeded["dataset"]["id"],
            version=99,
        )
        response = client.post(
            f"/api/v1/models/{seeded['model']['id']}/train",
            json={"reuse_factor_values": True},
            headers=csrf_headers(client),
        )
        assert response.status_code == 400, response.text

    def test_reuse_unfinished_run_400(self, client: TestClient) -> None:
        """计算记录未完成（无 values 对象）→ 不可复用 → 422。"""
        login(client, "admin")
        seeded = _seed_model(client)
        _seed_compute_run(
            seeded["factor"]["id"],
            seeded["project"]["id"],
            seeded["dataset"]["id"],
            version=1,
            finished=False,
        )
        response = client.post(
            f"/api/v1/models/{seeded['model']['id']}/train",
            json={"reuse_factor_values": True},
            headers=csrf_headers(client),
        )
        assert response.status_code == 400, response.text

    def test_audit_records_reuse_flag(self, client: TestClient) -> None:
        """审计 detail 记 reuse_factor_values（共享库用 action 过滤取最新一条）。"""
        login(client, "admin")
        seeded = _seed_model(client)
        _seed_compute_run(
            seeded["factor"]["id"],
            seeded["project"]["id"],
            seeded["dataset"]["id"],
            version=1,
        )
        response = client.post(
            f"/api/v1/models/{seeded['model']['id']}/train",
            json={"reuse_factor_values": True},
            headers=csrf_headers(client),
        )
        assert response.status_code == 200, response.text
        run_id = response.json()["data"]["training_run_id"]
        logs = client.get(
            "/api/v1/audit-logs", params={"action": "train.submit", "page_size": 50}
        ).json()["data"]
        mine = next(item for item in logs["items"] if item["resource_id"] == run_id)
        assert mine["detail"]["reuse_factor_values"] is True
