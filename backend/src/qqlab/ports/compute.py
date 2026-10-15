"""计算端口：训练 / 回测 / 因子计算的能力抽象。

只有 worker 进程会实例化实现（`adapters.compute.qlib_compute`），
API 进程永远不 import qlib —— 这是硬约束「Qlib 不进 Web 进程」的结构保证。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True)
class CostConfig:
    """回测费用假设。三件套必填，API 层校验，报告页脚回显。

    ``from_dict`` 兼容两种存储形态：``to_dict()`` 的嵌套形态，以及
    API 直传的扁平形态（slippage_value / impact_rate_per_million 顶层键）。
    """

    commission_rate: float = 0.0005
    min_commission: float = 5.0
    slippage_type: str = "fixed_bp"
    slippage_value: float = 10.0
    impact_rate_per_million: float = 0.0001
    settlement_fee_rate: float = 0.00002
    stamp_duty_sell: float = 0.0005

    def to_dict(self) -> dict[str, Any]:
        return {
            "commission_rate": self.commission_rate,
            "min_commission": self.min_commission,
            "slippage": {"type": self.slippage_type, "value": self.slippage_value},
            "impact_cost": {"type": "linear", "rate_per_million": self.impact_rate_per_million},
            "settlement_fee": self.settlement_fee_rate,
            "stamp_duty_sell": self.stamp_duty_sell,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CostConfig:
        data = dict(data or {})
        slippage = data.get("slippage") or {}
        impact = data.get("impact_cost") or {}
        defaults = cls()
        return cls(
            commission_rate=float(data.get("commission_rate", defaults.commission_rate)),
            min_commission=float(data.get("min_commission", defaults.min_commission)),
            slippage_type=str(slippage.get("type", data.get("slippage_type", defaults.slippage_type))),
            slippage_value=float(slippage.get("value", data.get("slippage_value", defaults.slippage_value))),
            impact_rate_per_million=float(
                impact.get(
                    "rate_per_million", data.get("impact_rate_per_million", defaults.impact_rate_per_million)
                )
            ),
            settlement_fee_rate=float(
                data.get("settlement_fee", data.get("settlement_fee_rate", defaults.settlement_fee_rate))
            ),
            stamp_duty_sell=float(data.get("stamp_duty_sell", defaults.stamp_duty_sell)),
        )


@dataclass(slots=True)
class BacktestSpec:
    org_id: str
    project_id: str
    strategy_id: str
    dataset_id: str
    benchmark: str
    cost: CostConfig
    split: dict[str, list[str]] = field(default_factory=dict)
    topk: int = 50
    params: dict[str, Any] = field(default_factory=dict)
    start_date: str = ""
    end_date: str = ""


@dataclass(slots=True)
class BacktestResult:
    metrics: dict[str, float]
    data_range: dict[str, Any]
    cost_config: dict[str, Any]
    curve_key: str
    positions_key: str | None
    limitations: str


ProgressCallback = Callable[[int, str], Awaitable[None]]


@runtime_checkable
class ComputePort(Protocol):
    """worker 侧的计算能力。API 进程通过 jobs 间接使用，不直接调用。"""

    name: str  # "qlib" | "stub"

    async def run_backtest(self, spec: BacktestSpec, progress: ProgressCallback) -> BacktestResult: ...

    async def healthcheck(self) -> bool: ...
