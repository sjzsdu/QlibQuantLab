"""最小日频回测模拟器（**纯标准库**，stub 与 qlib 两条链路共用）。

硬约束（docs/stage1/06-qlib-integration.md §4）：
- 费用模型 100% 由 ``CostConfig`` 显式驱动 —— 不使用任何「qlib 默认值」兜底；
- 信号在 t 日收盘生成 → t+1 日开盘成交，杜绝前视偏差；
- 回测结果必须回显 ``cost_config`` 副本（``metrics["cost_applied"]``）。

因为只用标准库，成本口径在 ``COMPUTE_BACKEND=qlib|stub`` 下完全一致；
qlib 在本模块之外只负责**取数**，不参与任何交易/费用计算。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from qqlab.ports.compute import CostConfig

#: 年化因子：A 股日频
TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True, slots=True)
class Bar:
    """单标的单日行情（来自 qlib features 或 stub 合成）。"""

    date: str  # YYYY-MM-DD
    open: float
    close: float
    volume: float = 0.0


#: instrument -> [Bar]（按 date 升序）
PriceSeries = dict[str, list[Bar]]
#: date -> [(instrument, score)]（score 降序，由调用方排好）
SignalMap = dict[str, list[tuple[str, float]]]


@dataclass(slots=True)
class SimulationResult:
    nav_curve: list[tuple[str, float]] = field(default_factory=list)
    final_positions: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    cost_breakdown: dict[str, float] = field(default_factory=dict)
    trade_count: int = 0
    turnover_history: list[float] = field(default_factory=list)


def momentum_scores(prices: PriceSeries, *, lookback: int = 20) -> SignalMap:
    """动量打分：close[t] / close[t-lookback] - 1，逐交易日输出全标的排名分。

    阶段 3 的「最小回测信号」（纯规则，不含训练模型；模型训练在阶段 5）。
    数据不足 lookback 的标的不参与当日排名。
    """
    closes_by_date: dict[str, dict[str, float]] = {}
    for instrument, bars in prices.items():
        for bar in bars:
            closes_by_date.setdefault(bar.date, {})[instrument] = bar.close

    scores: SignalMap = {}
    for date in sorted(closes_by_date):
        closes = closes_by_date[date]
        dated = sorted(d for d in closes_by_date if d < date)
        if len(dated) < lookback:
            continue
        base_date = dated[-lookback]
        base = closes_by_date[base_date]
        day_scores: list[tuple[str, float]] = [
            (inst, closes[inst] / base[inst] - 1.0)
            for inst, close in closes.items()
            if inst in base and base[inst] > 0 and close > 0
        ]
        if day_scores:
            day_scores.sort(key=lambda pair: pair[1], reverse=True)
            scores[date] = day_scores
    return scores


def _fee_detail(amount: float, cost: CostConfig, *, is_sell: bool) -> dict[str, float]:
    """一笔成交的费用拆解（amount = 成交金额，不含费用）。

    冲击成本口径 = ``docs/stage1/06-qlib-integration.md`` §4 的权威公式：
    ``impact = rate_per_million × 成交额``（不再做 /1e6 缩放，阶段 3 实测核对后固化）。
    """
    commission = max(amount * cost.commission_rate, cost.min_commission)
    stamp = amount * cost.stamp_duty_sell if is_sell else 0.0
    settlement = amount * cost.settlement_fee_rate
    impact = amount * cost.impact_rate_per_million
    return {
        "commission": commission,
        "stamp_duty": stamp,
        "settlement": settlement,
        "impact": impact,
    }


def run_simulation(
    *,
    prices: PriceSeries,
    signals: SignalMap,
    cost: CostConfig,
    topk: int = 50,
    initial_cash: float = 1_000_000.0,
    start_date: str | None = None,
    end_date: str | None = None,
) -> SimulationResult:
    """等权 topk、日频调仓、次日开盘成交的日频模拟（**目标市值 delta 模型**）。

    - t 日收盘生成目标市值字典：新 topk 等权 + 被剔除持仓目标 0；
    - t+1 日开盘按 ``delta = 目标市值 - 持仓市值`` 执行，**先卖后买**（卖出释放现金）；
    - 成交价 = 开盘 ± 滑点（买加滑点、卖减滑点，``fixed_bp`` 单位 bp）；
    - 费用（佣金/印花税/过户费/冲击成本）按**成交后金额**从现金扣除；
    - 买入现金不足时等比缩放当日买入。
    """
    if topk < 1:
        raise ValueError("topk 必须 >= 1")

    # 交易日历 = 有行情的日期并集（升序，受 start/end 截断）
    calendar = sorted({bar.date for bars in prices.values() for bar in bars})
    if start_date:
        calendar = [d for d in calendar if d >= start_date]
    if end_date:
        calendar = [d for d in calendar if d <= end_date]
    if not calendar:
        raise ValueError("没有可用的行情日期（检查数据区间或 start/end 过滤）")

    by_date: dict[str, dict[str, Bar]] = {}
    for instrument, bars in prices.items():
        for bar in bars:
            by_date.setdefault(bar.date, {})[instrument] = bar

    cash = initial_cash
    holdings: dict[str, float] = {}  # instrument -> shares
    pending: dict[str, float] = {}  # instrument -> 目标市值（含被剔除持仓的 0 目标），次日开盘执行

    nav_curve: list[tuple[str, float]] = []
    turnover_history: list[float] = []
    trade_count = 0
    fees_total = {"commission": 0.0, "stamp_duty": 0.0, "settlement": 0.0, "impact": 0.0}
    slippage_total = 0.0

    slippage_frac = cost.slippage_value / 10_000.0 if cost.slippage_type == "fixed_bp" else 0.0

    for date in calendar:
        today = by_date.get(date, {})

        # ---- 1) 执行昨日收盘生成的目标市值 delta（今日开盘 ± 滑点，先卖后买） ----
        if pending:
            # 每个待调仓标的的执行参考价（今日开盘）；无开盘数据的顺延为现金
            exec_prices: dict[str, float] = {
                inst: today[inst].open for inst in pending if inst in today and today[inst].open > 0
            }
            if exec_prices:
                nav_before = cash + sum(
                    holdings.get(i, 0.0) * today[i].close
                    for i in holdings
                    if i in today and today[i].close > 0
                )
                # delta = 目标市值 - 当前持仓市值（开盘计价）；负 = 卖出，正 = 买入
                deltas = [
                    (inst, pending[inst] - holdings.get(inst, 0.0) * exec_prices[inst])
                    for inst in exec_prices
                ]
                sells = [(i, -d) for i, d in deltas if d < -1e-9]
                buys = [(i, d) for i, d in deltas if d > 1e-9]

                traded_value = 0.0
                for instrument, sell_value in sells:
                    exec_price = exec_prices[instrument] * (1.0 - slippage_frac)
                    # 卖出量不超过实际持仓（目标 0 时清仓）
                    value = min(sell_value, holdings.get(instrument, 0.0) * exec_price)
                    if value <= 0:
                        continue
                    fees = _fee_detail(value, cost, is_sell=True)
                    for key, amount in fees.items():
                        fees_total[key] += amount
                    slippage_total += value * slippage_frac
                    cash += value - sum(fees.values())
                    holdings[instrument] = holdings.get(instrument, 0.0) - value / exec_price
                    trade_count += 1
                    traded_value += value

                # 买入：按目标 delta，现金不足时等比缩放（费用从现金扣除）
                total_buy = sum(v for _, v in buys)
                scale = 1.0
                if total_buy > cash > 0 and total_buy > 0:
                    scale = cash / total_buy
                elif cash <= 0:
                    scale = 0.0
                for instrument, delta_value in buys:
                    budget = delta_value * scale
                    if budget <= 0:
                        continue
                    exec_price = exec_prices[instrument] * (1.0 + slippage_frac)
                    # 名义金额与实际支出（含费用）分列，避免费用漏算
                    nominal = budget / (1.0 + slippage_frac) if slippage_frac else budget
                    fees = _fee_detail(nominal, cost, is_sell=False)
                    spend = nominal + slippage_frac * nominal + sum(fees.values())
                    if spend <= 0:
                        continue
                    holdings[instrument] = holdings.get(instrument, 0.0) + nominal / exec_price
                    cash -= spend
                    for key, amount in fees.items():
                        fees_total[key] += amount
                    slippage_total += nominal * slippage_frac
                    trade_count += 1
                    traded_value += nominal

                turnover_history.append(traded_value / nav_before if nav_before > 0 else 0.0)
            pending = {}

        # ---- 2) 收盘盯市 ----
        nav = cash + sum(
            holdings.get(i, 0.0) * today[i].close for i in holdings if i in today and today[i].close > 0
        )
        if nav <= 0:
            # 破产底线（有限债务约定）：净值不可能为负。min_commission 是**绝对**费用下限，
            # 净值衰减到极小时一笔迷你卖出的佣金就能把现金打穿（阶段 3 实测：21 年噪声
            # 动量 + 真实费用 → NAV = -5.28 → _metrics 对负底数取分数幂得到 complex →
            # JSONB 落库 TypeError → 任务终态丢失）。清零持仓与现金，亏损封顶 -100%，
            # 此后净值恒 0（现金为 0 时买入缩放为 0，不再产生成交）。
            cash = 0.0
            holdings.clear()
            nav = 0.0
        nav_curve.append((date, nav))

        # ---- 3) 收盘生成次日目标市值（t 日信号 → t+1 日开盘成交） ----
        day_signals = signals.get(date)
        if day_signals:
            ranked = [inst for inst, _ in day_signals if inst in by_date.get(date, {}) or inst in prices][
                :topk
            ]
            if ranked:
                per_slot = nav / len(ranked)
                targets = {instrument: per_slot for instrument in ranked}
                # 被剔除出 topk 的持仓目标市值 = 0 → 次日清仓卖出
                for instrument, shares in holdings.items():
                    if shares > 0 and instrument not in targets:
                        targets[instrument] = 0.0
                pending = targets

    if not nav_curve:
        raise ValueError("模拟未产生任何净值点（信号与行情日期无交集）")

    metrics = _metrics(nav_curve, initial_cash)
    metrics["trade_count"] = float(trade_count)
    metrics["total_cost"] = sum(fees_total.values()) + slippage_total
    metrics["avg_turnover"] = sum(turnover_history) / len(turnover_history) if turnover_history else 0.0
    # 硬约束：结果必须回显费用假设副本
    metrics["cost_applied"] = cost.to_dict()  # type: ignore[assignment]

    final_positions = {
        instrument: shares for instrument, shares in sorted(holdings.items()) if abs(shares) > 1e-9
    }
    return SimulationResult(
        nav_curve=nav_curve,
        final_positions=final_positions,
        metrics=metrics,
        cost_breakdown={**fees_total, "slippage": slippage_total},
        trade_count=trade_count,
        turnover_history=turnover_history,
    )


def _metrics(nav_curve: list[tuple[str, float]], initial_cash: float) -> dict[str, float]:
    navs = [nav for _, nav in nav_curve]
    total_return = navs[-1] / initial_cash - 1.0
    n = len(navs)
    # 防 complex 兜底：净值 ≤ 0（破产）时年化收益封顶 -100%。负底数的分数幂在 Python
    # 里返回 complex（阶段 3 实测），complex 无法写 JSONB —— run_simulation 的 0 净值
    # 底线已挡住负净值，这里再兜一层防止未来改动引入绕过路径。
    if total_return <= -1.0:
        annualized = -1.0
    else:
        annualized = (1.0 + total_return) ** (TRADING_DAYS_PER_YEAR / n) - 1.0 if n > 0 else 0.0

    daily_ret = [navs[i] / navs[i - 1] - 1.0 for i in range(1, n) if navs[i - 1] > 0]
    if len(daily_ret) >= 2:
        mean = sum(daily_ret) / len(daily_ret)
        var = sum((r - mean) ** 2 for r in daily_ret) / (len(daily_ret) - 1)
        std = math.sqrt(var)
        sharpe = mean / std * math.sqrt(TRADING_DAYS_PER_YEAR) if std > 0 else 0.0
    else:
        sharpe = 0.0

    peak = navs[0]
    max_drawdown = 0.0
    for nav in navs:
        peak = max(peak, nav)
        if peak > 0:
            max_drawdown = min(max_drawdown, nav / peak - 1.0)

    calmar = annualized / abs(max_drawdown) if max_drawdown < 0 else 0.0
    return {
        "total_return": total_return,
        "annualized_return": annualized,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
    }
