"""rank-IC 统计纯函数（阶段 6 切片⑤：因子计算 + IC 预览）。

从 qlib 适配器 ``_daily_ic`` / ``_pooled_ic`` 抽出，训练与因子计算**同一口径**：
- pooled rank-IC：全样本 Spearman（样本 < 3 或常数序列 → 0.0）；
- daily rank-IC：按日横截面 Spearman，每日样本 < 5 跳过（NaN 丢弃）；
- 汇总：mean / std / IR(=mean/std) / 正IC占比 / 有效天数。

实机回归教训（阶段 5，docs/stage5/05-testing §4）：调用点若传 ``.to_numpy()``
会把 MultiIndex 退化成 RangeIndex，``groupby(level=-1)`` 变成按行分组
（每组 1 行 < 5）→ daily 恒为空、valid_ir 恒 0。**输入必须是带 MultiIndex
的 Series（末位 level 为日期）**，本模块 docstring 与调用点共同约束。

pandas 在函数内延迟 import：API 进程永不触达本模块（worker 侧适配器专用）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

#: 每日横截面最小样本数（低于此值该日 IC 视为无效，跳过）
MIN_DAILY_SAMPLES = 5


def pooled_rank_ic(pred, actual) -> float:  # noqa: ANN001
    """全样本 Spearman rank-IC（样本 < 3 或常数序列 → 0.0）。"""
    import pandas as pd  # noqa: PLC0415

    if len(pred) < 3:
        return 0.0
    value = pd.Series(pred).rank().corr(pd.Series(actual).rank())
    return float(value) if value == value else 0.0


def daily_rank_ics(pred, actual) -> list[tuple[str, float]]:  # noqa: ANN001
    """按日横截面 rank-IC 序列，返回 ``[(日期ISO, ic)]``（每日样本 < MIN 跳过）。

    输入须为**带 MultiIndex 的 Series**（末位 level 为日期）—— 见模块 docstring。
    """
    import pandas as pd  # noqa: PLC0415

    frame = pd.DataFrame({"p": pred, "a": actual}).dropna()
    if frame.empty:
        return []
    ics = frame.groupby(level=-1).apply(
        lambda g: g["p"].rank().corr(g["a"].rank()) if len(g) >= MIN_DAILY_SAMPLES else float("nan")
    )
    out: list[tuple[str, float]] = []
    for label, value in ics.items():
        if value == value:  # 非 NaN
            if isinstance(label, str):
                date_s = label
            elif hasattr(label, "date"):  # pandas.Timestamp → 日期 ISO
                date_s = label.date().isoformat()
            else:
                date_s = str(label)
            out.append((date_s, float(value)))
    return out


def ic_summary(ics: Sequence[float]) -> dict[str, Any]:
    """IC 序列汇总：mean / std / ir / positive_ratio / n_days。

    IR = mean/std（std 为 0 时取 0）；positive_ratio = IC > 0 的天数占比。
    空序列 → 全 0（前端展示 0 而非 NaN，DB JSON 也不存 NaN——SQLite/PG 均会炸）。
    """
    import math  # noqa: PLC0415

    values = [float(v) for v in ics if v == v]
    n = len(values)
    if n == 0:
        return {"ic_mean": 0.0, "ic_std": 0.0, "ic_ir": 0.0, "ic_positive_ratio": 0.0, "n_days": 0}
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n  # 总体标准差（与训练口径一致）
    std = math.sqrt(var)
    positives = sum(1 for v in values if v > 0)
    return {
        "ic_mean": round(mean, 6),
        "ic_std": round(std, 6),
        # std ≤ 1e-12 视为常数序列（浮点噪声会让 [0.1,0.1,0.1] 的 var≈1e-34 → IR 爆炸）
        "ic_ir": round(mean / std, 6) if std > 1e-12 else 0.0,
        "ic_positive_ratio": round(positives / n, 6),
        "n_days": n,
    }


__all__ = ["MIN_DAILY_SAMPLES", "daily_rank_ics", "ic_summary", "pooled_rank_ic"]
