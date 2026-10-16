"""ComputePort 双实现单测：stub 确定性 + 工厂 + qlib 配置纯函数。"""

from __future__ import annotations

import pytest

from conftest import make_settings
from qqlab.adapters.compute import VALID_BACKENDS, build_compute
from qqlab.adapters.compute.stub_compute import (
    STUB_START,
    StubComputeProvider,
    make_synthetic_prices,
)
from qqlab.ports.compute import BacktestSpec, CostConfig, FactorSpec, TrainSpec


def _spec(**overrides) -> BacktestSpec:
    payload = dict(
        org_id="dev-org",
        project_id="00000000-0000-0000-0000-000000000001",
        strategy_id="00000000-0000-0000-0000-000000000002",
        dataset_id="00000000-0000-0000-0000-000000000003",
        benchmark="SH000300",
        cost=CostConfig(),
        topk=5,
        params={"lookback": 10},
    )
    payload.update(overrides)
    return BacktestSpec(**payload)


class TestSyntheticPrices:
    def test_deterministic(self) -> None:
        assert make_synthetic_prices(seed=7) == make_synthetic_prices(seed=7)

    def test_different_seed_differs(self) -> None:
        assert make_synthetic_prices(seed=7) != make_synthetic_prices(seed=8)

    def test_prices_positive_and_sorted(self) -> None:
        prices = make_synthetic_prices(n_instruments=3, seed=1)
        for bars in prices.values():
            dates = [bar.date for bar in bars]
            assert dates == sorted(dates)
            assert all(bar.open > 0 and bar.close > 0 for bar in bars)
        assert bars[0].date >= STUB_START

    def test_covers_requested_range(self) -> None:
        """回测会把 dataset 全区间解析进 spec —— 合成行情必须覆盖请求区间。

        阶段 3 实测回归：dataset 1999–2020 与固定 2023 合成区间无交集，
        模拟器报"没有可用的行情日期"。
        """
        prices = make_synthetic_prices(seed=1, start="1999-11-10", end="2020-09-25")
        bars = next(iter(prices.values()))
        assert bars[0].date >= "1999-11-10"
        assert bars[-1].date <= "2020-09-25"
        assert len(bars) > 5000  # 21 年全工作日量级（含周末过滤）
        # 确定性：同区间同 seed 同结果
        assert prices == make_synthetic_prices(seed=1, start="1999-11-10", end="2020-09-25")

    def test_invalid_range_rejected(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="非法"):
            make_synthetic_prices(start="2024-01-31", end="2023-01-03")


class TestStubCompute:
    async def test_run_backtest_result_shape(self) -> None:
        provider = StubComputeProvider()
        calls: list[tuple[int, str]] = []

        async def progress(pct: int, message: str) -> None:
            calls.append((pct, message))

        result = await provider.run_backtest(_spec(), progress)
        assert result.metrics["engine"] == "stub"
        assert result.data_range["synthetic"] is True
        assert result.data_range["start"] <= result.data_range["end"]
        assert result.cost_config == CostConfig().to_dict()
        assert result.metrics["cost_applied"] == CostConfig().to_dict()
        assert "stub" in result.limitations
        assert result.curve_key.endswith("stub_curve.csv")
        assert [pct for pct, _ in calls] == sorted(pct for pct, _ in calls)

    async def test_deterministic_across_runs(self) -> None:
        provider = StubComputeProvider()

        async def no_progress(pct: int, message: str) -> None:  # noqa: ARG001
            return None

        r1 = await provider.run_backtest(_spec(), no_progress)
        r2 = await provider.run_backtest(_spec(), no_progress)
        assert r1.metrics == r2.metrics

    async def test_curve_uploaded_when_storage_present(self, tmp_path) -> None:
        from qqlab.adapters.storage.local_storage import LocalStorageProvider

        storage = LocalStorageProvider(str(tmp_path))
        provider = StubComputeProvider(storage)

        async def no_progress(pct: int, message: str) -> None:  # noqa: ARG001
            return None

        result = await provider.run_backtest(_spec(), no_progress)
        content = await storage.get(result.curve_key)
        assert content.decode().splitlines()[0].split(",")[0] >= "2023"

    async def test_healthcheck(self) -> None:
        assert await StubComputeProvider().healthcheck() is True


class TestStubTrainPredict:
    """阶段 5：stub 训练/预测 —— 与 qlib 同一接口形状（artifact 落/读口径一致）。"""

    @staticmethod
    async def _noop(pct: int, message: str) -> None:  # noqa: ARG001
        return None

    def _train_spec(self) -> TrainSpec:
        return TrainSpec(
            org_id="dev-org",
            project_id="00000000-0000-0000-0000-000000000001",
            dataset_id="00000000-0000-0000-0000-000000000003",
            model_id="00000000-0000-0000-0000-000000000009",
            factors=[
                FactorSpec(
                    factor_id="f1",
                    name="mom5",
                    expression="$close / Ref($close, 5) - 1",
                    version=1,
                )
            ],
            split={"train": ["2023-01-03", "2023-06-30"], "valid": ["2023-07-03", "2023-12-29"]},
            algo="lgb",
        )

    async def test_train_returns_artifact_and_annotations(self) -> None:
        provider = StubComputeProvider()
        result = await provider.train(self._train_spec(), self._noop)

        assert result.artifact  # pickle 伪模型字节
        assert result.artifact_key.endswith("stub_model.pkl")
        assert result.metrics["engine"] == "stub"
        assert result.metrics["n_factors"] == 1
        assert result.data_range["train"] == ["2023-01-03", "2023-06-30"]
        assert result.data_range["valid"] == ["2023-07-03", "2023-12-29"]
        assert "伪模型" in result.limitations

    async def test_train_deterministic(self) -> None:
        provider = StubComputeProvider()
        r1 = await provider.train(self._train_spec(), self._noop)
        r2 = await provider.train(self._train_spec(), self._noop)
        assert r1.artifact == r2.artifact
        assert r1.metrics == r2.metrics

    async def test_predict_signals_sorted_desc(self) -> None:
        signals = await StubComputeProvider().predict_signals(_spec(), b"", self._noop)
        assert signals
        for _date, scores in signals.items():
            assert scores == sorted(scores, key=lambda t: -t[1])
            assert all(isinstance(s, str) for s, _ in scores)

    async def test_run_backtest_model_signal_labels(self) -> None:
        """注入模型信号 + signal_source=model → metrics/data_range/limitations 全标注。"""
        provider = StubComputeProvider()
        signals = await provider.predict_signals(_spec(), b"", self._noop)
        spec = _spec(signals=signals, signal_source="model")
        result = await provider.run_backtest(spec, self._noop)

        assert result.metrics["signal_source"] == "model"
        assert result.data_range["signal_source"] == "model"
        assert "模型" in result.limitations

    async def test_run_backtest_default_rule_label(self) -> None:
        result = await StubComputeProvider().run_backtest(_spec(), self._noop)
        assert result.metrics["signal_source"] == "rule"
        assert result.data_range["signal_source"] == "rule"
        assert "动量" in result.limitations

    async def test_curve_key_isolated_by_backtest_id(self) -> None:
        """同策略多次回测：curve 键按 backtest_id 隔离，不互相覆盖（阶段 5 回归）。"""
        provider = StubComputeProvider()
        signals = await provider.predict_signals(_spec(), b"", self._noop)
        bt1 = _spec(backtest_id="bt-111", signal_source="model", signals=signals)
        bt2 = _spec(backtest_id="bt-222", signal_source="model", signals=signals)
        r1 = await provider.run_backtest(bt1, self._noop)
        r2 = await provider.run_backtest(bt2, self._noop)
        assert "/bt-111/" in r1.curve_key
        assert "/bt-222/" in r2.curve_key
        assert r1.curve_key != r2.curve_key


class TestBuildCompute:
    def test_stub_backend(self) -> None:
        compute = build_compute(make_settings(COMPUTE_BACKEND="stub"))
        assert compute.name == "stub"

    def test_qlib_backend_builds_lazily(self) -> None:
        """qlib 工厂是惰性的：build 不应把 qlib 拉进 sys.modules（API 进程隔离的结构性证据）。"""
        import sys

        settings = make_settings(COMPUTE_BACKEND="qlib")
        assert "qlib" not in sys.modules
        compute = build_compute(settings)
        assert compute.name == "qlib"
        assert "qlib" not in sys.modules

    def test_invalid_backend_rejected_by_settings(self) -> None:
        with pytest.raises(ValueError, match="COMPUTE_BACKEND"):
            make_settings(COMPUTE_BACKEND="torch")

    def test_valid_backends(self) -> None:
        assert VALID_BACKENDS == ("qlib", "stub")


class TestQlibEnvConfig:
    """build_qlib_config 是纯函数：不 import qlib，只生成参数。"""

    def test_flat_init_kwargs(self) -> None:
        from qqlab.worker.qlib_env import build_qlib_config, data_dir_for

        settings = make_settings()
        cfg = build_qlib_config(settings, "dev-org")
        assert set(cfg) == {
            "provider_uri",
            "mount_path",
            "region",
            "experiment_uri",
            "auto_mount",
            "flask_server",
            "flask_port",
            "redis_host",
            "redis_port",
            "redis_task_db",
        }
        assert cfg["provider_uri"] == data_dir_for(settings, "dev-org")
        assert cfg["provider_uri"].endswith("/dev-org/cn_data")
        assert cfg["mount_path"] == cfg["provider_uri"]  # R4：本地路径替代 NFS
        assert cfg["auto_mount"] is False
        assert cfg["flask_server"] == "qlib-server"
        assert cfg["flask_port"] == 9710
        assert cfg["region"] == "cn"

    def test_per_org_isolation(self) -> None:
        from qqlab.worker.qlib_env import build_qlib_config

        settings = make_settings()
        a = build_qlib_config(settings, "org-a")
        b = build_qlib_config(settings, "org-b")
        assert a["provider_uri"] != b["provider_uri"]
        assert a["experiment_uri"] != b["experiment_uri"]

    def test_probe_unreachable_server_returns_false(self) -> None:
        pytest.importorskip("socketio", reason="probe 需要 python-socketio（worker 环境）")
        from qqlab.worker.qlib_env import probe_qlib_server

        ok, detail = probe_qlib_server(make_settings(QLIB_SERVER_WS_URL="ws://127.0.0.1:1"), timeout=1.0)
        assert ok is False
        assert "ws://127.0.0.1:1" in detail


def test_qlib_env_module_importable_without_qlib() -> None:
    """stub 环境（未装 qlib）也能 import qlib_env —— 延迟导入的直接证据。"""
    import qqlab.worker.qlib_env as mod  # noqa: PLC0415

    assert callable(mod.build_qlib_config)
    assert callable(mod.qlib_online)
    assert callable(mod.probe_dataset_via_qlib)
