"""股票池 API（阶段 6 D6）：universes 清单 + 提交期校验 + payload/params 记录。

- ``GET /datasets/{id}/universes``：返回池名 + 标的数（含 3 列分段文件的去重计数）；
- 回测/训练提交：非 all 池必须存在于数据集 instruments/（未知 → 422 code 1011）；
- 未导入数据集（storage_uri 空）提交非 all 池 → 422；
- 提交成功后 ``backtest.params.universe`` / ``job.payload.universe`` 记录所选池。
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import _TEST_DB, csrf_headers, login, make_settings  # noqa: PLC2701
from qqlab.main import create_app

TRAIN_RANGE = ("2023-01-03", "2023-12-29")


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _write_universe_files(root: Path) -> None:
    """all（3 列含指数）+ csi300（3 列含重复分段）+ csi500（2 列）。"""
    inst = root / "instruments"
    inst.mkdir(parents=True)
    (inst / "all.txt").write_text(
        "SH000300\t2005-01-04\t2020-09-25\n"
        "SH600000\t1999-11-10\t2020-09-25\n"
        "SZ000001\t1991-04-03\t2020-09-25\n"
    )
    # 820 行 690 唯一的真实形态缩影：同标的多段分段
    (inst / "csi300.txt").write_text(
        "SH600000\t2005-01-01\t2010-12-31\n"
        "SH600000\t2011-01-01\t2020-09-25\n"
        "SZ000001\t2005-01-01\t2020-09-25\n"
    )
    (inst / "csi500.txt").write_text("SZ000002\nSH600004\n")


def _ready_dataset(tmp_path: Path) -> tuple[TestClient, dict]:
    """独立 app（QLIB_DATA_ROOT=tmp）+ SQL 回填 storage_uri/日期（绕过 worker）。"""
    data_root = tmp_path / "qlib_data"
    org_dir = data_root / "dev-org" / "cn_data"
    _write_universe_files(org_dir)

    client = TestClient(create_app(make_settings(QLIB_DATA_ROOT=str(data_root))))
    login(client, "admin")
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
    )
    assert dataset.status_code == 200, dataset.text
    row = dataset.json()["data"]
    conn = sqlite3.connect(_TEST_DB)
    try:
        conn.execute(
            "UPDATE datasets SET storage_uri = ?, start_date = ?, end_date = ?, status = 'active' "
            "WHERE id = ?",
            (str(org_dir), *TRAIN_RANGE, uuid.UUID(row["id"]).hex),
        )
        conn.commit()
    finally:
        conn.close()
    return client, row


def _project(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/projects",
        json={"name": _unique("proj")},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _strategy(client: TestClient, project_id: str) -> dict:
    response = client.post(
        "/api/v1/strategies",
        json={"project_id": project_id, "name": _unique("strat")},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _backtest_cost() -> dict:
    return {
        "commission_rate": 0.0003,
        "slippage_value": 10.0,
        "impact_rate_per_million": 0.0001,
    }


class TestUniversesEndpoint:
    def test_list_with_counts(self, tmp_path: Path) -> None:
        client, dataset = _ready_dataset(tmp_path)
        response = client.get(f"/api/v1/datasets/{dataset['id']}/universes")
        assert response.status_code == 200, response.text
        items = {item["name"]: item["instruments"] for item in response.json()["data"]["items"]}
        assert items == {"all": 3, "csi300": 2, "csi500": 2}

    def test_dataset_of_other_org_404(self, tmp_path: Path) -> None:
        client, dataset = _ready_dataset(tmp_path)
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
        assert other.get(f"/api/v1/datasets/{dataset['id']}/universes").status_code == 404

    def test_viewer_can_read(self, tmp_path: Path) -> None:
        client, dataset = _ready_dataset(tmp_path)
        login(client, "viewer")
        response = client.get(f"/api/v1/datasets/{dataset['id']}/universes")
        assert response.status_code == 200, response.text


class TestBacktestUniverse:
    def test_valid_universe_recorded_in_params(self, tmp_path: Path) -> None:
        client, dataset = _ready_dataset(tmp_path)
        project = _project(client)
        strategy = _strategy(client, project["id"])
        response = client.post(
            "/api/v1/backtests",
            json={
                "strategy_id": strategy["id"],
                "dataset_id": dataset["id"],
                "universe": "csi300",
                "cost_config": _backtest_cost(),
            },
            headers=csrf_headers(client),
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["params"]["universe"] == "csi300"

    def test_unknown_universe_422(self, tmp_path: Path) -> None:
        client, dataset = _ready_dataset(tmp_path)
        project = _project(client)
        strategy = _strategy(client, project["id"])
        response = client.post(
            "/api/v1/backtests",
            json={
                "strategy_id": strategy["id"],
                "dataset_id": dataset["id"],
                "universe": "zzz",
                "cost_config": _backtest_cost(),
            },
            headers=csrf_headers(client),
        )
        assert response.status_code == 422, response.text
        body = response.json()
        assert body["code"] == 1011
        assert "csi300" in body["message"]  # 列出可用池

    def test_non_all_without_import_422(self, client: TestClient) -> None:
        """未导入数据集（storage_uri 空）提交非 all 池 → 422（无法校验即拒绝）。"""
        login(client, "admin")
        project = _project(client)
        strategy = _strategy(client, project["id"])
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
        conn = sqlite3.connect(_TEST_DB)
        try:
            conn.execute(
                "UPDATE datasets SET start_date = ?, end_date = ?, status = 'active' WHERE id = ?",
                (*TRAIN_RANGE, uuid.UUID(dataset["id"]).hex),
            )
            conn.commit()
        finally:
            conn.close()
        response = client.post(
            "/api/v1/backtests",
            json={
                "strategy_id": strategy["id"],
                "dataset_id": dataset["id"],
                "universe": "csi300",
                "cost_config": _backtest_cost(),
            },
            headers=csrf_headers(client),
        )
        assert response.status_code == 422, response.text
        assert response.json()["code"] == 1011

    def test_malformed_universe_schema_422(self, client: TestClient) -> None:
        """池名 pattern 不合法（含 / 或空串）→ schema 422（信封 code 1422）。"""
        login(client, "admin")
        seeded_source = client.post(
            "/api/v1/data-sources",
            json={"name": _unique("src")},
            headers=csrf_headers(client),
        ).json()["data"]
        license_row = client.post(
            "/api/v1/data-licenses",
            json={
                "data_source_id": seeded_source["id"],
                "license_ref": _unique("ToS"),
                "allowed_use": "internal research only",
                "granted_by": "unit-test",
            },
            headers=csrf_headers(client),
        ).json()["data"]
        dataset = client.post(
            "/api/v1/datasets",
            json={
                "data_source_id": seeded_source["id"],
                "license_id": license_row["id"],
                "name": _unique("ds"),
            },
            headers=csrf_headers(client),
        ).json()["data"]
        project = _project(client)
        strategy = _strategy(client, project["id"])
        response = client.post(
            "/api/v1/backtests",
            json={
                "strategy_id": strategy["id"],
                "dataset_id": dataset["id"],
                "universe": "../evil",
                "cost_config": _backtest_cost(),
            },
            headers=csrf_headers(client),
        )
        assert response.status_code == 422, response.text
        assert response.json()["code"] == 1422


class TestTrainUniverse:
    def test_universe_recorded_in_job_payload(self, tmp_path: Path) -> None:
        client, dataset = _ready_dataset(tmp_path)
        project = _project(client)
        factor = client.post(
            "/api/v1/factors",
            json={
                "project_id": project["id"],
                "name": _unique("factor"),
                "expression": "$close / Ref($close, 5) - 1",
            },
            headers=csrf_headers(client),
        ).json()["data"]
        model = client.post(
            "/api/v1/models",
            json={
                "project_id": project["id"],
                "dataset_id": dataset["id"],
                "name": _unique("model"),
                "factor_ids": [factor["id"]],
            },
            headers=csrf_headers(client),
        )
        assert model.status_code == 200, model.text
        model_id = model.json()["data"]["id"]
        response = client.post(
            f"/api/v1/models/{model_id}/train",
            json={"universe": "csi300"},
            headers=csrf_headers(client),
        )
        assert response.status_code == 200, response.text
        job_id = response.json()["data"]["job_id"]
        job = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
        assert job["payload"]["universe"] == "csi300"

    def test_unknown_universe_422(self, tmp_path: Path) -> None:
        client, dataset = _ready_dataset(tmp_path)
        project = _project(client)
        factor = client.post(
            "/api/v1/factors",
            json={
                "project_id": project["id"],
                "name": _unique("factor"),
                "expression": "$close / Ref($close, 5) - 1",
            },
            headers=csrf_headers(client),
        ).json()["data"]
        model = client.post(
            "/api/v1/models",
            json={
                "project_id": project["id"],
                "dataset_id": dataset["id"],
                "name": _unique("model"),
                "factor_ids": [factor["id"]],
            },
            headers=csrf_headers(client),
        )
        assert model.status_code == 200, model.text
        model_id = model.json()["data"]["id"]
        response = client.post(
            f"/api/v1/models/{model_id}/train",
            json={"universe": "zzz"},
            headers=csrf_headers(client),
        )
        assert response.status_code == 422, response.text
        assert response.json()["code"] == 1011
