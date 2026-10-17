"""回测导出 API（阶段 6 切片④）：报告 CSV + 持仓明细 + 二次确认 + 审计留痕。

口径断言：报告 CSV 覆盖四标注（data_range 含来源授权链 / cost_config /
limitations / 参数与指标）+ 末尾固定风险提示；持仓明细原样转发对象存储；
无 ``confirm=true`` 一律 400（code 1007）；``backtest.export`` 权限与跨租户 404。
"""

from __future__ import annotations

import csv
import io
import sqlite3
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import _TEST_DB, csrf_headers, login, make_settings  # noqa: PLC2701
from qqlab.main import create_app

COST = {
    "commission_rate": 0.0003,
    "slippage_value": 10.0,
    "impact_rate_per_million": 0.0001,
}


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _seed_dataset_with_dates(client: TestClient) -> dict:
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
            "UPDATE datasets SET start_date = '2023-01-03', end_date = '2023-12-29', "
            "status = 'active' WHERE id = ?",
            (uuid.UUID(dataset["id"]).hex,),
        )
        conn.commit()
    finally:
        conn.close()
    return dataset


def _seed_backtest(client: TestClient) -> dict:
    """数据集 + 项目 + rule 策略 + 提交一个回测（未完成态）。"""
    dataset = _seed_dataset_with_dates(client)
    project = client.post(
        "/api/v1/projects",
        json={"name": _unique("proj")},
        headers=csrf_headers(client),
    ).json()["data"]
    strategy = client.post(
        "/api/v1/strategies",
        json={"project_id": project["id"], "name": _unique("strat")},
        headers=csrf_headers(client),
    ).json()["data"]
    response = client.post(
        "/api/v1/backtests",
        json={
            "strategy_id": strategy["id"],
            "dataset_id": dataset["id"],
            "cost_config": COST,
        },
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _finish(backtest_id: str, *, positions_uri: str | None = None) -> None:
    """直连 SQL 回填"任务已完成"的四标注字段（绕过 worker）。"""
    conn = sqlite3.connect(_TEST_DB)
    try:
        conn.execute(
            "UPDATE backtests SET metrics = ?, data_range = ?, limitations = ?, "
            "positions_uri = ?, curve_uri = ? WHERE id = ?",
            (
                '{"total_return": -0.49, "sharpe": 1.2, "engine": "qlib"}',
                '{"start": "2023-01-03", "end": "2023-12-29", "universe": "csi300", '
                '"topk": 50, "source": {"vendor": "测试供应商", "allowed_use": "internal research only"}}',
                "静态费用模型（佣金/滑点/冲击成本按固定费率估算）；历史回测不代表未来收益。",
                positions_uri,
                "some-org/backtests/x/curve.csv",
                uuid.UUID(backtest_id).hex,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _read_positions_object(key: str) -> bytes:
    """把持仓对象写进测试用本地对象存储（与 app 同一根）。"""
    root = Path(make_settings().STORAGE_LOCAL_ROOT)
    target = root / key.lstrip("/")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = b"date,instrument,shares\n2023-01-04,SH600000,100.000000\n"
    target.write_bytes(payload)
    return payload


class TestReportExport:
    def test_without_confirm_400(self, client: TestClient) -> None:
        login(client, "admin")
        bt = _seed_backtest(client)
        response = client.get(f"/api/v1/backtests/{bt['id']}/export")
        assert response.status_code == 400
        assert response.json()["code"] == 1007

    def test_report_csv_covers_four_annotations(self, client: TestClient) -> None:
        login(client, "admin")
        bt = _seed_backtest(client)
        _finish(bt["id"])
        response = client.get(
            f"/api/v1/backtests/{bt['id']}/export",
            params={"format": "csv", "section": "report", "confirm": True},
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/csv")
        assert "attachment;" in response.headers["content-disposition"]
        assert "report" in response.headers["content-disposition"]
        assert response.content.startswith(b"\xef\xbb\xbf")  # BOM → Excel 打开中文

        rows = list(csv.reader(io.StringIO(response.text.lstrip("\ufeff"))))
        assert rows[0] == ["section", "key", "value"]
        by_section: dict[str, dict[str, str]] = {}
        for section, key, value in rows[1:]:
            by_section.setdefault(section, {})[key] = value

        # 元信息 + 参数 + 指标 + 费用三件套
        assert by_section["meta"]["backtest_id"] == bt["id"]
        assert by_section["meta"]["universe"] == "csi300"
        assert by_section["param"]["topk"] == "50"
        assert by_section["metric"]["total_return"] == "-0.49"
        assert by_section["cost"]["commission_rate"] == "0.0003"
        assert by_section["cost"]["slippage_value"] == "10.0"
        assert by_section["cost"]["impact_rate_per_million"] == "0.0001"
        # data_range 逐层展平：来源授权链进 CSV（四标注第 4 项）
        assert by_section["data_range"]["source.vendor"] == "测试供应商"
        assert by_section["data_range"]["source.allowed_use"] == "internal research only"
        assert by_section["data_range"]["universe"] == "csi300"
        # 局限 + 固定风险提示
        assert "静态费用模型" in by_section["disclaimer"]["limitations"]
        assert "不提供任何投资建议" in by_section["disclaimer"]["risk"]

    def test_report_content_matches_detail_endpoint(self, client: TestClient) -> None:
        """导出与页面展示同源：详情接口的 limitations 必须逐字出现在 CSV 里。"""
        login(client, "admin")
        bt = _seed_backtest(client)
        _finish(bt["id"])
        detail = client.get(f"/api/v1/backtests/{bt['id']}").json()["data"]
        response = client.get(
            f"/api/v1/backtests/{bt['id']}/export",
            params={"section": "report", "confirm": True},
        )
        assert response.status_code == 200, response.text
        assert detail["limitations"] in response.text

    def test_invalid_section_422(self, client: TestClient) -> None:
        login(client, "admin")
        bt = _seed_backtest(client)
        response = client.get(
            f"/api/v1/backtests/{bt['id']}/export",
            params={"section": "trades", "confirm": True},
        )
        assert response.status_code == 422

    def test_unknown_backtest_404(self, client: TestClient) -> None:
        login(client, "admin")
        response = client.get(
            f"/api/v1/backtests/{uuid.uuid4()}/export",
            params={"confirm": True},
        )
        assert response.status_code == 404

    def test_not_finished_has_no_positions_400(self, client: TestClient) -> None:
        login(client, "admin")
        bt = _seed_backtest(client)  # 未回填 positions_uri
        response = client.get(
            f"/api/v1/backtests/{bt['id']}/export",
            params={"section": "positions", "confirm": True},
        )
        assert response.status_code == 400
        assert "持仓明细" in response.json()["message"]


class TestPositionsExport:
    def test_positions_streams_object_bytes(self, client: TestClient) -> None:
        login(client, "admin")
        bt = _seed_backtest(client)
        key = f"dev-org/backtests/{bt['id']}/positions.csv"
        expected = _read_positions_object(key)
        _finish(bt["id"], positions_uri=key)

        response = client.get(
            f"/api/v1/backtests/{bt['id']}/export",
            params={"format": "csv", "section": "positions", "confirm": True},
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/csv")
        assert "positions" in response.headers["content-disposition"]
        assert response.content == expected  # 原样转发（无 BOM、无重编码）

    def test_positions_object_missing_400(self, client: TestClient) -> None:
        login(client, "admin")
        bt = _seed_backtest(client)
        _finish(bt["id"], positions_uri=f"dev-org/backtests/{bt['id']}/gone.csv")
        response = client.get(
            f"/api/v1/backtests/{bt['id']}/export",
            params={"section": "positions", "confirm": True},
        )
        assert response.status_code == 400
        assert "缺失" in response.json()["message"]


class TestExportGuards:
    def test_records_audit_action(self, client: TestClient) -> None:
        login(client, "admin")
        bt = _seed_backtest(client)
        _finish(bt["id"])
        response = client.get(
            f"/api/v1/backtests/{bt['id']}/export",
            params={"section": "report", "confirm": True},
        )
        assert response.status_code == 200, response.text
        logs = client.get(
            "/api/v1/audit-logs",
            params={"action": "backtest.export"},
        ).json()["data"]
        assert logs["total"] >= 1
        latest = logs["items"][0]
        assert latest["resource_id"] == bt["id"]
        assert latest["detail"]["section"] == "report"

    def test_refused_without_confirm_leaves_no_audit(self, client: TestClient) -> None:
        login(client, "admin")
        bt = _seed_backtest(client)
        before = client.get(
            "/api/v1/audit-logs",
            params={"action": "backtest.export"},
        ).json()["data"]["total"]
        assert client.get(f"/api/v1/backtests/{bt['id']}/export").status_code == 400
        after = client.get(
            "/api/v1/audit-logs",
            params={"action": "backtest.export"},
        ).json()["data"]["total"]
        assert after == before  # 未真正导出 → 不新增成功导出记录（测试库跨用例共享）

    def test_viewer_denied_403(self, client: TestClient) -> None:
        login(client, "admin")
        bt = _seed_backtest(client)
        login(client, "viewer")
        response = client.get(
            f"/api/v1/backtests/{bt['id']}/export",
            params={"confirm": True},
        )
        assert response.status_code == 403

    def test_auditor_allowed(self, client: TestClient) -> None:
        login(client, "admin")
        bt = _seed_backtest(client)
        _finish(bt["id"])
        login(client, "auditor")
        response = client.get(
            f"/api/v1/backtests/{bt['id']}/export",
            params={"confirm": True},
        )
        assert response.status_code == 200, response.text

    def test_other_org_404(self, client: TestClient) -> None:
        login(client, "admin")
        bt = _seed_backtest(client)
        _finish(bt["id"])

        other = TestClient(
            create_app(
                make_settings(
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
        response = other.get(
            f"/api/v1/backtests/{bt['id']}/export",
            params={"confirm": True},
        )
        assert response.status_code == 404
