"""训练 handler：payload 执行快照 → ComputePort.train → artifact 落对象存储 → 回写训练记录。

payload（API 层 ``ModelService.submit_train`` 固化的**执行快照**，模型行之后再被
修改不影响本次运行）：``training_run_id / model_id / dataset_id / project_id /
algo / hyperparams / target / factors（factor_snapshot） / split / max_instruments``。

落库口径（docs/stage5，四标注同回测）：
- ``training_runs.metrics`` = 训练指标（train_ic / valid_ic / valid_ir / 样本数…）；
- ``training_runs.data_range`` = 切分区间 + 引擎 + 因子表达式 + **数据来源授权**
  （``source`` 键）+ ``limitations``（训练结果无独立 limitations 列，存 data_range，
  避免新迁移——决策见 docs/stage5）；
- artifact 由本 handler 统一 ``storage.put``（stub/qlib 同一口径，D5-6）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from qqlab.core.errors import ValidationAppError
from qqlab.core.ids import stable_uuid
from qqlab.core.logging import get_logger
from qqlab.models import Dataset
from qqlab.ports.compute import FactorSpec, TrainSpec
from qqlab.repositories.job import JobRepository
from qqlab.repositories.study import ModelRepository, TrainingRunRepository
from qqlab.worker.handlers.backtest import _source_annotation
from qqlab.worker.handlers.base import run_job

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from qqlab.config import Settings
    from qqlab.container import Container
    from qqlab.models import Job
    from qqlab.ports.compute import ComputePort

logger = get_logger("qqlab.worker.train")


async def _execute(
    settings: Settings,
    compute: ComputePort,
    container: Container,
    job: Job,
    repo: JobRepository,
    progress,  # noqa: ANN001 - ProgressCallback
) -> dict[str, Any]:
    payload = job.payload or {}
    run_id = payload.get("training_run_id")
    if not run_id:
        raise ValidationAppError("train 任务缺少 training_run_id")

    session = repo.session
    scope = repo.scope
    run_repo = TrainingRunRepository(session, scope)
    run = await run_repo.get(run_id)
    if run is None:
        raise ValidationAppError(f"training_run {run_id} 不存在或不属于租户 {scope.org_id}")
    run.job_id = run.job_id or job.id  # 入队竞态兜底（API 侧 job_id 回填还没提交）
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

    factors = [
        FactorSpec(
            factor_id=str(f.get("factor_id", "")),
            name=str(f.get("name", "")),
            expression=str(f.get("expression", "")),
            version=int(f.get("version", 1)),
        )
        for f in (payload.get("factors") or [])
    ]
    if not factors:
        raise ValidationAppError("训练快照缺少因子列表（factors）——模型 factor_snapshot 为空")

    spec = TrainSpec(
        org_id=scope.org_id,
        project_id=str(payload.get("project_id", run.project_id)),
        dataset_id=str(payload.get("dataset_id", run.dataset_id)),
        model_id=str(payload.get("model_id", run.model_id)),
        factors=factors,
        split=dict(payload.get("split") or {}),
        algo=str(payload.get("algo", "lgb")),
        hyperparams=dict(payload.get("hyperparams") or {}),
        target=str(payload.get("target") or ""),
        max_instruments=int(payload.get("max_instruments") or 0),
    )

    result = await compute.train(spec, progress)

    await progress(92, "落模型 artifact 到对象存储")
    await container.storage.put(result.artifact_key, result.artifact, content_type="application/octet-stream")

    data_range = dict(result.data_range)
    data_range["source"] = await _source_annotation(session, scope, dataset)
    data_range["limitations"] = result.limitations
    data_range["artifact_key"] = result.artifact_key

    await session.refresh(run)  # 训练期间 worker 自己也写过（无）；防 API 侧回填 job_id 竞态
    run.job_id = run.job_id or job.id
    run.metrics = dict(result.metrics)
    run.data_range = data_range
    run.artifact_uri = result.artifact_key
    run.finished_at = datetime.now(tz=UTC)

    # 模型状态 draft/training/failed → trained（模型行可能已被删：跳过）
    model = await ModelRepository(session, scope).get(str(run.model_id))
    if model is not None:
        model.status = "trained"
    await session.flush()
    await repo.append_log(
        job.id,
        f"train 完成 algo={spec.algo} engine={result.metrics.get('engine')} "
        f"valid_ic={result.metrics.get('valid_ic')} "
        f"样本={result.metrics.get('n_train_samples')}",
    )
    logger.info(
        "train_done",
        extra={
            "training_run_id": str(run_id),
            "engine": result.metrics.get("engine"),
            "valid_ic": result.metrics.get("valid_ic"),
        },
    )
    return {
        "training_run_id": str(run_id),
        "model_id": str(run.model_id),
        "engine": result.metrics.get("engine"),
        "train_ic": result.metrics.get("train_ic"),
        "valid_ic": result.metrics.get("valid_ic"),
        "valid_ir": result.metrics.get("valid_ir"),
        "artifact_key": result.artifact_key,
    }


def make_train_handler(settings: Settings, container: Container, compute: ComputePort):  # noqa: ANN201 - Handler 类型
    async def handle(payload: dict[str, Any]) -> dict[str, Any]:
        return await run_job(
            settings,
            container,
            payload,
            kind="train",
            execute=lambda job, repo, progress: _execute(settings, compute, container, job, repo, progress),
        )

    return handle


__all__ = ["make_train_handler"]
