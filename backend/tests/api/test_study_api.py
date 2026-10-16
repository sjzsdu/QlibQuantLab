"""阶段 5 研究域 API 测试：模型 / 训练提交 / 策略 / 回测（四标注、RBAC、租户隔离）。

- 创建模型即快照因子表达式（因子后改不影响模型）；
- 训练提交固化执行快照进 job payload，默认切分取数据集区间；
- 费用三件套缺失 → 422；模型信号未训练 → 409；曲线未生成 → 400；
- 敏感操作二次确认（删除/发布）+ 权限点（viewer 403）+ 跨租户 404。
"""

from __future__ import annotations

import sqlite3
import uuid

from fastapi.testclient import TestClient

from conftest import _TEST_DB, csrf_headers, login  # noqa: PLC2701

TRAIN_RANGE = ("2023-01-03", "2023-12-29")


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _create_project(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/projects",
        json={"name": _unique("proj")},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _create_factor(
    client: TestClient, project_id: str, *, expression: str = "$close / Ref($close, 5) - 1"
) -> dict:
    response = client.post(
        "/api/v1/factors",
        json={"project_id": project_id, "name": _unique("factor"), "expression": expression},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _seed_dataset(client: TestClient, *, with_dates: bool = True) -> dict:
    """数据源 → 授权 → 数据集（直连 SQL 补导入后的日期区间与状态）。"""
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
    if with_dates:
        conn = sqlite3.connect(_TEST_DB)
        try:
            conn.execute(
                "UPDATE datasets SET start_date = ?, end_date = ?, status = 'active' WHERE id = ?",
                (*TRAIN_RANGE, uuid.UUID(row["id"]).hex),
            )
            conn.commit()
        finally:
            conn.close()
    return row


def _seed_model(client: TestClient, *, with_dates: bool = True, expression: str | None = None) -> dict:
    project = _create_project(client)
    dataset = _seed_dataset(client, with_dates=with_dates)
    factor = _create_factor(client, project["id"], **({"expression": expression} if expression else {}))
    response = client.post(
        "/api/v1/models",
        json={
            "project_id": project["id"],
            "dataset_id": dataset["id"],
            "name": _unique("model"),
            "factor_ids": [factor["id"]],
        },
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    return {"model": response.json()["data"], "project": project, "dataset": dataset, "factor": factor}


class TestModelCatalog:
    def test_catalog_lgb_only(self, client: TestClient) -> None:
        login(client, "admin")
        data = client.get("/api/v1/models/catalog").json()["data"]
        assert [item["algo"] for item in data] == ["lgb"]
        assert data[0]["available"] is True


class TestModelCrud:
    def test_create_snapshots_factor_expression(self, client: TestClient) -> None:
        """创建瞬间快照：因子后续改表达式，模型 factor_snapshot 不变（衔接点 #3）。"""
        login(client, "admin")
        seeded = _seed_model(client)
        model, factor = seeded["model"], seeded["factor"]

        assert model["factor_snapshot"][0]["expression"] == factor["expression"]
        assert model["factor_snapshot"][0]["factor_id"] == factor["id"]
        assert model["status"] == "draft"
        assert model["training_config"]["target"]

        patched = client.patch(
            f"/api/v1/factors/{factor['id']}",
            json={"expression": "$volume / $open - 1"},
            headers=csrf_headers(client),
        )
        assert patched.status_code == 200, patched.text

        detail = client.get(f"/api/v1/models/{model['id']}").json()["data"]
        assert detail["factor_snapshot"][0]["expression"] == factor["expression"]

    def test_duplicate_factor_expression_400(self, client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        dataset = _seed_dataset(client)
        f1 = _create_factor(client, project["id"])
        f2 = _create_factor(client, project["id"])  # 同表达式
        response = client.post(
            "/api/v1/models",
            json={
                "project_id": project["id"],
                "dataset_id": dataset["id"],
                "name": _unique("model"),
                "factor_ids": [f1["id"], f2["id"]],
            },
            headers=csrf_headers(client),
        )
        assert response.status_code == 400
        assert "重复" in response.json()["message"]

    def test_unknown_algo_400(self, client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        dataset = _seed_dataset(client)
        factor = _create_factor(client, project["id"])
        response = client.post(
            "/api/v1/models",
            json={
                "project_id": project["id"],
                "dataset_id": dataset["id"],
                "name": _unique("model"),
                "algo": "xgboost",
                "factor_ids": [factor["id"]],
            },
            headers=csrf_headers(client),
        )
        assert response.status_code == 400
        assert "算法" in response.json()["message"]

    def test_update_name_hyperparams(self, client: TestClient) -> None:
        login(client, "admin")
        model = _seed_model(client)["model"]
        response = client.patch(
            f"/api/v1/models/{model['id']}",
            json={"name": _unique("renamed"), "hyperparams": {"n_estimators": 88}},
            headers=csrf_headers(client),
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["hyperparams"]["n_estimators"] == 88
        assert data["algo"] == model["algo"]  # 算法不可改

    def test_model_cross_tenant_404(self, client: TestClient, other_org_client: TestClient) -> None:
        login(client, "admin")
        model = _seed_model(client)["model"]
        login(other_org_client, "admin")
        assert other_org_client.get(f"/api/v1/models/{model['id']}").status_code == 404

    def test_viewer_read_only(self, client: TestClient) -> None:
        login(client, "admin")
        model = _seed_model(client)["model"]
        client.post("/api/v1/auth/logout", headers=csrf_headers(client))
        login(client, "viewer")
        assert client.get(f"/api/v1/models/{model['id']}").status_code == 200
        denied = client.post(
            "/api/v1/models",
            json={"project_id": "x", "dataset_id": "x", "name": "x", "factor_ids": ["x"]},
            headers=csrf_headers(client),
        )
        assert denied.status_code == 403


class TestTrainSubmit:
    def test_submit_default_split(self, client: TestClient) -> None:
        """提交训练：run 先落库 → 入队 → job payload 固化执行快照（可复现性）。"""
        login(client, "admin")
        seeded = _seed_model(client)
        model = seeded["model"]

        response = client.post(
            f"/api/v1/models/{model['id']}/train",
            json={},
            headers=csrf_headers(client),
        )
        assert response.status_code == 200, response.text
        receipt = response.json()["data"]
        assert receipt["status"] == "queued"
        assert receipt["split"]["train"][0] == TRAIN_RANGE[0]
        assert receipt["split"]["valid"][1] == TRAIN_RANGE[1]

        # job payload 携带完整执行快照
        job = client.get(f"/api/v1/jobs/{receipt['job_id']}").json()["data"]
        assert job["kind"] == "train" and job["status"] == "queued"
        assert job["payload"]["factors"][0]["expression"] == seeded["factor"]["expression"]
        assert job["payload"]["split"] == receipt["split"]
        assert job["payload"]["target"]

        # 训练记录列表 + 详情（read-your-writes：提交后立即可见）
        runs = client.get("/api/v1/training-runs", params={"model_id": model["id"]}).json()["data"]
        assert runs["total"] >= 1
        run_id = receipt["training_run_id"]
        assert run_id in {item["id"] for item in runs["items"]}
        detail = client.get(f"/api/v1/training-runs/{run_id}").json()["data"]
        assert detail["job_id"] == receipt["job_id"]
        assert detail["job_status"] == "queued"
        assert detail["model_id"] == model["id"]

        # 模型状态 → training，last_run 可见
        after = client.get(f"/api/v1/models/{model['id']}").json()["data"]
        assert after["status"] == "training"
        assert after["last_run"] is not None

    def test_duplicate_active_train_409(self, client: TestClient) -> None:
        login(client, "admin")
        model = _seed_model(client)["model"]
        first = client.post(f"/api/v1/models/{model['id']}/train", json={}, headers=csrf_headers(client))
        assert first.status_code == 200
        second = client.post(f"/api/v1/models/{model['id']}/train", json={}, headers=csrf_headers(client))
        assert second.status_code == 409
        assert "训练任务" in second.json()["message"]

    def test_dataset_without_dates_400(self, client: TestClient) -> None:
        login(client, "admin")
        model = _seed_model(client, with_dates=False)["model"]
        response = client.post(f"/api/v1/models/{model['id']}/train", json={}, headers=csrf_headers(client))
        assert response.status_code == 400
        assert "日期范围" in response.json()["message"]

    def test_split_out_of_dataset_range_400(self, client: TestClient) -> None:
        login(client, "admin")
        model = _seed_model(client)["model"]
        response = client.post(
            f"/api/v1/models/{model['id']}/train",
            json={"split": {"train": ["2022-01-04", "2023-06-30"], "valid": ["2023-07-03", "2023-12-29"]}},
            headers=csrf_headers(client),
        )
        assert response.status_code == 400
        assert "超出数据集区间" in response.json()["message"]

    def test_split_overlap_422(self, client: TestClient) -> None:
        login(client, "admin")
        model = _seed_model(client)["model"]
        response = client.post(
            f"/api/v1/models/{model['id']}/train",
            json={"split": {"train": ["2023-01-03", "2023-09-30"], "valid": ["2023-06-01", "2023-12-29"]}},
            headers=csrf_headers(client),
        )
        assert response.status_code == 422

    def test_train_requires_permission(self, client: TestClient) -> None:
        login(client, "admin")
        model = _seed_model(client)["model"]
        client.post("/api/v1/auth/logout", headers=csrf_headers(client))
        login(client, "viewer")
        response = client.post(f"/api/v1/models/{model['id']}/train", json={}, headers=csrf_headers(client))
        assert response.status_code == 403


class TestModelDelete:
    def test_requires_confirm_then_bound_strategy(self, client: TestClient) -> None:
        login(client, "admin")
        seeded = _seed_model(client)
        model = seeded["model"]

        denied = client.delete(f"/api/v1/models/{model['id']}", headers=csrf_headers(client))
        assert denied.status_code == 400
        assert "confirm" in denied.json()["message"]

        # 策略绑定中 → 409（先改绑或删策略）
        strategy = client.post(
            "/api/v1/strategies",
            json={
                "project_id": seeded["project"]["id"],
                "name": _unique("strat"),
                "signal_source": "model",
                "model_id": model["id"],
            },
            headers=csrf_headers(client),
        )
        assert strategy.status_code == 200, strategy.text
        bound = client.delete(f"/api/v1/models/{model['id']}?confirm=true", headers=csrf_headers(client))
        assert bound.status_code == 409
        assert "绑定" in bound.json()["message"]

        # 解绑（策略切回 rule）→ 删除成功
        switched = client.patch(
            f"/api/v1/strategies/{strategy.json()['data']['id']}",
            json={"signal_source": "rule"},
            headers=csrf_headers(client),
        )
        assert switched.status_code == 200, switched.text
        ok = client.delete(f"/api/v1/models/{model['id']}?confirm=true", headers=csrf_headers(client))
        assert ok.status_code == 200, ok.text
        assert client.get(f"/api/v1/models/{model['id']}").status_code == 404

    def test_viewer_cannot_delete(self, client: TestClient) -> None:
        login(client, "admin")
        model = _seed_model(client)["model"]
        client.post("/api/v1/auth/logout", headers=csrf_headers(client))
        login(client, "viewer")
        denied = client.delete(f"/api/v1/models/{model['id']}?confirm=true", headers=csrf_headers(client))
        assert denied.status_code == 403


class TestStrategyApi:
    def test_create_rule_strategy(self, client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        response = client.post(
            "/api/v1/strategies",
            json={"project_id": project["id"], "name": _unique("strat"), "lookback": 15},
            headers=csrf_headers(client),
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["signal_source"] == "rule"
        assert data["signal_config"] == {"source": "rule", "lookback": 15}
        assert data["model_id"] is None

    def test_model_source_requires_model_id_422(self, client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        response = client.post(
            "/api/v1/strategies",
            json={"project_id": project["id"], "name": _unique("strat"), "signal_source": "model"},
            headers=csrf_headers(client),
        )
        assert response.status_code == 422

    def test_create_model_source_and_switch_back(self, client: TestClient) -> None:
        login(client, "admin")
        seeded = _seed_model(client)
        project, model = seeded["project"], seeded["model"]

        created = client.post(
            "/api/v1/strategies",
            json={
                "project_id": project["id"],
                "name": _unique("strat"),
                "signal_source": "model",
                "model_id": model["id"],
            },
            headers=csrf_headers(client),
        )
        assert created.status_code == 200, created.text
        row = created.json()["data"]
        assert row["signal_source"] == "model"
        assert row["model_id"] == model["id"]
        assert row["model_name"] == model["name"]

        # 切回 rule → model_id 清空
        switched = client.patch(
            f"/api/v1/strategies/{row['id']}",
            json={"signal_source": "rule"},
            headers=csrf_headers(client),
        )
        assert switched.status_code == 200
        assert switched.json()["data"]["model_id"] is None
        assert switched.json()["data"]["signal_config"]["source"] == "rule"

        # 单独提交 model_id 也算切到 model
        switched2 = client.patch(
            f"/api/v1/strategies/{row['id']}",
            json={"model_id": model["id"]},
            headers=csrf_headers(client),
        )
        assert switched2.status_code == 200
        assert switched2.json()["data"]["signal_source"] == "model"

    def test_publish_requires_confirm_and_admin(self, client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        row = client.post(
            "/api/v1/strategies",
            json={"project_id": project["id"], "name": _unique("strat")},
            headers=csrf_headers(client),
        ).json()["data"]

        denied = client.post(f"/api/v1/strategies/{row['id']}/publish", headers=csrf_headers(client))
        assert denied.status_code == 400
        assert "confirm" in denied.json()["message"]

        client.post("/api/v1/auth/logout", headers=csrf_headers(client))
        login(client, "viewer")
        forbidden = client.post(
            f"/api/v1/strategies/{row['id']}/publish?confirm=true", headers=csrf_headers(client)
        )
        assert forbidden.status_code == 403

        client.post("/api/v1/auth/logout", headers=csrf_headers(client))
        login(client, "admin")
        ok = client.post(f"/api/v1/strategies/{row['id']}/publish?confirm=true", headers=csrf_headers(client))
        assert ok.status_code == 200
        assert ok.json()["data"]["visibility"] == "public"
        assert ok.json()["data"]["is_public"] is True
        assert ok.json()["data"]["version"] == row["version"] + 1

    def test_strategy_cross_tenant_404(self, client: TestClient, other_org_client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        row = client.post(
            "/api/v1/strategies",
            json={"project_id": project["id"], "name": _unique("strat")},
            headers=csrf_headers(client),
        ).json()["data"]
        login(other_org_client, "admin")
        assert other_org_client.get(f"/api/v1/strategies/{row['id']}").status_code == 404


class TestBacktestApi:
    def _create_strategy(self, client: TestClient, project_id: str, **kwargs) -> dict:
        response = client.post(
            "/api/v1/strategies",
            json={"project_id": project_id, "name": _unique("strat"), **kwargs},
            headers=csrf_headers(client),
        )
        assert response.status_code == 200, response.text
        return response.json()["data"]

    def _cost(self, **overrides) -> dict:
        payload = {
            "commission_rate": 0.0003,
            "slippage_value": 10.0,
            "impact_rate_per_million": 0.0001,
        }
        payload.update(overrides)
        return payload

    def test_cost_three_required_422(self, client: TestClient) -> None:
        login(client, "admin")
        seeded = _seed_model(client)
        strategy = self._create_strategy(client, seeded["project"]["id"])
        cost = self._cost()
        del cost["slippage_value"]
        response = client.post(
            "/api/v1/backtests",
            json={
                "strategy_id": strategy["id"],
                "dataset_id": seeded["dataset"]["id"],
                "cost_config": cost,
            },
            headers=csrf_headers(client),
        )
        assert response.status_code == 422

    def test_submit_rule_strategy(self, client: TestClient) -> None:
        login(client, "admin")
        seeded = _seed_model(client)
        strategy = self._create_strategy(client, seeded["project"]["id"], lookback=10)
        response = client.post(
            "/api/v1/backtests",
            json={
                "strategy_id": strategy["id"],
                "dataset_id": seeded["dataset"]["id"],
                "topk": 5,
                "cost_config": self._cost(),
            },
            headers=csrf_headers(client),
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["job_status"] == "queued"
        assert data["cost_config"]["commission_rate"] == 0.0003
        assert data["cost_config"]["slippage_value"] == 10.0
        assert data["metrics"] == {}  # 尚未回测
        assert data["limitations"] is None

        job = client.get(f"/api/v1/jobs/{data['job_id']}").json()["data"]
        assert job["kind"] == "backtest"
        assert job["payload"]["backtest_id"] == data["id"]

        listing = client.get("/api/v1/backtests", params={"strategy_id": strategy["id"]}).json()["data"]
        assert data["id"] in {item["id"] for item in listing["items"]}

    def test_model_signal_without_training_409(self, client: TestClient) -> None:
        """模型信号回测前置校验：没有产出 artifact 的成功训练 → 409（不排队才失败）。"""
        login(client, "admin")
        seeded = _seed_model(client)
        strategy = self._create_strategy(
            client,
            seeded["project"]["id"],
            signal_source="model",
            model_id=seeded["model"]["id"],
        )
        response = client.post(
            "/api/v1/backtests",
            json={
                "strategy_id": strategy["id"],
                "dataset_id": seeded["dataset"]["id"],
                "cost_config": self._cost(),
            },
            headers=csrf_headers(client),
        )
        assert response.status_code == 409
        assert "成功训练" in response.json()["message"]

    def test_curve_before_done_400(self, client: TestClient) -> None:
        login(client, "admin")
        seeded = _seed_model(client)
        strategy = self._create_strategy(client, seeded["project"]["id"])
        submitted = client.post(
            "/api/v1/backtests",
            json={
                "strategy_id": strategy["id"],
                "dataset_id": seeded["dataset"]["id"],
                "cost_config": self._cost(),
            },
            headers=csrf_headers(client),
        ).json()["data"]
        response = client.get(f"/api/v1/backtests/{submitted['id']}/curve")
        assert response.status_code == 400
        assert "尚未完成" in response.json()["message"]

    def test_range_invalid_422(self, client: TestClient) -> None:
        login(client, "admin")
        seeded = _seed_model(client)
        strategy = self._create_strategy(client, seeded["project"]["id"])
        response = client.post(
            "/api/v1/backtests",
            json={
                "strategy_id": strategy["id"],
                "dataset_id": seeded["dataset"]["id"],
                "start_date": "2023-12-01",
                "end_date": "2023-01-01",
                "cost_config": self._cost(),
            },
            headers=csrf_headers(client),
        )
        assert response.status_code == 422

    def test_dataset_without_dates_400(self, client: TestClient) -> None:
        login(client, "admin")
        project = _create_project(client)
        dataset = _seed_dataset(client, with_dates=False)
        strategy = self._create_strategy(client, project["id"])
        response = client.post(
            "/api/v1/backtests",
            json={
                "strategy_id": strategy["id"],
                "dataset_id": dataset["id"],
                "cost_config": self._cost(),
            },
            headers=csrf_headers(client),
        )
        assert response.status_code == 400
        assert "日期范围" in response.json()["message"]

    def test_viewer_cannot_submit(self, client: TestClient) -> None:
        login(client, "admin")
        seeded = _seed_model(client)
        strategy = self._create_strategy(client, seeded["project"]["id"])
        client.post("/api/v1/auth/logout", headers=csrf_headers(client))
        login(client, "viewer")
        response = client.post(
            "/api/v1/backtests",
            json={
                "strategy_id": strategy["id"],
                "dataset_id": seeded["dataset"]["id"],
                "cost_config": self._cost(),
            },
            headers=csrf_headers(client),
        )
        assert response.status_code == 403

    def test_backtest_cross_tenant_404(self, client: TestClient, other_org_client: TestClient) -> None:
        login(client, "admin")
        seeded = _seed_model(client)
        strategy = self._create_strategy(client, seeded["project"]["id"])
        submitted = client.post(
            "/api/v1/backtests",
            json={
                "strategy_id": strategy["id"],
                "dataset_id": seeded["dataset"]["id"],
                "cost_config": self._cost(),
            },
            headers=csrf_headers(client),
        ).json()["data"]
        login(other_org_client, "admin")
        assert other_org_client.get(f"/api/v1/backtests/{submitted['id']}").status_code == 404
