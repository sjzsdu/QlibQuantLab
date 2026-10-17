"""模拟器单测：成本口径 100% 透传 + 关键费用边界（阶段 3 硬约束 A3-5）。"""

from __future__ import annotations

import math

import pytest

from qqlab.adapters.compute.simulator import (
    Bar,
    PriceSeries,
    momentum_scores,
    run_simulation,
)
from qqlab.ports.compute import CostConfig


def _linear_market(*, days: int = 60, n_instruments: int = 6, start_price: float = 10.0) -> PriceSeries:
    """构造确定性行情：每个标的以不同速率线性上涨/下跌。"""
    prices: PriceSeries = {}
    for idx in range(n_instruments):
        instrument = f"TEST{idx:04d}.XSHE"
        drift = 0.001 * (idx - n_instruments / 2)  # 有涨有跌 → 动量有区分度
        price = start_price
        bars = []
        for day in range(days):
            date = f"2024-01-{day + 1:02d}" if day < 31 else f"2024-02-{day - 30:02d}"
            price = price * (1.0 + drift)
            bars.append(Bar(date=date, open=price, close=price, volume=1e6))
        prices[instrument] = bars
    return prices


def _flat_market(days: int = 30) -> PriceSeries:
    """零波动行情：净值应恒为初始资金，便于断言纯费用。"""
    return {
        f"FLAT{i:03d}.XSHE": [
            Bar(date=f"2024-03-{day + 1:02d}", open=10.0, close=10.0, volume=1e6) for day in range(days)
        ]
        for i in range(4)
    }


class TestCostConfigRoundtrip:
    def test_to_from_dict_roundtrip(self):
        cost = CostConfig(
            commission_rate=0.001,
            min_commission=8.0,
            slippage_type="fixed_bp",
            slippage_value=15.0,
            impact_rate_per_million=0.0002,
            settlement_fee_rate=0.00003,
            stamp_duty_sell=0.001,
        )
        restored = CostConfig.from_dict(cost.to_dict())
        assert restored == cost

    def test_from_dict_flat_shape(self):
        restored = CostConfig.from_dict(
            {
                "commission_rate": 0.002,
                "min_commission": 3.0,
                "slippage_type": "fixed_bp",
                "slippage_value": 7.0,
                "impact_rate_per_million": 0.001,
                "settlement_fee_rate": 0.00001,
                "stamp_duty_sell": 0.002,
            }
        )
        assert restored.commission_rate == 0.002
        assert restored.slippage_value == 7.0
        assert restored.impact_rate_per_million == 0.001

    def test_from_dict_none_uses_platform_defaults(self):
        restored = CostConfig.from_dict(None)
        assert restored == CostConfig()


class TestMomentumScores:
    def test_scores_ranking_is_deterministic(self):
        prices = _linear_market()
        s1 = momentum_scores(prices, lookback=5)
        s2 = momentum_scores(prices, lookback=5)
        assert s1 == s2
        first_day = sorted(s1)[0]
        scores = s1[first_day]
        assert [s for _, s in scores] == sorted((s for _, s in scores), reverse=True)

    def test_insufficient_history_produces_nothing(self):
        prices = _linear_market(days=3)
        assert momentum_scores(prices, lookback=20) == {}


class TestRunSimulation:
    def test_zero_cost_flat_market_nav_is_constant_after_first_trade(self):
        """零费用 + 零波动 → 首次建仓后净值恒等于初始资金。"""
        prices = _flat_market()
        signals = {
            date: [(f"FLAT{i:03d}.XSHE", 1.0) for i in range(4)]
            for date in [b.date for b in prices["FLAT000.XSHE"]]
        }
        cost = CostConfig(
            commission_rate=0.0,
            min_commission=0.0,
            slippage_value=0.0,
            impact_rate_per_million=0.0,
            settlement_fee_rate=0.0,
            stamp_duty_sell=0.0,
        )
        sim = run_simulation(prices=prices, signals=signals, cost=cost, topk=4, initial_cash=100_000)
        navs = [nav for _, nav in sim.nav_curve]
        # 第一个点是建仓前（次日才成交），其后应恒为 100_000
        assert all(math.isclose(nav, 100_000.0, rel_tol=1e-9) for nav in navs[1:])
        assert sim.trade_count == 4  # 只有首次建仓

    def test_every_cost_field_reduces_pnl_vs_zero_cost(self):
        """六个费用字段逐一打开，净值都应低于零费用基线（透传生效的强证据）。"""
        prices = _linear_market()
        signals = momentum_scores(prices, lookback=5)
        base_cost = CostConfig(
            commission_rate=0.0,
            min_commission=0.0,
            slippage_value=0.0,
            impact_rate_per_million=0.0,
            settlement_fee_rate=0.0,
            stamp_duty_sell=0.0,
        )
        baseline = run_simulation(prices=prices, signals=signals, cost=base_cost, topk=3)
        base_nav = baseline.nav_curve[-1][1]

        variants = {
            "commission": CostConfig(
                commission_rate=0.001,
                min_commission=0.0,
                slippage_value=0.0,
                impact_rate_per_million=0.0,
                settlement_fee_rate=0.0,
                stamp_duty_sell=0.0,
            ),
            "min_commission": CostConfig(
                commission_rate=0.0,
                min_commission=50.0,
                slippage_value=0.0,
                impact_rate_per_million=0.0,
                settlement_fee_rate=0.0,
                stamp_duty_sell=0.0,
            ),
            "slippage": CostConfig(
                commission_rate=0.0,
                min_commission=0.0,
                slippage_value=30.0,
                impact_rate_per_million=0.0,
                settlement_fee_rate=0.0,
                stamp_duty_sell=0.0,
            ),
            "impact": CostConfig(
                commission_rate=0.0,
                min_commission=0.0,
                slippage_value=0.0,
                impact_rate_per_million=0.01,
                settlement_fee_rate=0.0,
                stamp_duty_sell=0.0,
            ),
            "settlement": CostConfig(
                commission_rate=0.0,
                min_commission=0.0,
                slippage_value=0.0,
                impact_rate_per_million=0.0,
                settlement_fee_rate=0.001,
                stamp_duty_sell=0.0,
            ),
            "stamp_duty": CostConfig(
                commission_rate=0.0,
                min_commission=0.0,
                slippage_value=0.0,
                impact_rate_per_million=0.0,
                settlement_fee_rate=0.0,
                stamp_duty_sell=0.01,
            ),
        }
        for name, cost in variants.items():
            sim = run_simulation(prices=prices, signals=signals, cost=cost, topk=3)
            assert sim.nav_curve[-1][1] < base_nav, f"{name} 未降低净值 —— 费用未透传？"
            assert sim.metrics["cost_applied"] == cost.to_dict()

    def test_metrics_include_cost_applied_copy(self):
        prices = _linear_market()
        signals = momentum_scores(prices, lookback=5)
        cost = CostConfig()
        sim = run_simulation(prices=prices, signals=signals, cost=cost, topk=3)
        applied = sim.metrics["cost_applied"]
        assert applied == cost.to_dict()
        assert set(applied) == {
            "commission_rate",
            "min_commission",
            "slippage",
            "impact_cost",
            "settlement_fee",
            "stamp_duty_sell",
        }

    def test_metrics_shape(self):
        prices = _linear_market()
        signals = momentum_scores(prices, lookback=5)
        sim = run_simulation(prices=prices, signals=signals, cost=CostConfig(), topk=3)
        for key in ("total_return", "annualized_return", "sharpe", "max_drawdown", "calmar"):
            assert isinstance(sim.metrics[key], float)
        assert sim.metrics["max_drawdown"] <= 0.0
        assert sim.trade_count > 0
        assert sim.nav_curve[0][0] <= sim.nav_curve[-1][0]

    def test_start_end_filtering(self):
        prices = _linear_market(days=40)
        signals = momentum_scores(prices, lookback=5)
        sim = run_simulation(
            prices=prices,
            signals=signals,
            cost=CostConfig(),
            topk=3,
            start_date="2024-01-10",
            end_date="2024-01-20",
        )
        assert all("2024-01-10" <= d <= "2024-01-20" for d, _ in sim.nav_curve)

    def test_empty_calendar_raises(self):
        with pytest.raises(ValueError, match="没有可用的行情日期"):
            run_simulation(prices={}, signals={}, cost=CostConfig())

    def test_invalid_topk_raises(self):
        prices = _linear_market()
        with pytest.raises(ValueError, match="topk"):
            run_simulation(prices=prices, signals={}, cost=CostConfig(), topk=0)

    def test_bankruptcy_floor_caps_loss_at_100_percent(self):
        """破产底线：净值 ≤ 0 时清零，亏损封顶 -100%，metrics 全为可 JSON 序列化的 float。

        阶段 3 实测回归：min_commission 是绝对费用下限，净值衰减到极小时一笔迷你
        交易的佣金就把现金打穿 → NAV = -5.28 → ``(1+tr) ** (252/n)`` 对负底数取分数幂
        返回 **complex** → JSONB 落库 TypeError → 任务终态丢失。
        """
        import json

        prices = _flat_market()
        signals = {
            date: [(f"FLAT{i:03d}.XSHE", 1.0) for i in range(4)]
            for date in [b.date for b in prices["FLAT000.XSHE"]]
        }
        # 初始资金 1_000 而单笔最低佣金 10_000：建仓当天费用即击穿净值
        cost = CostConfig(min_commission=10_000.0)
        sim = run_simulation(prices=prices, signals=signals, cost=cost, topk=2, initial_cash=1_000.0)

        assert all(nav >= 0.0 for _, nav in sim.nav_curve)  # 净值永不下穿 0
        assert sim.metrics["total_return"] == pytest.approx(-1.0)
        assert sim.metrics["annualized_return"] == pytest.approx(-1.0)  # 而非 complex
        assert sim.metrics["max_drawdown"] == pytest.approx(-1.0)
        json.dumps(sim.metrics)  # 落库前必须能过 JSON 序列化（无 complex/NaN）

    def test_missing_date_forward_fills_last_close_instead_of_zeroing_nav(self):
        """数据缺口日按前值计价：持仓标的当日无行情 → 不清零、不触破产底线。

        实机回归（阶段 5）：dev cn_data 在 2019-04-29 整个 A 股横截面为 NaN（指数有值），
        旧口径「当日无行情即不计市值」把持仓市值瞬间清零 → 误触破产底线 → 净值永久
        归零（total_return 恒 -100%，规则与模型信号源无一幸免）。缺口 ≠ 归零：
        持仓应沿用最近有效收盘计价。
        """
        zero_cost = CostConfig(
            commission_rate=0.0,
            min_commission=0.0,
            slippage_value=0.0,
            impact_rate_per_million=0.0,
            settlement_fee_rate=0.0,
            stamp_duty_sell=0.0,
        )
        dates = [f"2024-06-{d:02d}" for d in range(1, 11)]  # 10 个交易日
        gap = dates[5]
        prices: PriceSeries = {}
        for i in range(4):
            instrument = f"GAP{i:03d}.XSHE"
            # 前三个标的在缺口日整行缺失（模拟整横截面 NaN）；GAP003 代表"指数"全程在场，
            # 提供缺口日 → 交易日历仍包含 gap。
            prices[instrument] = [
                Bar(date=d, open=10.0, close=10.0, volume=1e6) for d in dates if d != gap or i == 3
            ]
        # 手工信号：每天都选前三个（恰好是缺口日缺行情的三个）
        signals = {d: [(f"GAP{i:03d}.XSHE", 1.0 - i * 0.1) for i in range(4)] for d in dates}
        sim = run_simulation(prices=prices, signals=signals, cost=zero_cost, topk=3, initial_cash=100_000)
        navs = dict(sim.nav_curve)

        assert gap in navs  # 缺口日仍在交易日历中（由在场标的提供）
        assert math.isclose(navs[gap], 100_000.0, rel_tol=1e-6)  # 前值计价，净值不塌方
        assert all(nav > 90_000.0 for _, nav in sim.nav_curve)  # 全程无假破产
        assert sim.metrics["total_return"] == pytest.approx(0.0, abs=1e-9)


class TestPositionsHistory:
    """阶段 6 切片④：每日持仓快照（positions.csv 的数据源）。"""

    def test_snapshot_per_trading_day_after_mark_to_market(self):
        """每个交易日一条快照，与 nav_curve 同长同序，且反映收盘后真实持仓。"""
        prices = _flat_market()
        dates = [b.date for b in prices["FLAT000.XSHE"]]
        signals = {date: [(f"FLAT{i:03d}.XSHE", 1.0) for i in range(4)] for date in dates}
        cost = CostConfig(
            commission_rate=0.0,
            min_commission=0.0,
            slippage_value=0.0,
            impact_rate_per_million=0.0,
            settlement_fee_rate=0.0,
            stamp_duty_sell=0.0,
        )
        sim = run_simulation(prices=prices, signals=signals, cost=cost, topk=4, initial_cash=100_000)

        assert len(sim.positions_history) == len(sim.nav_curve)
        assert [d for d, _ in sim.positions_history] == [d for d, _ in sim.nav_curve]
        # 首日尚无成交（次日开盘成交）→ 空仓；其后建仓完成 → 4 只等权
        first_day, first_snap = sim.positions_history[0]
        assert first_snap == {}
        later_day, later_snap = sim.positions_history[-1]
        assert later_day == dates[-1]
        assert len(later_snap) == 4
        assert all(shares > 0 for shares in later_snap.values())

    def test_snapshot_is_sorted_and_nonzero_only(self):
        """快照按标的升序、只记非零持仓（与 final_positions 口径一致）。"""
        prices = _linear_market()
        signals = momentum_scores(prices, lookback=5)
        cost = CostConfig(
            commission_rate=0.0,
            min_commission=0.0,
            slippage_value=0.0,
            impact_rate_per_million=0.0,
            settlement_fee_rate=0.0,
            stamp_duty_sell=0.0,
        )
        sim = run_simulation(prices=prices, signals=signals, cost=cost, topk=3, initial_cash=100_000)
        assert sim.positions_history
        for _, snap in sim.positions_history:
            keys = list(snap)
            assert keys == sorted(keys)
            assert all(abs(s) > 1e-9 for s in snap.values())
        # 末日快照与 final_positions 同口径
        assert sim.positions_history[-1][1] == sim.final_positions

    def test_positions_csv_header_and_rows(self):
        """CSV 序列化：表头固定，行按 (date, instrument)，shares 保留 6 位小数。"""
        from qqlab.adapters.compute.simulator import positions_csv

        text = positions_csv(
            [
                ("2024-01-02", {"SH600000": 100.5, "SZ000001": 0.1234567}),
                ("2024-01-03", {}),
            ]
        )
        lines = text.split("\n")
        assert lines[0] == "date,instrument,shares"
        assert lines[1] == "2024-01-02,SH600000,100.500000"
        assert lines[2] == "2024-01-02,SZ000001,0.123457"
        assert len(lines) == 3  # 空仓日不产出行

    def test_positions_csv_empty_history_has_header(self):
        from qqlab.adapters.compute.simulator import positions_csv

        assert positions_csv([]) == "date,instrument,shares"
