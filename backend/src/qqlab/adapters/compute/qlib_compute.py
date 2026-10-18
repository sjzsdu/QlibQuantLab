"""Qlib 真实现（COMPUTE_BACKEND=qlib，**只在 worker 进程实例化**）。

职责边界：qlib 在这里只做**取数**（D.instruments / D.features 经 Qlib-Server），
交易模拟与费用计算全部走 `simulator.py`（与 stub 同一实现）——
这样成本口径不随计算后端切换而漂移。
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any

from qqlab.adapters.compute.simulator import (
    Bar,
    PriceSeries,
    momentum_scores,
    positions_csv,
    run_simulation,
)
from qqlab.config import Settings
from qqlab.core.ic import daily_rank_ics, ic_summary, pooled_rank_ic
from qqlab.core.logging import get_logger
from qqlab.core.qlib_data import read_universe
from qqlab.ports.compute import (
    BacktestResult,
    BacktestSpec,
    FactorComputeResult,
    FactorComputeSpec,
    ProgressCallback,
    SignalMap,
    TrainResult,
    TrainSpec,
)

logger = get_logger("qqlab.compute.qlib")

#: D.features 的字段集（模拟器只需要开高低收量里的 O/C/V）
FEATURE_FIELDS = ["$open", "$close", "$volume"]

#: 因子值面板导出行数上限（date,instrument,value 三列；gzip 前）。超出按面板顺序
#: 截断并置 ``values_truncated`` 标记 —— 全市场长区间面板可达千万行，不设上限会打爆对象存储。
MAX_VALUES_ROWS = 1_000_000


def panel_from_values_csv(gz_bytes: bytes, *, start: str = "", end: str = "") -> pd.Series:  # noqa: F821
    """values.csv.gz（gzip CSV，``date,instrument,value``）→ Series[(instrument, date)]。

    与 qlib ``D.features`` 的 MultiIndex 形状对齐：索引 (instrument: str, date: Timestamp)，
    **末位 level 为日期** —— 训练拼接对齐与 ``core.ic`` 的 ``groupby(level=-1)`` 约定都
    依赖这个形状（阶段 5 实机教训的反向应用）。纯函数，无 qlib 依赖，可单测。
    """
    import gzip as _gzip  # noqa: PLC0415
    import io  # noqa: PLC0415

    import pandas as pd  # noqa: PLC0415

    frame = pd.read_csv(io.BytesIO(_gzip.decompress(gz_bytes)))
    if frame.empty or not {"date", "instrument", "value"} <= set(frame.columns):
        raise RuntimeError("因子值对象为空或格式不符（需要 date,instrument,value 三列）")
    frame["date"] = pd.to_datetime(frame["date"])
    if start:
        frame = frame[frame["date"] >= pd.Timestamp(start)]
    if end:
        frame = frame[frame["date"] <= pd.Timestamp(end)]
    series = frame.set_index(["instrument", "date"])["value"]
    return series.astype("float64")


def slice_panel(panel, instruments: list[str], start: str, end: str):  # noqa: ANN001, ANN201
    """按标的集 + 日期区间 [start, end]（闭区间）切复用面板 —— 与 D.features 的
    start_time/end_time 口径对齐（换用复用值时切分语义不漂移）。"""
    import pandas as pd  # noqa: PLC0415

    dates = panel.index.get_level_values(1)
    mask = (
        panel.index.get_level_values(0).isin(instruments)
        & (dates >= pd.Timestamp(start))
        & (dates <= pd.Timestamp(end))
    )
    return panel.loc[mask]


class QlibComputeProvider:
    name = "qlib"

    def __init__(self, settings: Settings, storage=None) -> None:  # noqa: ANN001
        self.settings = settings
        self._storage = storage

    # ------------------------------------------------------------ 取数
    def _resolve_instruments(self, org_id: str, universe: str) -> list[str]:
        """统一用 stdlib 解析股票池标的（阶段 6 D6）。

        实测（dev-org 全量）：``read_universe`` 与 ``D.list_instruments(D.instruments(name),
        as_list=True)`` 的**集合与顺序完全一致**（all: 3875、csi300: 690），
        故三条取数路径统一走 stdlib —— 与 API 侧校验同源，且不依赖 qlib 在线模式。
        """
        from qqlab.worker.qlib_env import data_dir_for  # noqa: PLC0415 - qlib 只在 worker 加载

        return read_universe(Path(data_dir_for(self.settings, org_id)), universe or "all")

    def _fetch_prices(self, spec: BacktestSpec) -> PriceSeries:
        """经 qlib 在线模式取数（阻塞，调用方放进线程）。"""
        from qqlab.worker.qlib_env import qlib_online  # noqa: PLC0415 - qlib 只在 worker 加载

        instruments = self._resolve_instruments(spec.org_id, spec.universe)
        # 标的截断（决策 #2）：spec.params.max_instruments 优先，其次 QLIB_DATA_SYMBOLS（0 = 全量）
        limit = int(spec.params.get("max_instruments") or 0) or self.settings.QLIB_DATA_SYMBOLS
        if limit > 0:
            instruments = instruments[:limit]

        with qlib_online(self.settings, org_id=spec.org_id):
            from qlib.data import D  # noqa: PLC0415

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

        if spec.signals is not None:
            # 模型信号：worker 已完成 predict_signals 并注入（加载 artifact → 因子 → 预测）
            await progress(50, "qlib: 使用注入的模型信号")
            signals = spec.signals
        else:
            await progress(50, "qlib: 计算动量信号")
            lookback = int(spec.params.get("lookback", 20))
            signals = momentum_scores(prices, lookback=lookback)
        if not signals:
            raise RuntimeError("信号为空：动量 lookback 过长或模型预测区间与行情无交集")

        await progress(65, "qlib: 运行模拟器")
        sim = run_simulation(
            prices=prices,
            signals=signals,
            cost=spec.cost,
            topk=spec.topk,
            start_date=spec.start_date or None,
            end_date=spec.end_date or None,
        )

        await progress(85, "qlib: 上传净值曲线与持仓明细")
        base_key = f"{spec.org_id}/backtests/{spec.backtest_id or spec.strategy_id}"
        curve_key = f"{base_key}/curve.csv"
        positions_key = f"{base_key}/positions.csv"
        if self._storage is not None:
            csv = "\n".join(f"{date},{nav:.4f}" for date, nav in sim.nav_curve)
            await self._storage.put(curve_key, csv.encode(), content_type="text/csv")
            await self._storage.put(
                positions_key,
                positions_csv(sim.positions_history).encode(),
                content_type="text/csv",
            )

        data_range = {
            "start": sim.nav_curve[0][0],
            "end": sim.nav_curve[-1][0],
            "freq": "day",
            "n_days": len(sim.nav_curve),
            "engine": self.name,
            "instruments": len(prices),
            "signal_source": spec.signal_source,
        }
        metrics = dict(sim.metrics)
        metrics["engine"] = self.name
        metrics["signal_source"] = spec.signal_source
        if spec.signal_source == "model":
            signal_note = "信号来自绑定模型的样本外预测（训练切分见训练记录，非确定性规则）"
        else:
            signal_note = "信号为动量规则（非训练模型）"
        return BacktestResult(
            metrics=metrics,
            data_range=data_range,
            cost_config=spec.cost.to_dict(),
            curve_key=curve_key,
            positions_key=positions_key if self._storage is not None else None,
            limitations=(
                f"静态费用模型（佣金/滑点/冲击成本按固定费率估算），未含融资融券、"
                f"涨跌停与停牌约束；{signal_note}；历史回测不代表未来收益。"
            ),
        )

    # ------------------------------------------------------------ 训练
    def _fetch_panel(
        self, spec: TrainSpec, reused_panel=None  # noqa: ANN001 - pd.DataFrame | None
    ) -> tuple[tuple, tuple | None, int]:
        """单次 ``qlib_online`` 上下文内取 train/valid 的因子与目标（阻塞，放线程）。

        口径（实测见 ``qlib_env.probe_dataset_via_qlib``）：``D.features`` 返回
        **index=MultiIndex(instrument, datetime)、columns=表达式列表** 的面板；
        目标用同一标的与区间取，保证与特征 index 逐行对齐。

        ``reused_panel`` 非空（阶段 6 复用模式）：X 来自 values.csv.gz 面板，按同一
        标的 + 同一 [start, end] 闭区间切片 —— 切分语义与 ``D.features`` 一致。

        切分必须由 API 层算好放进 ``spec.split``（服务层默认按数据集区间切），
        计算层不做日期推导 —— 训练快照的可复现性要求切分进 job payload。
        """
        from qqlab.worker.qlib_env import qlib_online  # noqa: PLC0415 - qlib 只在 worker 加载

        split = spec.split or {}
        train_span = split.get("train") or []
        valid_span = split.get("valid") or []
        if len(train_span) < 2:
            raise RuntimeError("训练缺少 train 区间：split.train=[start, end] 必须由 API 层提供")

        instruments = self._resolve_instruments(spec.org_id, spec.universe)
        if spec.max_instruments > 0:
            instruments = instruments[: spec.max_instruments]

        with qlib_online(self.settings, org_id=spec.org_id):
            from qlib.data import D  # noqa: PLC0415

            exprs = [f.expression for f in spec.factors]

            def _xy(start: str, end: str):  # noqa: ANN202
                # 复用模式（阶段 6）：X 来自 values.csv.gz（列名=表达式快照），目标仍走 qlib
                if reused_panel is not None:
                    X = slice_panel(reused_panel, instruments, start, end)
                else:
                    X = D.features(instruments, exprs, start_time=start, end_time=end)
                y = D.features(instruments, [spec.target], start_time=start, end_time=end)
                if X is None or X.empty:
                    raise RuntimeError(
                        f"qlib 未返回因子特征 [{start}~{end}]：确认 bootstrap 已导入数据"
                        + ("（复用面板切片为空：检查复用计算记录的股票池/区间是否覆盖本次切分）" if reused_panel is not None else "")
                    )
                return X, y

            train_pair = _xy(train_span[0], train_span[1])
            valid_pair = _xy(valid_span[0], valid_span[1]) if len(valid_span) >= 2 else None
            return train_pair, valid_pair, len(instruments)

    async def _load_reused_panel(self, spec: TrainSpec):  # noqa: ANN202
        """读因子计算落库的 values.csv.gz，拼成训练 X（复用模式）。

        列名取**因子快照表达式**（spec.factors，与 predict 路径同源）——
        LightGBM 特征名一致才不会在 predict 时报错。
        """
        import pandas as pd  # noqa: PLC0415

        if self._storage is None:  # pragma: no cover - 装配恒有 storage
            raise RuntimeError("训练复用因子值需要对象存储（storage 未装配）")
        by_factor = {str(s.get("factor_id")): s for s in (spec.factor_value_sources or [])}
        columns: dict[str, Any] = {}
        for factor in spec.factors:
            source = by_factor.get(factor.factor_id)
            if source is None or not source.get("values_uri"):
                raise RuntimeError(
                    f"复用源缺少因子 {factor.name!r}（factor_id={factor.factor_id}）："
                    "payload 快照不完整（提交期应已按版本校验）"
                )
            raw = await self._storage.get(str(source["values_uri"]))
            columns[factor.expression] = panel_from_values_csv(raw)
        # outer join（缺日为 NaN，与 D.features 的 NaN 口径一致，_fit_lgb 统一 dropna）
        return pd.concat(columns, axis=1)

    async def train(self, spec: TrainSpec, progress: ProgressCallback) -> TrainResult:
        """真实 LightGBM 训练：D.features 面板 → 对齐 → fit → joblib artifact。

        指标：``train_ic`` = 训练集 pooled Spearman；``valid_ic`` = 验证集**按日
        横截面** rank-IC 均值；``valid_ir`` = 该日度 IC 序列的 均值/标准差。

        复用模式（``spec.factor_value_sources`` 非空，阶段 6）：X 从因子计算落库的
        values.csv.gz 读取（同版本快照），目标仍实时取 qlib —— 行为差异记入
        metrics/data_range（handler 落 ``reuse_factor_values``）。
        """
        await progress(10, "qlib: 取因子与目标面板")
        reused_panel = None
        if spec.factor_value_sources:
            await progress(18, f"qlib: 读复用因子值（{len(spec.factor_value_sources)} 个计算记录）")
            reused_panel = await self._load_reused_panel(spec)
        train_pair, valid_pair, n_instruments = await asyncio.to_thread(
            self._fetch_panel, spec, reused_panel
        )

        await progress(45, "qlib: 训练 LightGBM")
        model_bytes, metrics = await asyncio.to_thread(lambda: self._fit_lgb(spec, train_pair, valid_pair))

        await progress(85, "qlib: 落模型 artifact")
        artifact_key = f"{spec.org_id}/experiments/{spec.project_id}/{spec.model_id}/model.joblib"
        # artifact 由 train handler 统一落对象存储（stub/qlib 同一口径）

        split = spec.split or {}
        data_range = {
            "train": list(split.get("train") or []),
            "valid": list(split.get("valid") or []),
            "freq": "day",
            "engine": self.name,
            "factors": [f.expression for f in spec.factors],
            "n_factors": len(spec.factors),
            "instruments": n_instruments,
        }
        metrics["engine"] = self.name
        metrics["algo"] = spec.algo
        return TrainResult(
            metrics=metrics,
            data_range=data_range,
            artifact=model_bytes,
            artifact_key=artifact_key,
            limitations=(
                "LightGBM 在历史因子上拟合次期收益，valid_ic/valid_ir 为验证集样本内统计，"
                "非未来收益承诺；未含交易成本与容量约束；因子表达式为提交时快照。"
            ),
        )

    # ------------------------------------------------------------ 因子计算（阶段 6 切片⑤）
    def _fetch_factor_panel(self, spec: FactorComputeSpec):  # noqa: ANN202
        """取单因子 + 目标面板（阻塞，调用方放进线程）。与训练 ``_fetch_panel`` 同源口径。"""
        from qqlab.worker.qlib_env import qlib_online  # noqa: PLC0415 - qlib 只在 worker 加载

        instruments = self._resolve_instruments(spec.org_id, spec.universe)
        if spec.max_instruments > 0:
            instruments = instruments[: spec.max_instruments]
        if not instruments:
            raise RuntimeError(f"股票池 {spec.universe!r} 无可用标的")

        with qlib_online(self.settings, org_id=spec.org_id):
            from qlib.data import D  # noqa: PLC0415

            X = D.features(
                instruments, [spec.expression], start_time=spec.start_date, end_time=spec.end_date
            )
            y = D.features(instruments, [spec.target], start_time=spec.start_date, end_time=spec.end_date)
            if X is None or X.empty:
                raise RuntimeError(
                    f"qlib 未返回因子面板 [{spec.start_date}~{spec.end_date}]："
                    "确认表达式合法且 bootstrap 已导入数据"
                )
            return X, y, len(instruments)

    @staticmethod
    def _factor_stats(X, y, n_instruments: int):  # noqa: ANN001, ANN202
        """覆盖率 + IC 汇总 + ic/values CSV 字节。纯 pandas 计算，可线程执行。

        IC 口径与训练**同源**（``core.ic``）：输入保持 D.features 的
        ``(instrument, date)`` MultiIndex，绝不 ``to_numpy()``（阶段 5 实机教训）。
        """
        import gzip  # noqa: PLC0415

        import numpy as np  # noqa: PLC0415

        factor = X.iloc[:, 0].replace([np.inf, -np.inf], np.nan)
        target = y.iloc[:, 0].replace([np.inf, -np.inf], np.nan)
        coverage = round(float(factor.notna().sum()) / max(int(len(factor)), 1), 6)

        pairs = daily_rank_ics(factor, target)  # [(date, ic)]，MultiIndex 保真
        summary = ic_summary([v for _, v in pairs])
        metrics = {
            **summary,
            "coverage": coverage,
            "pooled_ic": pooled_rank_ic(factor, target),
            "n_instruments": n_instruments,
        }

        ic_csv = ("date,ic\n" + "".join(f"{d},{v:.6f}\n" for d, v in pairs)).encode()

        # 因子值面板（长表 date,instrument,value）：非空值导出，超上限按面板顺序截断
        melted = factor.dropna()
        truncated = len(melted) > MAX_VALUES_ROWS
        if truncated:
            melted = melted.iloc[:MAX_VALUES_ROWS]
        lines = ["date,instrument,value"]
        for instrument, date, value in melted.rename("value").reset_index().itertuples(index=False):
            day = date.date().isoformat() if hasattr(date, "date") else str(date)
            lines.append(f"{day},{instrument},{float(value):.6f}")
        # mtime=0：gzip 头不嵌时间戳 —— 相同因子值 → 字节级一致（可复现/可比对）
        values_csv = gzip.compress(("\n".join(lines) + "\n").encode(), mtime=0)
        return metrics, ic_csv, values_csv, truncated

    async def compute_factor(
        self, spec: FactorComputeSpec, progress: ProgressCallback
    ) -> FactorComputeResult:
        """真实因子计算：D.features 面板 → 覆盖率 + 日度 rank-IC → ic.csv + values.csv.gz。"""
        await progress(10, "qlib: 取因子与目标面板")
        X, y, n_instruments = await asyncio.to_thread(self._fetch_factor_panel, spec)

        await progress(50, "qlib: 计算覆盖率与日度 rank-IC")
        metrics, ic_csv, values_csv, truncated = await asyncio.to_thread(
            self._factor_stats, X, y, n_instruments
        )

        await progress(88, "qlib: 生成 IC 与因子值对象")
        base_key = f"{spec.org_id}/factors/{spec.factor_id}/runs/{spec.run_id or spec.factor_id}"
        metrics["engine"] = self.name
        data_range = {
            "start": spec.start_date,
            "end": spec.end_date,
            "freq": "day",
            "engine": self.name,
            "expression": spec.expression,
            "version": spec.version,
            "target": spec.target,
            "n_instruments": n_instruments,
            "values_truncated": truncated,
            "values_max_rows": MAX_VALUES_ROWS,
        }
        return FactorComputeResult(
            metrics=metrics,
            data_range=data_range,
            ic_csv=ic_csv,
            values_csv=values_csv,
            ic_key=f"{base_key}/ic.csv",
            values_key=f"{base_key}/values.csv.gz",
            limitations=(
                "因子 IC 为历史区间样本内统计（因子值对次期收益的秩相关），非未来收益承诺；"
                "覆盖率=非空因子值占比；日度 IC 每日横截面样本 < 5 跳过；未含交易成本。"
                + ("因子值面板超上限已截断（见 data_range.values_truncated）。" if truncated else "")
            ),
        )

    @staticmethod
    def _pooled_ic(pred, actual) -> float:  # noqa: ANN001
        """pooled Spearman rank-IC（样本数 < 3 或常数序列时为 0）。

        阶段 6：实现抽到 ``core.ic``（与因子计算同一口径），本方法保留为薄委托
        （既有调用点与单测不变）。
        """
        return pooled_rank_ic(pred, actual)

    @staticmethod
    def _daily_ic(pred, actual) -> list[float]:  # noqa: ANN001
        """按日横截面 rank-IC 序列（输入须为**带 MultiIndex 的 Series**：末位为日期；每日样本 < 5 跳过）。

        实机回归（阶段 5）：调用点若传 ``.to_numpy()`` 会退化成 RangeIndex，
        ``groupby(level=-1)`` 变成按行分组（每组 1 行 < 5）→ daily 恒为空 →
        valid_ic 静默回退 pooled、valid_ir 恒 0（见 05-testing §4）。
        阶段 6：实现抽到 ``core.ic``（返回 (date, ic) 对），本方法取值并保持
        ``list[float]`` 兼容既有调用点与单测。
        """
        return [value for _, value in daily_rank_ics(pred, actual)]

    def _fit_lgb(self, spec: TrainSpec, train_pair, valid_pair):  # noqa: ANN001
        """拟合 LightGBM，返回 ``(joblib_bytes, metrics)``。

        与 ``predict_signals`` **同格式落/读**：``{"format_version", "model",
        "features", "target", "algo"}``（D5-6：joblib 单一格式保证 predict 一致）。
        """
        import joblib  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
        import pandas as pd  # noqa: PLC0415
        from lightgbm import LGBMRegressor  # noqa: PLC0415

        X_tr, y_tr = train_pair
        feats = list(X_tr.columns)  # D.features 列顺序 = 提交的因子顺序
        tr = X_tr.copy()
        tr["__target__"] = y_tr[y_tr.columns[0]]
        tr = tr.replace([np.inf, -np.inf], np.nan).dropna(axis=0, how="any")
        if tr.empty:
            raise RuntimeError("因子/目标对齐后无有效训练样本（全 NaN）")

        params = dict(spec.hyperparams or {})
        n_estimators = int(params.get("n_estimators", 200))
        learning_rate = float(params.get("learning_rate", 0.05))
        model = LGBMRegressor(n_estimators=n_estimators, learning_rate=learning_rate, importance_type="gain")

        va = None
        fit_kwargs = {}
        if valid_pair is not None:
            X_va, y_va = valid_pair
            va = X_va.copy()
            va["__target__"] = y_va[y_va.columns[0]]
            va = va.replace([np.inf, -np.inf], np.nan).dropna(axis=0, how="any")
            if not va.empty:
                fit_kwargs["eval_set"] = [(va.reindex(columns=feats).to_numpy(), va["__target__"].to_numpy())]
        model.fit(tr[feats].to_numpy(), tr["__target__"].to_numpy(), **fit_kwargs)

        train_pred = pd.Series(model.predict(tr[feats].to_numpy()), index=tr.index)
        train_ic = self._pooled_ic(train_pred.to_numpy(), tr["__target__"].to_numpy())

        valid_ic = 0.0
        valid_ir = 0.0
        n_valid_samples = 0
        n_valid_days = 0
        if va is not None and not va.empty:
            valid_pred = pd.Series(model.predict(va[feats].to_numpy()), index=va.index)
            # 传 Series（保留 MultiIndex）而非 to_numpy()：_daily_ic 依赖日期分组，见其 docstring
            daily = self._daily_ic(valid_pred, va["__target__"])
            if daily:
                valid_ic = sum(daily) / len(daily)
                n_valid_days = len(daily)
                mean = valid_ic
                std = (
                    (sum((v - mean) ** 2 for v in daily) / (len(daily) - 1)) ** 0.5
                    if len(daily) >= 2
                    else 0.0
                )
                valid_ir = mean / std if std > 1e-12 else 0.0
            else:
                valid_ic = self._pooled_ic(valid_pred.to_numpy(), va["__target__"].to_numpy())
            n_valid_samples = int(len(va))

        metrics = {
            "train_ic": round(train_ic, 6),
            "valid_ic": round(valid_ic, 6),
            "valid_ir": round(valid_ir, 6),
            "n_train_samples": int(len(tr)),
            "n_valid_samples": n_valid_samples,
            "n_train_days": int(tr.index.get_level_values(-1).nunique()),
            "n_valid_days": n_valid_days,
            "n_factors": len(feats),
            "lgb_n_estimators": n_estimators,
        }
        buf = io.BytesIO()
        joblib.dump(
            {
                "format_version": 1,
                "model": model,
                "features": feats,
                "target": spec.target,
                "algo": spec.algo,
            },
            buf,
        )
        return buf.getvalue(), metrics

    async def predict_signals(
        self, spec: BacktestSpec, model_artifact: bytes, progress: ProgressCallback
    ) -> SignalMap:
        """加载已训练模型，在回测区间上算因子 → 预测 → 按日横截面排序产信号。

        与动量信号同一 ``SignalMap`` 结构（date -> [(instrument, score)] 降序）。
        artifact 与 ``_fit_lgb`` 同格式（joblib bundle，format_version=1）。
        """
        await progress(20, "qlib: 加载模型并取因子")
        import joblib  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
        import pandas as pd  # noqa: PLC0415

        bundle = joblib.load(io.BytesIO(model_artifact))
        if bundle.get("format_version") != 1:
            raise RuntimeError(f"未知模型 artifact 格式：{bundle.get('format_version')!r}")
        model = bundle["model"]
        feats = bundle["features"]

        start = spec.start_date or None
        end = spec.end_date or None
        X = await asyncio.to_thread(lambda: self._fetch_expr_matrix(spec, feats, start, end))
        X = X.replace([np.inf, -np.inf], np.nan).dropna(axis=0, how="all")
        if X.empty:
            raise RuntimeError("模型信号：回测区间内因子全为空")
        pred = pd.Series(model.predict(X.to_numpy()), index=X.index)

        # 按日横截面排序：MultiIndex(instrument, datetime) -> date -> [(inst, score)]
        signals: SignalMap = {}
        for (instrument, dt), score in pred.items():
            date = str(dt)[:10]
            if score != score:  # NaN
                continue
            signals.setdefault(date, []).append((str(instrument), float(score)))
        for date in signals:
            signals[date].sort(key=lambda p: p[1], reverse=True)
        return signals

    def _fetch_expr_matrix(self, spec: BacktestSpec, exprs: list[str], start, end):  # noqa: ANN001, ANN202
        from qqlab.worker.qlib_env import qlib_online  # noqa: PLC0415

        instruments = self._resolve_instruments(spec.org_id, spec.universe)
        limit = int(spec.params.get("max_instruments") or 0) or self.settings.QLIB_DATA_SYMBOLS
        if limit > 0:
            instruments = instruments[:limit]

        with qlib_online(self.settings, org_id=spec.org_id):
            from qlib.data import D  # noqa: PLC0415

            X = D.features(instruments, exprs, start_time=start, end_time=end)
            if X is None or X.empty:
                raise RuntimeError("模型信号：qlib 未返回因子特征")
            return X

    async def healthcheck(self) -> bool:
        """探测 Qlib-Server 连通性（不依赖数据是否已导入）。"""
        from qqlab.worker.qlib_env import probe_qlib_server  # noqa: PLC0415

        ok, detail = probe_qlib_server(self.settings)
        if not ok:
            logger.warning("qlib_server_unreachable", extra={"detail": detail})
        return ok
