"""回测 handler：读快照 → 信号（rule | model）→ ComputePort 执行 → 回写四标注。

阶段 5（docs/stage5）：
- **双信号源**（D5-0b）：``strategy.signal_config.source = rule | model``；
  model 源取该模型**最近一次产出 artifact 的成功训练**（latest_succeeded），
  ``predict_signals`` 后注入 ``spec.signals``，与规则信号走同一模拟器；
- **curve 键按 backtest_id 隔离**：同策略多次回测不互相覆盖；
- **四标注**：``data_range``（区间/引擎/信号来源/标的数）+ ``cost_config``
  （100% 透传）+ ``limitations`` + ``data_range.source``（数据集 → 数据源 vendor
  → 授权台账 license_ref，可追溯但不含行情数据本身）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from qqlab.core.errors import ValidationAppError
from qqlab.core.ids import stable_uuid
from qqlab.core.logging import get_logger
from qqlab.models import DataLicense, Dataset, DataSource, Strategy
from qqlab.ports.compute import BacktestSpec, CostConfig
from qqlab.repositories.job import BacktestRepository, JobRepository
from qqlab.repositories.study import TrainingRunRepository
from qqlab.worker.handlers.base import run_job

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from qqlab.config import Settings
    from qqlab.container import Container
    from qqlab.models import Job
    from qqlab.ports.compute import ComputePort

logger = get_logger("qqlab.worker.backtest")

#: 非 all 股票池时追加的局限说明（stub 引擎合成行情不按股票池过滤，如实标注）
_UNIVERSE_LIMITATION = "股票池 {name} 为静态成分快照（START/END 分段区间不参与时点过滤，非时点化成分）"


def _with_universe_limitation(limitations: str, universe: str, engine: str = "") -> str:
    """把股票池局限并进 limitations（阶段 6 D6：非 all 时必须显式声明）。"""
    if universe in ("", "all"):
        return limitations
    if engine == "stub":
        note = f"股票池 {universe} 仅作标注：stub 合成行情不按股票池过滤标的"
    else:
        note = _UNIVERSE_LIMITATION.format(name=universe)
    return f"{limitations} {note}" if limitations else note


async def _source_annotation(session, scope, dataset: Dataset | None) -> dict[str, Any]:  # noqa: ANN001
    """数据来源/授权四标注第 4 项：数据集 → 数据源 → 授权台账（同租户过滤）。"""
    if dataset is None:
        return {}
    org_uuid = stable_uuid(scope.org_id)
    source = (
        (
            await session.execute(
                select(DataSource).where(
                    DataSource.id == dataset.data_source_id, DataSource.org_id == org_uuid
                )
            )
        )
        .scalars()
        .first()
    )
    license_row = (
        (
            await session.execute(
                select(DataLicense).where(
                    DataLicense.id == dataset.license_id, DataLicense.org_id == org_uuid
                )
            )
        )
        .scalars()
        .first()
    )
    return {
        "dataset_id": str(dataset.id),
        "dataset_name": dataset.name,
        "data_source_id": str(dataset.data_source_id),
        "vendor": source.vendor if source else None,
        "license_ref": license_row.license_ref if license_row else None,
        "allowed_use": license_row.allowed_use if license_row else None,
        "redistribution_allowed": license_row.redistribution_allowed if license_row else None,
    }


async def _execute(
    settings: Settings,
    compute: ComputePort,
    container: Container,
    job: Job,
    repo: JobRepository,
    progress,  # noqa: ANN001 - ProgressCallback
) -> dict[str, Any]:
    backtest_id = (job.payload or {}).get("backtest_id")
    if not backtest_id:
        raise ValidationAppError("backtest 任务缺少 backtest_id")

    session = repo.session
    scope = repo.scope
    brepo = BacktestRepository(session, scope)

    backtest = await brepo.get(backtest_id)
    if backtest is None:
        raise ValidationAppError(f"backtest {backtest_id} 不存在或不属于租户 {scope.org_id}")

    strategy = (
        (
            await session.execute(
                select(Strategy).where(
                    Strategy.id == backtest.strategy_id,
                    Strategy.org_id == stable_uuid(scope.org_id),
                )
            )
        )
        .scalars()
        .first()
    )
    if strategy is None:
        raise ValidationAppError(f"strategy {backtest.strategy_id} 不存在（租户过滤后）")

    dataset = (
        (
            await session.execute(
                select(Dataset).where(
                    Dataset.id == backtest.dataset_id,
                    Dataset.org_id == stable_uuid(scope.org_id),
                )
            )
        )
        .scalars()
        .first()
    )

    # 信号参数快照：strategy.signal_config（提交时快照）与本次 backtests.params 合并
    params: dict[str, Any] = {**(strategy.signal_config or {}), **(backtest.params or {})}
    start = backtest.start_date or (dataset.start_date if dataset else None)
    end = backtest.end_date or (dataset.end_date if dataset else None)
    signal_source = str(params.get("source", "rule"))
    if signal_source not in ("rule", "model"):
        raise ValidationAppError(f"未知信号源 {signal_source!r}（strategy.signal_config.source）")

    spec = BacktestSpec(
        org_id=scope.org_id,
        project_id=str(backtest.project_id),
        strategy_id=str(backtest.strategy_id),
        dataset_id=str(backtest.dataset_id),
        benchmark=backtest.benchmark,
        cost=CostConfig.from_dict(backtest.cost_config),
        backtest_id=str(backtest_id),
        signal_source=signal_source,
        topk=int(params.get("topk", 50)),
        params=params,
        start_date=start.isoformat() if start else "",
        end_date=end.isoformat() if end else "",
        universe=str(params.get("universe") or "all"),
    )

    training_run_id: str | None = None
    if signal_source == "model":
        if not strategy.model_id:
            raise ValidationAppError("策略为模型信号但未绑定 model_id")
        run = await TrainingRunRepository(session, scope).latest_succeeded(str(strategy.model_id))
        if run is None or not run.artifact_uri:
            raise ValidationAppError(
                f"模型 {strategy.model_id} 尚无产出 artifact 的成功训练记录——请先完成训练"
            )
        await progress(5, "加载模型 artifact 并预测信号")
        artifact = await container.storage.get(run.artifact_uri)
        spec.signals = await compute.predict_signals(spec, artifact, progress)
        training_run_id = str(run.id)
        params["training_run_id"] = training_run_id

    result = await compute.run_backtest(spec, progress)

    # 四标注：data_range 里再挂数据来源/授权（第 4 项），训练版本（模型信号时）
    data_range = dict(result.data_range)
    data_range["source"] = await _source_annotation(session, scope, dataset)
    data_range["topk"] = spec.topk
    data_range["universe"] = spec.universe
    if training_run_id:
        data_range["training_run_id"] = training_run_id
        data_range["model_id"] = str(strategy.model_id)

    await brepo.save_result(
        backtest_id,
        metrics=result.metrics,
        data_range=data_range,
        limitations=_with_universe_limitation(
            result.limitations, spec.universe, engine=str(result.metrics.get("engine") or "")
        ),
        curve_uri=result.curve_key,
        positions_uri=result.positions_key,
        job_id=job.id,
    )
    await repo.append_log(
        job.id,
        f"backtest 完成 engine={result.metrics.get('engine')} "
        f"signal={signal_source} "
        f"区间={result.data_range.get('start')}~{result.data_range.get('end')} "
        f"total_return={result.metrics.get('total_return'):.4f}",
    )
    logger.info(
        "backtest_done",
        extra={
            "backtest_id": str(backtest_id),
            "engine": result.metrics.get("engine"),
            "signal_source": signal_source,
        },
    )
    return {
        "backtest_id": str(backtest_id),
        "engine": result.metrics.get("engine"),
        "signal_source": signal_source,
        "total_return": result.metrics.get("total_return"),
        "sharpe": result.metrics.get("sharpe"),
        "max_drawdown": result.metrics.get("max_drawdown"),
        "curve_key": result.curve_key,
        "cost_applied": result.metrics.get("cost_applied"),
    }


def make_backtest_handler(settings: Settings, container: Container, compute: ComputePort):  # noqa: ANN201 - Handler 类型
    async def handle(payload: dict[str, Any]) -> dict[str, Any]:
        return await run_job(
            settings,
            container,
            payload,
            kind="backtest",
            execute=lambda job, repo, progress: _execute(settings, compute, container, job, repo, progress),
        )

    return handle
