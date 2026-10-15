"""Qlib 真实现（COMPUTE_BACKEND=qlib，**只在 worker 进程实例化**）。

职责边界：qlib 在这里只做**取数**（D.instruments / D.features 经 Qlib-Server），
交易模拟与费用计算全部走 `simulator.py`（与 stub 同一实现）——
这样成本口径不随计算后端切换而漂移。
"""

from __future__ import annotations

import asyncio

from qqlab.adapters.compute.simulator import Bar, PriceSeries, momentum_scores, run_simulation
from qqlab.config import Settings
from qqlab.core.logging import get_logger
from qqlab.ports.compute import BacktestResult, BacktestSpec, ProgressCallback

logger = get_logger("qqlab.compute.qlib")

#: D.features 的字段集（模拟器只需要开高低收量里的 O/C/V）
FEATURE_FIELDS = ["$open", "$close", "$volume"]


class QlibComputeProvider:
    name = "qlib"

    def __init__(self, settings: Settings, storage=None) -> None:  # noqa: ANN001
        self.settings = settings
        self._storage = storage

    # ------------------------------------------------------------ 取数
    def _fetch_prices(self, spec: BacktestSpec) -> PriceSeries:
        """经 qlib 在线模式取数（阻塞，调用方放进线程）。"""
        from qqlab.worker.qlib_env import qlib_online  # noqa: PLC0415 - qlib 只在 worker 加载

        with qlib_online(self.settings, org_id=spec.org_id):
            from qlib.data import D  # noqa: PLC0415

            instruments = D.list_instruments(instruments=D.instruments("all"), as_list=True)
            # 标的截断（决策 #2）：spec.params.max_instruments 优先，其次 QLIB_DATA_SYMBOLS（0 = 全量）
            limit = int(spec.params.get("max_instruments") or 0) or self.settings.QLIB_DATA_SYMBOLS
            if limit > 0:
                instruments = instruments[:limit]
            start = spec.start_date or None
            end = spec.end_date or None
            df = D.features(instruments, FEATURE_FIELDS, start_time=start, end_time=end)
            if df is None or df.empty:
                raise RuntimeError(
                    "qlib 未返回任何特征数据：确认 bootstrap 已导入数据、"
                    "qlib-server 的 provider_uri 与 worker 一致"
                )
            # MultiIndex(instrument, datetime) -> PriceSeries
            prices: PriceSeries = {}
            for (instrument, datetime_index), row in df.iterrows():
                open_ = row.get("$open")
                close = row.get("$close")
                volume = row.get("$volume")
                if close is None or close != close:  # NaN 跳过
                    continue
                date = str(datetime_index)[:10]
                prices.setdefault(str(instrument), []).append(
                    Bar(
                        date=date,
                        open=float(open_) if open_ == open_ else float(close),
                        close=float(close),
                        volume=float(volume) if volume == volume else 0.0,
                    )
                )
            for bars in prices.values():
                bars.sort(key=lambda bar: bar.date)
            return prices

    # ------------------------------------------------------------ ComputePort
    async def run_backtest(self, spec: BacktestSpec, progress: ProgressCallback) -> BacktestResult:
        await progress(10, "qlib: 连接 Qlib-Server 取数")
        prices = await asyncio.to_thread(self._fetch_prices, spec)
        logger.info(
            "qlib_prices_fetched",
            extra={"instruments": len(prices), "spec_strategy": spec.strategy_id},
        )

        await progress(50, "qlib: 计算动量信号")
        lookback = int(spec.params.get("lookback", 20))
        signals = momentum_scores(prices, lookback=lookback)
        if not signals:
            raise RuntimeError(f"动量信号为空：lookback={lookback} 相对数据区间过长")

        await progress(65, "qlib: 运行模拟器")
        sim = run_simulation(
            prices=prices,
            signals=signals,
            cost=spec.cost,
            topk=spec.topk,
            start_date=spec.start_date or None,
            end_date=spec.end_date or None,
        )

        await progress(85, "qlib: 上传净值曲线")
        curve_key = f"{spec.org_id}/backtests/{spec.strategy_id}/curve.csv"
        if self._storage is not None:
            csv = "\n".join(f"{date},{nav:.4f}" for date, nav in sim.nav_curve)
            await self._storage.put(curve_key, csv.encode(), content_type="text/csv")

        data_range = {
            "start": sim.nav_curve[0][0],
            "end": sim.nav_curve[-1][0],
            "freq": "day",
            "n_days": len(sim.nav_curve),
            "engine": self.name,
            "instruments": len(prices),
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
                "静态费用模型（佣金/滑点/冲击成本按固定费率估算），未含融资融券、"
                "涨跌停与停牌约束；信号为动量规则（非训练模型）；历史回测不代表未来收益。"
            ),
        )

    async def healthcheck(self) -> bool:
        """探测 Qlib-Server 连通性（不依赖数据是否已导入）。"""
        from qqlab.worker.qlib_env import probe_qlib_server  # noqa: PLC0415

        ok, detail = probe_qlib_server(self.settings)
        if not ok:
            logger.warning("qlib_server_unreachable", extra={"detail": detail})
        return ok
