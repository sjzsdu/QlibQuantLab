"""core.ic 共享 rank-IC 统计（阶段 6 切片⑤）：口径单测 + 实机回归护栏。

回归护栏（阶段 5 教训，docs/stage5/05-testing §4）：``daily_rank_ics`` 的输入
必须是带 ``(instrument, date)`` MultiIndex 的 Series —— 退化 RangeIndex 会让
``groupby(level=-1)`` 按行分组（每组 1 行 < 5），daily 恒为空、IR 恒 0。
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from qqlab.core.ic import MIN_DAILY_SAMPLES, daily_rank_ics, ic_summary, pooled_rank_ic


def _panel(rows: list[tuple[str, str, float, float]]) -> tuple[pd.Series, pd.Series]:
    """``[(instrument, date, factor, target)]`` → MultiIndex(instrument, date) Series 对。"""
    factor = pd.Series({(i, d): f for i, d, f, _ in rows})
    target = pd.Series({(i, d): t for i, d, _, t in rows})
    return factor, target


class TestPooledRankIc:
    def test_perfect_monotonic(self) -> None:
        assert pooled_rank_ic([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)

    def test_inverted(self) -> None:
        assert pooled_rank_ic([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)

    def test_short_input_zero(self) -> None:
        assert pooled_rank_ic([1.0, 2.0], [10.0, 20.0]) == 0.0

    def test_constant_sequence_zero(self) -> None:
        assert pooled_rank_ic([1, 1, 1, 1], [1, 2, 3, 4]) == 0.0  # corr=NaN → 0.0


class TestDailyRankIcs:
    def test_returns_date_ic_pairs(self) -> None:
        rows = [
            (f"I{i}", day, float(i), float(i))  # 每日完美正相关
            for day in ("2023-01-03", "2023-01-04")
            for i in range(8)
        ]
        factor, target = _panel(rows)
        pairs = daily_rank_ics(factor, target)
        assert [d for d, _ in pairs] == ["2023-01-03", "2023-01-04"]
        assert all(v == pytest.approx(1.0) for _, v in pairs)

    def test_inverted_cross_section_negative(self) -> None:
        rows = [(f"I{i}", "2023-01-03", float(i), float(-i)) for i in range(8)]
        factor, target = _panel(rows)
        pairs = daily_rank_ics(factor, target)
        assert len(pairs) == 1
        assert pairs[0][1] == pytest.approx(-1.0)

    def test_small_cross_section_skipped(self) -> None:
        """每日样本 < MIN_DAILY_SAMPLES → 该日跳过。"""
        rows = [(f"I{i}", "2023-01-03", float(i), float(i)) for i in range(MIN_DAILY_SAMPLES - 1)]
        factor, target = _panel(rows)
        assert daily_rank_ics(factor, target) == []

    def test_rangeindex_input_degenerates_empty(self) -> None:
        """回归护栏：退化 RangeIndex 输入 → 每组 1 行 → 全部跳过（空）。"""
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        assert daily_rank_ics(pd.Series(values), pd.Series(values)) == []

    def test_empty_input(self) -> None:
        empty = pd.Series(dtype=float)
        assert daily_rank_ics(empty, empty) == []


class TestIcSummary:
    def test_empty_all_zero(self) -> None:
        assert ic_summary([]) == {
            "ic_mean": 0.0,
            "ic_std": 0.0,
            "ic_ir": 0.0,
            "ic_positive_ratio": 0.0,
            "n_days": 0,
        }

    def test_basic_moments(self) -> None:
        out = ic_summary([0.1, 0.2, 0.3])
        assert out["ic_mean"] == pytest.approx(0.2, abs=1e-6)
        expected_std = math.sqrt(((0.1 - 0.2) ** 2 + 0.0 + (0.3 - 0.2) ** 2) / 3)
        assert out["ic_std"] == pytest.approx(expected_std, abs=1e-6)
        assert out["ic_ir"] == pytest.approx(0.2 / expected_std, abs=1e-4)
        assert out["n_days"] == 3

    def test_positive_ratio(self) -> None:
        out = ic_summary([0.1, -0.2, 0.3, -0.4])
        assert out["ic_positive_ratio"] == pytest.approx(0.5)
        assert out["n_days"] == 4

    def test_zero_std_ir_zero(self) -> None:
        out = ic_summary([0.1, 0.1, 0.1])
        assert out["ic_std"] == 0.0
        assert out["ic_ir"] == 0.0  # std=0 → IR 记 0（不除零）

    def test_nan_values_filtered(self) -> None:
        out = ic_summary([0.1, float("nan"), 0.3])
        assert out["n_days"] == 2
        assert out["ic_mean"] == pytest.approx(0.2)
