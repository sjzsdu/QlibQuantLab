"""因子计算 handler：payload 表达式快照 → ComputePort.compute_factor → 回写计算记录。

payload（API 层 ``FactorService.submit_compute`` 固化的**执行快照**）：
``run_id / factor_id / project_id / dataset_id / expression / version /
start_date / end_date / universe / max_instruments / target``。
因子行之后再被修改（表达式 version+1）不影响本次运行。

落库口径（与训练/回测同一「四标注」，docs/stage6）：
- ``factor_compute_runs.metrics`` = coverage + IC 汇总
  （ic_mean / ic_std / ic_ir / ic_positive_ratio / n_days / pooled_ic）；
- ``factor_compute_runs.data_range`` = 区间 + 引擎 + 表达式快照 + 股票池 +
  数据来源授权（``source``）+ 局限（``limitations``）+ 对象键；
- ic/values 对象由本 handler 统一 ``storage.put``（stub/qlib 同一口径，D5-6 同源）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from qqlab.core.errors import ValidationAppError
from qqlab.core.ids import stable_uuid
from qqlab.core.logging import get_logger
from qqlab.models import Dataset
from qqlab.ports.compute import FactorComputeSpec
from qqlab.repositories.job import JobRepository
from qqlab.repositories.study import FactorComputeRunRepository
from qqlab.worker.handlers.backtest import _source_annotation, _with_universe_limitation
from qqlab.worker.handlers.base import run_job

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from qqlab.config import Settings
    from qqlab.container import Container
    from qqlab.models import Job
    from qqlab.ports.compute import ComputePort

logger = get_logger("qqlab.worker.factor_compute")


async def _execute(
    settings: Settings,
    compute: ComputePort,
    container: Container,
    job: Job,
    repo: JobRepository,
    progress,  # noqa: ANN001 - ProgressCallback
) -> dict[str, Any]:
    payload = job.payload or {}
    run_id = payload.get("run_id")
    if not run_id:
        raise ValidationAppError("factor_compute 任务缺少 run_id")

    session = repo.session
    scope = repo.scope
    run_repo = FactorComputeRunRepository(session, scope)
    run = await run_repo.get(run_id)
    if run is None:
        raise ValidationAppError(f"factor_compute_run {run_id} 不存在或不属于租户 {scope.org_id}")
    run.job_id = job.id
    dataset = (
        (
            await session.execute(
                select(Dataset).where(
                    Dataset.id == run.dataset_id,
                    Dataset.org_id == stable_uuid(scope.org_id),
                )
            )
        )
        .scalars()
        .first()
    )

    run.started_at = run.started_at or datetime.now(tz=UTC)
    await session.flush()
    await session.commit()  # started_at 先可见（任务页能看到"已开始"）

    expression = str(payload.get("expression") or "").strip()
    if not expression:
        raise ValidationAppError("因子计算快照缺少表达式（expression）")

    spec = FactorComputeSpec(
        org_id=scope.org_id,
        project_id=str(payload.get("project_id", run.project_id)),
        factor_id=str(payload.get("factor_id", run.factor_id)),
        dataset_id=str(payload.get("dataset_id", run.dataset_id)),
        expression=expression,
        version=int(payload.get("version") or 1),
        start_date=str(payload.get("start_date") or ""),
        end_date=str(payload.get("end_date") or ""),
        target=str(payload.get("target") or ""),
        max_instruments=int(payload.get("max_instruments") or 0),
        universe=str(payload.get("universe") or "all"),
        run_id=str(run_id),
    )

    result = await compute.compute_factor(spec, progress)

    await progress(92, "落 IC 序列与因子值面板到对象存储")
    await container.storage.put(result.ic_key, result.ic_csv, content_type="text/csv; charset=utf-8")
    await container.storage.put(
        result.values_key, result.values_csv, content_type="text/csv; charset=utf-8"
    )

    data_range = dict(result.data_range)
    data_range["source"] = await _source_annotation(session, scope, dataset)
    data_range["universe"] = spec.universe
    data_range["limitations"] = _with_universe_limitation(
        result.limitations, spec.universe, engine=str(result.metrics.get("engine") or "")
    )
    data_range["ic_key"] = result.ic_key
    data_range["values_key"] = result.values_key

    await session.refresh(run)  # 防 API 侧回填 job_id 竞态
    run.job_id = job.id  # 关联当前执行任务（重试后即新 job）
    run.metrics = dict(result.metrics)
    run.data_range = data_range
    run.ic_uri = result.ic_key
    run.values_uri = result.values_key
    run.finished_at = datetime.now(tz=UTC)
    await session.flush()
    await repo.append_log(
        job.id,
        f"factor_compute 完成 engine={result.metrics.get('engine')} "
        f"coverage={result.metrics.get('coverage')} ic_mean={result.metrics.get('ic_mean')} "
        f"ic_ir={result.metrics.get('ic_ir')} 有效天数={result.metrics.get('n_days')}",
    )
    logger.info(
        "factor_compute_done",
        extra={
            "factor_compute_run_id": str(run_id),
            "engine": result.metrics.get("engine"),
            "coverage": result.metrics.get("coverage"),
            "ic_mean": result.metrics.get("ic_mean"),
        },
    )
    return {
        "run_id": str(run_id),
        "factor_id": str(run.factor_id),
        "engine": result.metrics.get("engine"),
        "coverage": result.metrics.get("coverage"),
        "ic_mean": result.metrics.get("ic_mean"),
        "ic_ir": result.metrics.get("ic_ir"),
        "n_days": result.metrics.get("n_days"),
        "ic_key": result.ic_key,
        "values_key": result.values_key,
    }


def make_factor_compute_handler(settings: Settings, container: Container, compute: ComputePort):  # noqa: ANN201 - Handler 类型
    async def handle(payload: dict[str, Any]) -> dict[str, Any]:
        return await run_job(
            settings,
            container,
            payload,
            kind="factor_compute",
            execute=lambda job, repo, progress: _execute(settings, compute, container, job, repo, progress),
        )

    return handle


__all__ = ["make_factor_compute_handler"]
