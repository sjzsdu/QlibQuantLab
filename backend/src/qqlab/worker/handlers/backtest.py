"""最小回测 handler：读快照 → ComputePort 执行 → 回写结果三标注。

阶段 3 交付的是**最小闭环**：信号为纯规则（动量 topk，来自 strategy.signal_config），
模型训练在阶段 5 接入；费用假设来自 backtests.cost_config（API 层必填三件套）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from qqlab.core.errors import ValidationAppError
from qqlab.core.ids import stable_uuid
from qqlab.core.logging import get_logger
from qqlab.models import Dataset, Strategy
from qqlab.ports.compute import BacktestSpec, CostConfig
from qqlab.repositories.job import BacktestRepository, JobRepository
from qqlab.worker.handlers.base import run_job

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from qqlab.config import Settings
    from qqlab.container import Container
    from qqlab.models import Job
    from qqlab.ports.compute import ComputePort

logger = get_logger("qqlab.worker.backtest")


async def _execute(
    settings: Settings,
    compute: ComputePort,
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

    spec = BacktestSpec(
        org_id=scope.org_id,
        project_id=str(backtest.project_id),
        strategy_id=str(backtest.strategy_id),
        dataset_id=str(backtest.dataset_id),
        benchmark=backtest.benchmark,
        cost=CostConfig.from_dict(backtest.cost_config),
        topk=int(params.get("topk", 50)),
        params=params,
        start_date=start.isoformat() if start else "",
        end_date=end.isoformat() if end else "",
    )

    result = await compute.run_backtest(spec, progress)

    await brepo.save_result(
        backtest_id,
        metrics=result.metrics,
        data_range=result.data_range,
        limitations=result.limitations,
        curve_uri=result.curve_key,
        job_id=job.id,
    )
    await repo.append_log(
        job.id,
        f"backtest 完成 engine={result.metrics.get('engine')} "
        f"区间={result.data_range.get('start')}~{result.data_range.get('end')} "
        f"total_return={result.metrics.get('total_return'):.4f}",
    )
    logger.info(
        "backtest_done",
        extra={"backtest_id": str(backtest_id), "engine": result.metrics.get("engine")},
    )
    return {
        "backtest_id": str(backtest_id),
        "engine": result.metrics.get("engine"),
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
            execute=lambda job, repo, progress: _execute(settings, compute, job, repo, progress),
        )

    return handle
