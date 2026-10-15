"""确定性合成数据实现（COMPUTE_BACKEND=stub）。

用途（阶段 1 降级总纲）：qlib-server 链路任一环节不可用（R1–R5）时，
阶段 4/5 仍能以合成数据跑通任务状态机、UI 与 CI；同时作为 qlib 实现的
**对照组**（同一模拟器、同一成本口径，只有数据来源不同）。
"""

from __future__ import annotations

import hashlib
import random

from qqlab.adapters.compute.simulator import Bar, PriceSeries, momentum_scores, run_simulation
from qqlab.core.logging import get_logger
from qqlab.ports.compute import BacktestResult, BacktestSpec, ProgressCallback

logger = get_logger("qqlab.compute.stub")

#: 合成数据默认区间（2023 一整年 + 2024 开头，250 个交易日量级）
STUB_START = "2023-01-03"
STUB_END = "2024-01-31"


def _seed_for(spec: BacktestSpec) -> int:
    raw = f"{spec.org_id}:{spec.strategy_id}:{spec.dataset_id}:{spec.benchmark}".encode()
    return int(hashlib.sha256(raw).hexdigest()[:12], 16)


def make_synthetic_prices(
    *,
    n_instruments: int = 30,
    seed: int = 42,
    start: str | None = None,
    end: str | None = None,
) -> PriceSeries:
    """几何布朗运动式合成行情（确定性：同 seed 同区间同结果）。

    ``start``/``end`` 缺省用 ``STUB_START``/``STUB_END``；显式传入（回测把 dataset
    全区间解析进 spec）时按请求区间生成 —— stub 的"数据"必须覆盖回测请求区间，
    否则与合成固定区间交集为空、模拟器报"没有可用的行情日期"（阶段 3 实测踩过）。
    """
    import datetime as _dt

    rng = random.Random(seed)
    start_d = _dt.date.fromisoformat(start) if start else _dt.date.fromisoformat(STUB_START)
    end_d = _dt.date.fromisoformat(end) if end else _dt.date.fromisoformat(STUB_END)
    if end_d < start_d:
        raise ValueError(f"合成行情区间非法：{start_d} > {end_d}")
    dates: list[str] = []
    day = start_d
    while day <= end_d:
        if day.weekday() < 5:  # 跳过周末
            dates.append(day.isoformat())
        day += _dt.timedelta(days=1)
    if not dates:
        raise ValueError(f"合成行情区间内没有交易日：{start_d} → {end_d}")

    prices: PriceSeries = {}
    for idx in range(n_instruments):
        instrument = f"STUB{idx:04d}.XSHE"
        price = 10.0 + rng.random() * 40.0
        drift = rng.uniform(-0.0008, 0.0012)
        bars = []
        for date in dates:
            price = max(0.5, price * (1.0 + rng.gauss(drift, 0.02)))
            spread = abs(rng.gauss(0, 0.003))
            bars.append(
                Bar(
                    date=date,
                    open=round(price * (1.0 + spread), 4),
                    close=round(price, 4),
                    volume=round(rng.uniform(1e5, 5e6), 0),
                )
            )
        prices[instrument] = bars
    return prices


class StubComputeProvider:
    """ComputePort 的本地对照实现：合成数据 + 与 qlib 链路同一个模拟器。"""

    name = "stub"

    def __init__(self, storage=None) -> None:  # noqa: ANN001 - StorageProvider | None
        self._storage = storage

    async def run_backtest(self, spec: BacktestSpec, progress: ProgressCallback) -> BacktestResult:
        await progress(10, "stub: 生成合成行情")
        seed = _seed_for(spec)
        # 合成区间必须覆盖回测请求区间（handler 会把 dataset 全区间解析进 spec），
        # 否则固定 STUB 区间与之无交集 → 模拟器报"没有可用的行情日期"
        prices = make_synthetic_prices(
            seed=seed,
            start=spec.start_date or None,
            end=spec.end_date or None,
        )
        lookback = int(spec.params.get("lookback", 20))

        await progress(40, "stub: 计算动量信号")
        signals = momentum_scores(prices, lookback=lookback)

        await progress(60, "stub: 运行模拟器")
        sim = run_simulation(
            prices=prices,
            signals=signals,
            cost=spec.cost,
            topk=min(spec.topk, 10),
            start_date=spec.start_date or None,
            end_date=spec.end_date or None,
        )

        await progress(80, "stub: 上传净值曲线")
        curve_key = f"{spec.org_id}/backtests/{spec.strategy_id}/stub_curve.csv"
        if self._storage is not None:
            csv = "\n".join(f"{date},{nav:.4f}" for date, nav in sim.nav_curve)
            await self._storage.put(curve_key, csv.encode(), content_type="text/csv")

        data_range = {
            "start": sim.nav_curve[0][0],
            "end": sim.nav_curve[-1][0],
            "freq": "day",
            "n_days": len(sim.nav_curve),
            "engine": self.name,
            "synthetic": True,
        }
        metrics = dict(sim.metrics)
        metrics["engine"] = self.name
        return BacktestResult(
            metrics=metrics,
            data_range=data_range,
            cost_config=spec.cost.to_dict(),
            curve_key=curve_key,
            positions_key=None,
            limitations=(
                "[stub] 使用合成随机行情（seed 确定性），结果**仅用于验证链路与费用口径**，"
                "不代表任何真实市场表现；信号为动量规则，未含融资融券/涨跌停约束。"
            ),
        )

    async def healthcheck(self) -> bool:
        return True
