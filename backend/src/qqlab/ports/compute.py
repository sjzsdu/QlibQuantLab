"""计算端口：训练 / 回测 / 因子计算的能力抽象。

只有 worker 进程会实例化实现（`adapters.compute.qlib_compute`），
API 进程永远不 import qlib —— 这是硬约束「Qlib 不进 Web 进程」的结构保证。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

#: 默认训练目标：次期收益（t+1 相对 t 的收盘收益），qlib 表达式
DEFAULT_TARGET = "Ref($close, -1) / $close - 1"


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
    #: 回测任务自己的 id：curve 对象键用它隔离（同策略多次回测不互相覆盖）。
    #: 空串（旧调用/单测直构 spec）时降级用 strategy_id。
    backtest_id: str = ""
    #: 信号来源标签："rule"（动量规则）| "model"（绑定模型的样本外预测）
    signal_source: str = "rule"
    #: 预计算信号（worker 先 ``predict_signals`` 再注入）；None = 提交方在
    #: ``run_backtest`` 内部按规则现算。metrics/data_range/limitations 会标注来源。
    signals: SignalMap | None = None
    split: dict[str, list[str]] = field(default_factory=dict)
    topk: int = 50
    params: dict[str, Any] = field(default_factory=dict)
    start_date: str = ""
    end_date: str = ""
    #: 股票池名（数据集 instruments/ 下）；"all" = 全市场（含指数代码）。
    #: 阶段 6 D6：worker 侧按此解析标的清单，非 all 为静态成分快照（见 limitations）。
    universe: str = "all"


@dataclass(slots=True)
class BacktestResult:
    metrics: dict[str, float]
    data_range: dict[str, Any]
    cost_config: dict[str, Any]
    curve_key: str
    positions_key: str | None
    limitations: str


@dataclass(slots=True)
class FactorSpec:
    """训练/预测用的单个因子（``factor_snapshot`` 的一条，含版本可复现）。"""

    factor_id: str
    name: str
    expression: str
    version: int


@dataclass(slots=True)
class TrainSpec:
    """训练输入：数据集 + 因子表达式快照 + 切分 + 超参。

    ``split``：``{"train": [start, end], "valid": [start, end], "test": [start, end]}``
    （日期 ISO 串；``test`` 可空 —— 阶段 5 只在 train/valid 上训练与选轮）。
    ``target``：qlib 表达式，预测目标（默认次期收益，见 ``DEFAULT_TARGET``）。
    """

    org_id: str
    project_id: str
    dataset_id: str
    model_id: str
    factors: list[FactorSpec]
    split: dict[str, list[str]] = field(default_factory=dict)
    algo: str = "LGBModel"
    hyperparams: dict[str, Any] = field(default_factory=dict)
    target: str = DEFAULT_TARGET
    max_instruments: int = 0  # 0 = 不截断（训练默认小 universe 由调用方给）
    #: 股票池名（数据集 instruments/ 下）；"all" = 全市场（含指数代码）
    universe: str = "all"
    #: 训练复用因子值（阶段 6）：非空时由 API 层按因子版本解析好的复用源
    #: （[{factor_id, version, run_id, values_uri, expression}]），适配器读 values.csv.gz
    #: 拼 X 而非重算表达式；None/空 = 重算（默认，行为不变）。
    factor_value_sources: list[dict[str, Any]] | None = None


@dataclass(slots=True)
class FactorComputeSpec:
    """因子计算输入（阶段 6 切片⑤）：单因子表达式快照 + 数据集 + 区间 + 股票池。

    ``target``：qlib 表达式，IC 参照的预测目标（默认次期收益，见 ``DEFAULT_TARGET``）。
    """

    org_id: str
    project_id: str
    factor_id: str
    dataset_id: str
    expression: str
    version: int = 1
    start_date: str = ""
    end_date: str = ""
    target: str = DEFAULT_TARGET
    max_instruments: int = 0  # 0 = 不截断
    #: 股票池名（数据集 instruments/ 下）；"all" = 全市场（含指数代码）
    universe: str = "all"
    #: 计算运行记录 id：ic/values 对象键用它隔离（同因子多次计算不互相覆盖）
    run_id: str = ""


@dataclass(slots=True)
class FactorComputeResult:
    metrics: dict[str, Any]
    data_range: dict[str, Any]
    #: IC 序列 CSV 字节（``date,ic``）——适配器只产字节，落对象存储由 handler 统一做
    ic_csv: bytes
    #: 因子值面板 CSV 字节（``date,instrument,value``）
    values_csv: bytes
    ic_key: str
    values_key: str
    limitations: str


@dataclass(slots=True)
class TrainResult:
    metrics: dict[str, Any]
    data_range: dict[str, Any]
    #: 模型权重的 joblib 字节（``train`` 落对象存储，``predict`` 直接反序列化）
    artifact: bytes
    artifact_key: str
    limitations: str


ProgressCallback = Callable[[int, str], Awaitable[None]]

#: date -> [(instrument, score)]（score 降序，由调用方排好）
SignalMap = dict[str, list[tuple[str, float]]]


@runtime_checkable
class ComputePort(Protocol):
    """worker 侧的计算能力。API 进程通过 jobs 间接使用，不直接调用。"""

    name: str  # "qlib" | "stub"

    async def run_backtest(self, spec: BacktestSpec, progress: ProgressCallback) -> BacktestResult: ...

    async def train(self, spec: TrainSpec, progress: ProgressCallback) -> TrainResult: ...

    async def compute_factor(self, spec: FactorComputeSpec, progress: ProgressCallback) -> FactorComputeResult: ...

    async def predict_signals(
        self, spec: BacktestSpec, model_artifact: bytes, progress: ProgressCallback
    ) -> SignalMap: ...

    async def healthcheck(self) -> bool: ...
