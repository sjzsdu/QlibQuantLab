"""模型服务：创建（因子快照）/ 改参 / 删除 + 提交训练任务（阶段 5）。

- 创建时收 ``factor_ids`` 引用因子库，**创建瞬间快照**表达式进 ``factor_snapshot``，
  后续因子修改不影响已建模型（可复现性，衔接点 #3 的落定口径）；
- 训练切分：调用方不传时按数据集区间做 70/30 默认切分，切分随 job payload 固化；
- 提交顺序：run 行先落库（commit-before-publish 的延伸）→ 入队 → 回填 job_id →
  提交；入队失败时补偿删除 run 行，避免孤儿记录；
- 所有写路径显式 ``commit``（D4-8 read-your-writes）。
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from qqlab.core.errors import (
    ConfirmationRequiredError,
    ConflictError,
    NotFoundError,
    ValidationAppError,
)
from qqlab.core.ids import stable_uuid
from qqlab.core.tenant import OrgScope
from qqlab.models import Job, MLModel, TrainingRun
from qqlab.ports.audit import AuditAction, AuditWriter
from qqlab.ports.auth import CurrentUser
from qqlab.ports.compute import DEFAULT_TARGET
from qqlab.repositories import (
    DatasetRepository,
    FactorRepository,
    JobRepository,
    ModelRepository,
    ProjectRepository,
    StrategyRepository,
    TrainingRunRepository,
)
from qqlab.schemas import (
    ModelCreateIn,
    ModelOut,
    ModelUpdateIn,
    PageOut,
    TrainingRunBrief,
    TrainingRunOut,
    TrainSubmitIn,
)
from qqlab.services.base import AuditContext

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from qqlab.ports.storage import StorageProvider
    from qqlab.services.job_service import JobService

#: 阶段 5 训练算法目录（与 GET /models/catalog 同源；D5-0a 仅 LightGBM）
TRAIN_ALGOS: dict[str, str] = {"lgb": "LightGBM 梯度提升树"}

#: 默认切分所需的最小数据跨度（天）
MIN_SPLIT_SPAN_DAYS = 60


def default_split(start: date, end: date) -> dict[str, list[str]]:
    """数据集区间 → 70/30 切分（train 前段、valid 后段，不重叠）。"""
    span = (end - start).days
    if span < MIN_SPLIT_SPAN_DAYS:
        raise ValidationAppError(
            f"数据区间仅 {span} 天（<{MIN_SPLIT_SPAN_DAYS}），无法默认切分——请显式传 split"
        )
    cut = start + timedelta(days=int(span * 0.7) - 1)
    return {
        "train": [start.isoformat(), cut.isoformat()],
        "valid": [(cut + timedelta(days=1)).isoformat(), end.isoformat()],
    }


class ModelService:
    def __init__(
        self,
        *,
        session,  # noqa: ANN001 - AsyncSession
        scope: OrgScope,
        user: CurrentUser,
        audit: AuditWriter,
        ctx: AuditContext,
        storage: StorageProvider | None = None,
    ) -> None:
        self._session = session
        self._scope = scope
        self._user = user
        self._audit = audit
        self._ctx = ctx
        self._storage = storage

    # ------------------------------------------------------------- 序列化
    async def _job_status(self, job_id: uuid.UUID | None) -> str | None:
        if job_id is None:
            return None
        row = await self._session.execute(
            select(Job.status).where(Job.id == job_id, Job.org_id == stable_uuid(self._scope.org_id))
        )
        value = row.scalar_one_or_none()
        return str(value) if value else None

    async def _run_brief(self, run: TrainingRun | None) -> TrainingRunBrief | None:
        if run is None:
            return None
        return TrainingRunBrief(
            id=str(run.id),
            job_id=str(run.job_id) if run.job_id else None,
            job_status=await self._job_status(run.job_id),
            created_at=run.created_at,
            finished_at=run.finished_at,
        )

    async def _out(self, row: MLModel) -> ModelOut:
        project = await ProjectRepository(self._session, self._scope).get(str(row.project_id))
        dataset = await DatasetRepository(self._session, self._scope).get(str(row.dataset_id))
        names = await ModelRepository(self._session, self._scope).usernames([row.created_by])
        last_run = await TrainingRunRepository(self._session, self._scope).latest(str(row.id))
        return ModelOut(
            id=str(row.id),
            project_id=str(row.project_id),
            project_name=project.name if project else None,
            dataset_id=str(row.dataset_id),
            dataset_name=dataset.name if dataset else None,
            name=row.name,
            algo=row.algo,
            hyperparams=dict(row.hyperparams or {}),
            training_config=dict(row.training_config or {}),
            factor_snapshot=list(row.factor_snapshot or []),
            status=row.status,
            last_run=await self._run_brief(last_run),
            created_by=names.get(row.created_by, "（空）"),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _run_out(run: TrainingRun, *, model_name: str | None, job_status: str | None) -> TrainingRunOut:
        return TrainingRunOut(
            id=str(run.id),
            model_id=str(run.model_id),
            model_name=model_name,
            dataset_id=str(run.dataset_id),
            job_id=str(run.job_id) if run.job_id else None,
            job_status=job_status,
            metrics=dict(run.metrics or {}),
            data_range=dict(run.data_range or {}),
            artifact_uri=run.artifact_uri,
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )

    # ------------------------------------------------------------- CRUD
    async def list(
        self, *, page: int, page_size: int, keyword: str | None, project_id: str | None
    ) -> PageOut[ModelOut]:
        repo = ModelRepository(self._session, self._scope)
        rows, total = await repo.list(page=page, page_size=page_size, keyword=keyword, project_id=project_id)
        items = [await self._out(r) for r in rows]
        return PageOut[ModelOut](items=items, total=total, page=page, page_size=page_size)

    async def get(self, model_id: str) -> ModelOut:
        row = await ModelRepository(self._session, self._scope).get(model_id)
        if row is None:
            raise NotFoundError("模型不存在或不属于当前组织")
        return await self._out(row)

    async def create(self, data: ModelCreateIn) -> ModelOut:
        algo = data.algo.strip()
        if algo not in TRAIN_ALGOS:
            raise ValidationAppError(f"暂不支持的算法 {algo!r}；当前可用：{', '.join(sorted(TRAIN_ALGOS))}")
        project = await ProjectRepository(self._session, self._scope).get(data.project_id)
        if project is None:
            raise NotFoundError("项目不存在或不属于当前组织")
        dataset = await DatasetRepository(self._session, self._scope).get(data.dataset_id)
        if dataset is None:
            raise NotFoundError("数据集不存在或不属于当前组织")

        repo = ModelRepository(self._session, self._scope)
        if await repo.count_by_name(data.name.strip(), project_id=project.id):
            raise ConflictError(f"同项目下已存在同名模型：{data.name}")

        # 因子引用 → 快照（引用不存在/重复表达式 → 400）
        factor_repo = FactorRepository(self._session, self._scope)
        snapshot: list[dict[str, Any]] = []
        missing: list[str] = []
        for fid in data.factor_ids:
            factor = await factor_repo.get(fid)
            if factor is None:
                missing.append(fid)
                continue
            snapshot.append(
                {
                    "factor_id": str(factor.id),
                    "name": factor.name,
                    "expression": factor.expression,
                    "version": factor.version,
                    "factor_type": factor.factor_type,
                }
            )
        if missing:
            raise ValidationAppError(f"因子不存在或不属于当前组织：{', '.join(missing)}")
        exprs = [f["expression"] for f in snapshot]
        if len(set(exprs)) != len(exprs):
            raise ValidationAppError("因子表达式重复：模型特征列不能重复（请去掉重复因子）")

        row = await repo.add(
            MLModel(
                org_id=stable_uuid(self._scope.org_id),
                created_by=stable_uuid(self._scope.user_id),
                project_id=project.id,
                dataset_id=dataset.id,
                name=data.name.strip(),
                algo=algo,
                hyperparams=dict(data.hyperparams or {}),
                training_config={"target": (data.target or DEFAULT_TARGET).strip()},
                factor_snapshot=snapshot,
                status="draft",
            )
        )
        await self._audit.record(
            action=AuditAction.MODEL_CREATE,
            resource_type="model",
            resource_id=str(row.id),
            detail={
                "name": row.name,
                "algo": row.algo,
                "dataset_id": str(dataset.id),
                "n_factors": len(snapshot),
            },
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        await self._session.commit()
        return await self._out(row)

    async def update(self, model_id: str, data: ModelUpdateIn) -> ModelOut:
        """可改名与超参；``factor_snapshot`` / ``algo`` / ``dataset_id`` 不可改。"""
        repo = ModelRepository(self._session, self._scope)
        row = await repo.get(model_id)
        if row is None:
            raise NotFoundError("模型不存在或不属于当前组织")
        payload = data.model_dump(exclude_unset=True)
        if "name" in payload and payload["name"] is not None:
            new_name = str(payload["name"]).strip()
            if new_name != row.name and await repo.count_by_name(new_name, project_id=row.project_id):
                raise ConflictError(f"同项目下已存在同名模型：{new_name}")
            row.name = new_name
        if "hyperparams" in payload and payload["hyperparams"] is not None:
            row.hyperparams = dict(payload["hyperparams"])
        await self._session.flush()
        await self._audit.record(
            action=AuditAction.MODEL_UPDATE,
            resource_type="model",
            resource_id=str(row.id),
            detail={"fields": sorted(payload)},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        await self._session.commit()
        return await self._out(row)

    async def delete(self, model_id: str, *, confirm: bool) -> bool:
        if not confirm:
            raise ConfirmationRequiredError("model.delete")
        repo = ModelRepository(self._session, self._scope)
        row = await repo.get(model_id)
        if row is None:
            raise NotFoundError("模型不存在或不属于当前组织")
        bound = await StrategyRepository(self._session, self._scope).count_bounding(str(row.id))
        if bound:
            raise ConflictError(f"有 {bound} 个策略正绑定该模型——先改绑或删除策略")

        # 收集 artifact 键（训练记录随模型级联删除，对象存储尽力清理）
        runs, _ = await TrainingRunRepository(self._session, self._scope).list(
            page=1, page_size=200, model_id=str(row.id)
        )
        artifact_uris = [r.artifact_uri for r in runs if r.artifact_uri]
        name = row.name
        await self._session.delete(row)
        await self._session.flush()
        if self._storage is not None:
            for uri in artifact_uris:
                with contextlib.suppress(Exception):  # noqa: S110 - 尽力清理，失败不影响删除
                    await self._storage.delete(uri)
        await self._audit.record(
            action=AuditAction.MODEL_DELETE,
            resource_type="model",
            resource_id=model_id,
            detail={"name": name, "artifacts_cleaned": len(artifact_uris)},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        await self._session.commit()
        return True

    # ------------------------------------------------------------- 训练
    async def submit_train(
        self, model_id: str, data: TrainSubmitIn, *, job_service: JobService
    ) -> dict[str, Any]:
        """入队 train 任务，返回 ``{job_id, training_run_id, split, status}``。

        payload 携带**完整执行快照**（因子表达式 / 超参 / 目标 / 切分），
        入队后模型行再被修改也不影响本次运行（D5 可复现性）。
        """
        model = await ModelRepository(self._session, self._scope).get(model_id)
        if model is None:
            raise NotFoundError("模型不存在或不属于当前组织")
        dataset = await DatasetRepository(self._session, self._scope).get(str(model.dataset_id))
        if dataset is None:
            raise NotFoundError("数据集不存在或不属于当前组织")
        if not (dataset.start_date and dataset.end_date):
            raise ValidationAppError("数据集尚无日期范围（导入未完成），不能提交训练")

        # 切分：显式优先，缺省按数据集区间 70/30；并夹紧到数据集范围内校验
        if data.split is not None:
            split = {
                "train": list(data.split.train),
                **({"valid": list(data.split.valid)} if data.split.valid else {}),
            }
        else:
            split = default_split(dataset.start_date, dataset.end_date)
        d0, d1 = dataset.start_date, dataset.end_date
        for key, (s, e) in (
            (k, (date.fromisoformat(v[0]), date.fromisoformat(v[1]))) for k, v in split.items()
        ):
            if s < d0 or e > d1:
                raise ValidationAppError(
                    f"split.{key}=[{s.isoformat()}~{e.isoformat()}] 超出数据集区间 "
                    f"[{d0.isoformat()}~{d1.isoformat()}]"
                )

        # 同模型已有活跃训练 → 409（活跃态 payload_hash 唯一索引之外的业务级拦截）
        for active in await JobRepository(self._session, self._scope).active_by_kind(kind="train"):
            if (active.payload or {}).get("model_id") == str(model.id):
                raise ConflictError("该模型已有排队/运行中的训练任务，请等待其完成")

        target = str((dict(model.training_config) or {}).get("target") or DEFAULT_TARGET)
        run = TrainingRun(
            org_id=stable_uuid(self._scope.org_id),
            created_by=stable_uuid(self._scope.user_id),
            project_id=model.project_id,
            model_id=model.id,
            dataset_id=model.dataset_id,
            metrics={},
            data_range={},
        )
        self._session.add(run)
        model.status = "training"
        await self._session.flush()
        run_id = str(run.id)
        # run 行与模型状态先于消息可见（worker 拾取时不依赖本 session 的后续提交）
        await self._session.commit()

        payload = {
            "training_run_id": run_id,
            "model_id": str(model.id),
            "dataset_id": str(model.dataset_id),
            "project_id": str(model.project_id),
            "algo": model.algo,
            "hyperparams": dict(model.hyperparams or {}),
            "target": target,
            "factors": list(model.factor_snapshot or []),
            "split": split,
            "max_instruments": int(data.max_instruments),
        }
        try:
            job_id = await job_service.enqueue(
                kind="train",
                payload=payload,
                requested_by=self._user.username,
                project_id=model.project_id,
            )
        except Exception:
            # 补偿：入队失败回滚 run 行与模型状态，避免孤儿记录
            stale = await TrainingRunRepository(self._session, self._scope).get(run_id)
            if stale is not None:
                await self._session.delete(stale)
            model.status = "draft"
            await self._session.commit()
            raise

        await self._session.refresh(run)  # 入队期间 worker 可能已动过 run 行
        run.job_id = uuid.UUID(str(job_id))
        await self._session.flush()
        await self._audit.record(
            action=AuditAction.TRAIN_SUBMIT,
            resource_type="training_run",
            resource_id=run_id,
            detail={
                "model_id": str(model.id),
                "job_id": job_id,
                "algo": model.algo,
                "split": split,
                "n_factors": len(payload["factors"]),
            },
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        await self._session.commit()
        return {
            "job_id": job_id,
            "training_run_id": run_id,
            "split": split,
            "status": "queued",
        }

    # ------------------------------------------------------------- 训练记录
    async def list_runs(
        self, *, page: int, page_size: int, model_id: str | None, project_id: str | None
    ) -> PageOut[TrainingRunOut]:
        run_repo = TrainingRunRepository(self._session, self._scope)
        rows, total = await run_repo.list(
            page=page, page_size=page_size, model_id=model_id, project_id=project_id
        )
        model_ids = {r.model_id for r in rows}
        model_names: dict[str, str] = {}
        if model_ids:
            model_names = {
                str(m.id): m.name
                for m in (
                    await self._session.execute(
                        select(MLModel).where(
                            MLModel.org_id == stable_uuid(self._scope.org_id),
                            MLModel.id.in_(model_ids),
                        )
                    )
                ).scalars()
            }
        items = [
            self._run_out(
                r,
                model_name=model_names.get(str(r.model_id)),
                job_status=(await self._job_status(r.job_id)),
            )
            for r in rows
        ]
        return PageOut[TrainingRunOut](items=items, total=total, page=page, page_size=page_size)

    async def get_run(self, run_id: str) -> TrainingRunOut:
        run = await TrainingRunRepository(self._session, self._scope).get(run_id)
        if run is None:
            raise NotFoundError("训练记录不存在或不属于当前组织")
        model = await ModelRepository(self._session, self._scope).get(str(run.model_id))
        return self._run_out(
            run,
            model_name=model.name if model else None,
            job_status=await self._job_status(run.job_id),
        )


__all__ = ["ModelService", "TRAIN_ALGOS", "default_split"]
