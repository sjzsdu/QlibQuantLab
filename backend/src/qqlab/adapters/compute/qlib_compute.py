"""Qlib 真实现（COMPUTE_BACKEND=qlib，**只在 worker 进程实例化**）。

职责边界：qlib 在这里只做**取数**（D.instruments / D.features 经 Qlib-Server），
交易模拟与费用计算全部走 `simulator.py`（与 stub 同一实现）——
这样成本口径不随计算后端切换而漂移。
"""

from __future__ import annotations

import asyncio
import io

from qqlab.adapters.compute.simulator import Bar, PriceSeries, momentum_scores, run_simulation
from qqlab.config import Settings
from qqlab.core.logging import get_logger
from qqlab.ports.compute import (
    BacktestResult,
    BacktestSpec,
    ProgressCallback,
    SignalMap,
    TrainResult,
    TrainSpec,
)

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

        await progress(85, "qlib: 上传净值曲线")
        curve_key = f"{spec.org_id}/backtests/{spec.backtest_id or spec.strategy_id}/curve.csv"
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
            positions_key=None,
            limitations=(
                f"静态费用模型（佣金/滑点/冲击成本按固定费率估算），未含融资融券、"
                f"涨跌停与停牌约束；{signal_note}；历史回测不代表未来收益。"
            ),
        )

    # ------------------------------------------------------------ 训练
    def _fetch_panel(self, spec: TrainSpec) -> tuple[tuple, tuple | None, int]:
        """单次 ``qlib_online`` 上下文内取 train/valid 的因子与目标（阻塞，放线程）。

        口径（实测见 ``qlib_env.probe_dataset_via_qlib``）：``D.features`` 返回
        **index=MultiIndex(instrument, datetime)、columns=表达式列表** 的面板；
        目标用同一标的与区间取，保证与特征 index 逐行对齐。

        切分必须由 API 层算好放进 ``spec.split``（服务层默认按数据集区间切），
        计算层不做日期推导 —— 训练快照的可复现性要求切分进 job payload。
        """
        from qqlab.worker.qlib_env import qlib_online  # noqa: PLC0415

        split = spec.split or {}
        train_span = split.get("train") or []
        valid_span = split.get("valid") or []
        if len(train_span) < 2:
            raise RuntimeError("训练缺少 train 区间：split.train=[start, end] 必须由 API 层提供")

        with qlib_online(self.settings, org_id=spec.org_id):
            from qlib.data import D  # noqa: PLC0415

            instruments = D.list_instruments(instruments=D.instruments("all"), as_list=True)
            if spec.max_instruments > 0:
                instruments = instruments[: spec.max_instruments]
            exprs = [f.expression for f in spec.factors]

            def _xy(start: str, end: str):  # noqa: ANN202
                X = D.features(instruments, exprs, start_time=start, end_time=end)
                y = D.features(instruments, [spec.target], start_time=start, end_time=end)
                if X is None or X.empty:
                    raise RuntimeError(f"qlib 未返回因子特征 [{start}~{end}]：确认 bootstrap 已导入数据")
                return X, y

            train_pair = _xy(train_span[0], train_span[1])
            valid_pair = _xy(valid_span[0], valid_span[1]) if len(valid_span) >= 2 else None
            return train_pair, valid_pair, len(instruments)

    async def train(self, spec: TrainSpec, progress: ProgressCallback) -> TrainResult:
        """真实 LightGBM 训练：D.features 面板 → 对齐 → fit → joblib artifact。

        指标：``train_ic`` = 训练集 pooled Spearman；``valid_ic`` = 验证集**按日
        横截面** rank-IC 均值；``valid_ir`` = 该日度 IC 序列的 均值/标准差。
        """
        await progress(10, "qlib: 取因子与目标面板")
        train_pair, valid_pair, n_instruments = await asyncio.to_thread(self._fetch_panel, spec)

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

    @staticmethod
    def _pooled_ic(pred, actual) -> float:  # noqa: ANN001
        """pooled Spearman rank-IC（样本数 < 3 或常数序列时为 0）。"""
        import pandas as pd  # noqa: PLC0415

        if len(pred) < 3:
            return 0.0
        value = pd.Series(pred).rank().corr(pd.Series(actual).rank())
        return float(value) if value == value else 0.0

    @staticmethod
    def _daily_ic(pred, actual) -> list[float]:  # noqa: ANN001
        """按日横截面 rank-IC 序列（MultiIndex 末位为日期；每日样本 < 5 跳过）。"""
        import pandas as pd  # noqa: PLC0415

        frame = pd.DataFrame({"p": pred, "a": actual}).dropna()
        if frame.empty:
            return []
        ics = frame.groupby(level=-1).apply(
            lambda g: g["p"].rank().corr(g["a"].rank()) if len(g) >= 5 else float("nan")
        )
        return [float(v) for v in ics if v == v]

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
            daily = self._daily_ic(valid_pred.to_numpy(), va["__target__"].to_numpy())
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

        with qlib_online(self.settings, org_id=spec.org_id):
            from qlib.data import D  # noqa: PLC0415

            instruments = D.list_instruments(instruments=D.instruments("all"), as_list=True)
            limit = int(spec.params.get("max_instruments") or 0) or self.settings.QLIB_DATA_SYMBOLS
            if limit > 0:
                instruments = instruments[:limit]
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
