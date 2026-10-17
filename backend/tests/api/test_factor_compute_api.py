"""因子计算 API（阶段 6 切片⑤）：提交 / 计算记录 / IC 预览。

- ``POST /factors/{id}/compute``：入队 + 表达式快照进 job payload + run 行 + 审计留痕；
- 同因子已有活跃任务 → 409；未知股票池 → 422 code 1011；区间越界/倒置 → 400 code 1005；
- ``GET /factors/{id}/compute-runs``：分页 + job_status；
- ``GET .../ic-curve``：未完成 → 400 code 1005；完成后点列 + >1500 点降采样。
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import _TEST_DB, csrf_headers, login, make_settings  # noqa: PLC2701
from qqlab.core.ids import stable_uuid
from qqlab.main import create_app

RANGE = ("2023-01-03", "2023-12-29")


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _ready_dataset(tmp_path: Path) -> tuple[TestClient, dict]:
    """独立 app（QLIB_DATA_ROOT=tmp，含 instruments 池文件）+ SQL 回填日期（绕过 worker）。"""
    data_root = tmp_path / "qlib_data"
    org_dir = data_root / "dev-org" / "cn_data"
    inst = org_dir / "instruments"
    inst.mkdir(parents=True)
    (inst / "all.txt").write_text("SH600000\t1999-11-10\t2020-09-25\nSZ000001\t1991-04-03\t2020-09-25\n")
    (inst / "csi300.txt").write_text(
        "SH600000\t2005-01-01\t2020-09-25\nSZ000001\t2005-01-01\t2020-09-25\n"
    )

    client = TestClient(create_app(make_settings(QLIB_DATA_ROOT=str(data_root))))
    login(client, "admin")
    source = client.post(
        "/api/v1/data-sources", json={"name": _unique("src")}, headers=csrf_headers(client)
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
        json={"data_source_id": source["id"], "license_id": license_row["id"], "name": _unique("ds")},
        headers=csrf_headers(client),
    )
    assert dataset.status_code == 200, dataset.text
    row = dataset.json()["data"]
    conn = sqlite3.connect(_TEST_DB)
    try:
        conn.execute(
            "UPDATE datasets SET storage_uri = ?, start_date = ?, end_date = ?, status = 'active' "
            "WHERE id = ?",
            (str(org_dir), *RANGE, uuid.UUID(row["id"]).hex),
        )
        conn.commit()
    finally:
        conn.close()
    return client, row


def _project_and_factor(client: TestClient) -> tuple[dict, dict]:
    project = client.post(
        "/api/v1/projects", json={"name": _unique("proj")}, headers=csrf_headers(client)
    ).json()["data"]
    factor = client.post(
        "/api/v1/factors",
        json={
            "project_id": project["id"],
            "name": _unique("factor"),
            "expression": "$close / Ref($close, 5) - 1",
        },
        headers=csrf_headers(client),
    )
    assert factor.status_code == 200, factor.text
    return project, factor.json()["data"]


def _audit_total(client: TestClient) -> int:
    response = client.get("/api/v1/audit-logs?action=factor.compute&page_size=1")
    assert response.status_code == 200, response.text
    return int(response.json()["data"]["total"])


class TestSubmitCompute:
    def test_submit_queues_job_and_records_snapshot(self, tmp_path: Path) -> None:
        client, dataset = _ready_dataset(tmp_path)
        _project, factor = _project_and_factor(client)
        audit_before = _audit_total(client)

        response = client.post(
            f"/api/v1/factors/{factor['id']}/compute",
            json={"dataset_id": dataset["id"], "universe": "csi300"},
            headers=csrf_headers(client),
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["status"] == "queued"
        assert data["run_id"] and data["job_id"]

        job = client.get(f"/api/v1/jobs/{data['job_id']}").json()["data"]
        assert job["kind"] == "factor_compute"
        payload = job["payload"]
        assert payload["expression"] == factor["expression"]  # 表达式快照
        assert payload["version"] == factor["version"]
        assert payload["universe"] == "csi300"
        assert payload["start_date"] == RANGE[0]
        assert payload["end_date"] == RANGE[1]
        assert payload["run_id"] == data["run_id"]

        runs = client.get(f"/api/v1/factors/{factor['id']}/compute-runs").json()["data"]
        assert runs["total"] == 1
        assert runs["items"][0]["id"] == data["run_id"]
        assert runs["items"][0]["job_status"] in ("queued", "running")
        assert runs["items"][0]["ic_uri"] is None  # 未完成

        assert _audit_total(client) == audit_before + 1  # 共享库：before/after 基线

    def test_active_conflict_409(self, tmp_path: Path) -> None:
        client, dataset = _ready_dataset(tmp_path)
        _project, factor = _project_and_factor(client)
        body = {"dataset_id": dataset["id"]}
        first = client.post(
            f"/api/v1/factors/{factor['id']}/compute", json=body, headers=csrf_headers(client)
        )
        assert first.status_code == 200, first.text
        second = client.post(
            f"/api/v1/factors/{factor['id']}/compute", json=body, headers=csrf_headers(client)
        )
        assert second.status_code == 409, second.text

    def test_unknown_universe_422(self, tmp_path: Path) -> None:
        client, dataset = _ready_dataset(tmp_path)
        _project, factor = _project_and_factor(client)
        response = client.post(
            f"/api/v1/factors/{factor['id']}/compute",
            json={"dataset_id": dataset["id"], "universe": "zzz"},
            headers=csrf_headers(client),
        )
        assert response.status_code == 422, response.text
        body = response.json()
        assert body["code"] == 1011
        assert "csi300" in body["message"]  # 列出可用池

    def test_range_beyond_dataset_400(self, tmp_path: Path) -> None:
        client, dataset = _ready_dataset(tmp_path)
        _project, factor = _project_and_factor(client)
        response = client.post(
            f"/api/v1/factors/{factor['id']}/compute",
            json={"dataset_id": dataset["id"], "start_date": "2024-01-01"},
            headers=csrf_headers(client),
        )
        assert response.status_code == 400, response.text
        assert response.json()["code"] == 1005

    def test_inverted_dates_400(self, tmp_path: Path) -> None:
        client, dataset = _ready_dataset(tmp_path)
        _project, factor = _project_and_factor(client)
        response = client.post(
            f"/api/v1/factors/{factor['id']}/compute",
            json={"dataset_id": dataset["id"], "start_date": "2023-06-01", "end_date": "2023-01-01"},
            headers=csrf_headers(client),
        )
        assert response.status_code == 400, response.text
        assert response.json()["code"] == 1005

    def test_factor_of_other_org_404(self, tmp_path: Path) -> None:
        client, dataset = _ready_dataset(tmp_path)
        _project, factor = _project_and_factor(client)
        other = TestClient(
            create_app(
                make_settings(
                    QLIB_DATA_ROOT=str(tmp_path / "qlib_data"),
                    MOCK_ORG_ID="other-org",
                    MOCK_ORG_SLUG="other",
                    MOCK_ORG_NAME="Other Org",
                    MOCK_USER_ID="other-user",
                    MOCK_USER_USERNAME="other",
                    MOCK_USER_EMAIL="other@qlibquantlab.local",
                )
            )
        )
        login(other, "admin")
        response = other.post(
            f"/api/v1/factors/{factor['id']}/compute",
            json={"dataset_id": dataset["id"]},
            headers=csrf_headers(other),
        )
        assert response.status_code == 404, response.text

    def test_viewer_forbidden_403(self, tmp_path: Path) -> None:
        client, dataset = _ready_dataset(tmp_path)
        _project, factor = _project_and_factor(client)
        login(client, "viewer")
        response = client.post(
            f"/api/v1/factors/{factor['id']}/compute",
            json={"dataset_id": dataset["id"]},
            headers=csrf_headers(client),
        )
        assert response.status_code == 403, response.text


class TestComputeRuns:
    def test_unknown_factor_404(self, tmp_path: Path) -> None:
        client, _dataset = _ready_dataset(tmp_path)
        response = client.get(f"/api/v1/factors/{uuid.uuid4()}/compute-runs")
        assert response.status_code == 404, response.text

    def test_viewer_can_read(self, tmp_path: Path) -> None:
        client, dataset = _ready_dataset(tmp_path)
        _project, factor = _project_and_factor(client)
        client.post(
            f"/api/v1/factors/{factor['id']}/compute",
            json={"dataset_id": dataset["id"]},
            headers=csrf_headers(client),
        )
        login(client, "viewer")
        response = client.get(f"/api/v1/factors/{factor['id']}/compute-runs")
        assert response.status_code == 200, response.text
        assert response.json()["data"]["total"] == 1


def _seed_finished_run(client: TestClient, factor_id: str, *, n_points: int) -> tuple[str, str]:
    """把一条完成的计算记录 + ic.csv 对象写进共享库/本地对象存储。返回 (run_id, 末日)。"""
    import datetime as dt

    run_id = uuid.uuid4().hex
    key = f"dev-org/factors/{factor_id}/runs/{run_id}/ic.csv"
    start = dt.date(2023, 1, 2)
    lines = ["date,ic"]
    for i in range(n_points):
        day = start + dt.timedelta(days=i)
        lines.append(f"{day.isoformat()},{(i % 20) / 100 - 0.1:.2f}")
    payload = ("\n".join(lines) + "\n").encode()
    root = Path(make_settings().STORAGE_LOCAL_ROOT)
    target = root / key.lstrip("/")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)

    project_id = client.get("/api/v1/projects").json()["data"]["items"][0]["id"]
    dataset_id = client.get("/api/v1/datasets").json()["data"]["items"][0]["id"]
    conn = sqlite3.connect(_TEST_DB)
    try:
        conn.execute(
            "INSERT INTO factor_compute_runs "
            "(id, org_id, created_by, created_at, updated_at, project_id, factor_id, dataset_id, "
            " metrics, data_range, ic_uri, started_at, finished_at) "
            "VALUES (?, ?, ?, datetime('now'), datetime('now'), ?, ?, ?, '{}', '{}', ?, "
            " datetime('now'), datetime('now'))",
            (
                run_id,
                stable_uuid("dev-org").hex,
                stable_uuid("dev-user").hex,
                uuid.UUID(project_id).hex,
                uuid.UUID(factor_id).hex,
                uuid.UUID(dataset_id).hex,
                key,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    last_day = (start + dt.timedelta(days=n_points - 1)).isoformat()
    return run_id, last_day


class TestIcCurve:
    def test_not_finished_400(self, tmp_path: Path) -> None:
        client, dataset = _ready_dataset(tmp_path)
        _project, factor = _project_and_factor(client)
        submitted = client.post(
            f"/api/v1/factors/{factor['id']}/compute",
            json={"dataset_id": dataset["id"]},
            headers=csrf_headers(client),
        ).json()["data"]
        response = client.get(
            f"/api/v1/factors/{factor['id']}/compute-runs/{submitted['run_id']}/ic-curve"
        )
        assert response.status_code == 400, response.text
        assert response.json()["code"] == 1005

    def test_finished_returns_points(self, tmp_path: Path) -> None:
        client, _dataset = _ready_dataset(tmp_path)
        _project, factor = _project_and_factor(client)
        run_id, _last_day = _seed_finished_run(client, factor["id"], n_points=10)
        response = client.get(f"/api/v1/factors/{factor['id']}/compute-runs/{run_id}/ic-curve")
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["total"] == 10
        assert data["downsampled"] is False
        assert len(data["points"]) == 10
        assert data["points"][0][0].startswith("2023-01-")
        assert -1.0 <= data["points"][0][1] <= 1.0

    def test_downsampled_over_1500(self, tmp_path: Path) -> None:
        client, _dataset = _ready_dataset(tmp_path)
        _project, factor = _project_and_factor(client)
        run_id, last_day = _seed_finished_run(client, factor["id"], n_points=1800)
        response = client.get(f"/api/v1/factors/{factor['id']}/compute-runs/{run_id}/ic-curve")
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["total"] == 1800
        assert data["downsampled"] is True
        assert len(data["points"]) <= 1501
        assert data["points"][-1][0] == last_day  # 保末点

    def test_run_of_other_factor_404(self, tmp_path: Path) -> None:
        client, _dataset = _ready_dataset(tmp_path)
        _project, factor_a = _project_and_factor(client)
        _project2, factor_b = _project_and_factor(client)
        run_id, _last_day = _seed_finished_run(client, factor_b["id"], n_points=5)
        response = client.get(f"/api/v1/factors/{factor_a['id']}/compute-runs/{run_id}/ic-curve")
        assert response.status_code == 404, response.text
