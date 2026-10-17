"""因子服务：表达式 CRUD + 静态校验 + 发布 + 计算/IC 预览（阶段 6 切片⑤）。

- 表达式在**创建/修改**时经 ``core.qlib_expr`` 静态校验（词法/语法/白名单）；
  真实求值走 worker ``JobKind.FACTOR_COMPUTE``（qlib D.features / stub 合成）；
- 修改表达式 → ``version + 1``（计算运行快照按版本追溯）；
- 发布 = visibility → public，需二次确认并审计；
- 计算 = 提交 job + ``factor_compute_runs`` 落库（metrics + 四标注 + ic/values 对象键）。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from qqlab.core.errors import ConfirmationRequiredError, ConflictError, NotFoundError, ValidationAppError
from qqlab.core.ids import stable_uuid
from qqlab.core.qlib_expr import ExpressionCheck, check_expression
from qqlab.core.tenant import OrgScope
from qqlab.models import Factor, FactorComputeRun, Job, JobKind
from qqlab.models import StudyVisibility as Visibility
from qqlab.ports.audit import AuditAction, AuditWriter
from qqlab.ports.auth import CurrentUser
from qqlab.ports.compute import DEFAULT_TARGET
from qqlab.repositories import (
    DatasetRepository,
    FactorComputeRunRepository,
    FactorRepository,
    JobRepository,
    ProjectRepository,
)
from qqlab.schemas import (
    ExpressionCheckOut,
    FactorComputeRunOut,
    FactorComputeSubmitIn,
    FactorCreateIn,
    FactorOut,
    FactorUpdateIn,
    IcCurveOut,
    PageOut,
)
from qqlab.services.backtest_service import CURVE_MAX_POINTS
from qqlab.services.base import AuditContext, ensure_universe

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from qqlab.config import Settings
    from qqlab.ports.storage import StorageProvider
    from qqlab.services.job_service import JobService


class FactorService:
    def __init__(
        self,
        *,
        session,  # noqa: ANN001 - AsyncSession
        scope: OrgScope,
        user: CurrentUser,
        audit: AuditWriter,
        ctx: AuditContext,
        storage: StorageProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._scope = scope
        self._user = user
        self._audit = audit
        self._ctx = ctx
        self._storage = storage
        self._settings = settings

    # ------------------------------------------------------------- 序列化
    async def _out(self, row: Factor) -> FactorOut:
        project = await ProjectRepository(self._session, self._scope).get(str(row.project_id))
        names = await FactorRepository(self._session, self._scope).usernames([row.created_by])
        return FactorOut(
            id=str(row.id),
            project_id=str(row.project_id),
            project_name=project.name if project else None,
            name=row.name,
            expression=row.expression,
            factor_type=row.factor_type,
            description=row.description,
            params=dict(row.params or {}),
            version=row.version,
            visibility=row.visibility,
            created_by=names.get(row.created_by, "（空）"),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    # ------------------------------------------------------------- 校验
    @staticmethod
    def check(expression: str) -> ExpressionCheckOut:
        result: ExpressionCheck = check_expression(expression)
        return ExpressionCheckOut(
            valid=result.valid, errors=result.errors, fields=result.fields, functions=result.functions
        )

    @staticmethod
    def _ensure_valid(expression: str) -> None:
        result = check_expression(expression)
        if not result.valid:
            raise ValidationAppError("表达式校验未通过：" + "；".join(result.errors))

    # ------------------------------------------------------------- CRUD
    async def list(
        self, *, page: int, page_size: int, keyword: str | None, project_id: str | None
    ) -> PageOut[FactorOut]:
        repo = FactorRepository(self._session, self._scope)
        rows, total = await repo.list(page=page, page_size=page_size, keyword=keyword, project_id=project_id)
        items = [await self._out(r) for r in rows]
        return PageOut[FactorOut](items=items, total=total, page=page, page_size=page_size)

    async def get(self, factor_id: str) -> FactorOut:
        row = await FactorRepository(self._session, self._scope).get(factor_id)
        if row is None:
            raise NotFoundError("因子不存在或不属于当前组织")
        return await self._out(row)

    async def create(self, data: FactorCreateIn) -> FactorOut:
        self._ensure_valid(data.expression)
        project = await ProjectRepository(self._session, self._scope).get(data.project_id)
        if project is None:
            raise NotFoundError("项目不存在或不属于当前组织")
        repo = FactorRepository(self._session, self._scope)
        if await repo.count_by_name(data.name.strip(), project_id=project.id):
            raise ConflictError(f"同项目下已存在同名因子：{data.name}")
        row = await repo.add(
            Factor(
                org_id=stable_uuid(self._scope.org_id),
                created_by=stable_uuid(self._scope.user_id),
                project_id=project.id,
                name=data.name.strip(),
                expression=data.expression.strip(),
                factor_type=data.factor_type.strip() or "expression",
                description=data.description,
                params=data.params or {},
            )
        )
        await self._audit.record(
            action=AuditAction.FACTOR_CREATE,
            resource_type="factor",
            resource_id=str(row.id),
            detail={"name": row.name, "expression": row.expression},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        await self._session.commit()
        return await self._out(row)

    async def update(self, factor_id: str, data: FactorUpdateIn) -> FactorOut:
        repo = FactorRepository(self._session, self._scope)
        row = await repo.get(factor_id)
        if row is None:
            raise NotFoundError("因子不存在或不属于当前组织")
        payload = data.model_dump(exclude_unset=True)
        expression_changed = False
        if "expression" in payload and payload["expression"] is not None:
            new_expr = str(payload["expression"]).strip()
            if new_expr != row.expression:
                self._ensure_valid(new_expr)
                row.expression = new_expr
                row.version = row.version + 1
                expression_changed = True
        if "name" in payload and payload["name"] is not None:
            new_name = str(payload["name"]).strip()
            if new_name != row.name and await repo.count_by_name(new_name, project_id=row.project_id):
                raise ConflictError(f"同项目下已存在同名因子：{new_name}")
            row.name = new_name
        if "description" in payload:
            row.description = payload["description"]
        if "params" in payload and payload["params"] is not None:
            row.params = payload["params"]
        await self._session.flush()
        await self._audit.record(
            action=AuditAction.FACTOR_UPDATE,
            resource_type="factor",
            resource_id=str(row.id),
            detail={
                "fields": sorted(payload),
                "version": row.version,
                "expression_changed": expression_changed,
            },
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        await self._session.commit()
        return await self._out(row)

    async def delete(self, factor_id: str, *, confirm: bool) -> bool:
        if not confirm:
            raise ConfirmationRequiredError("factor.delete")
        repo = FactorRepository(self._session, self._scope)
        row = await repo.get(factor_id)
        if row is None:
            raise NotFoundError("因子不存在或不属于当前组织")
        name = row.name
        await self._session.delete(row)
        await self._session.flush()
        await self._audit.record(
            action=AuditAction.FACTOR_UPDATE,
            resource_type="factor",
            resource_id=factor_id,
            detail={"op": "delete", "name": name},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        await self._session.commit()
        return True

    async def publish(self, factor_id: str, *, confirm: bool) -> FactorOut:
        if not confirm:
            raise ConfirmationRequiredError("factor.publish")
        row = await FactorRepository(self._session, self._scope).get(factor_id)
        if row is None:
            raise NotFoundError("因子不存在或不属于当前组织")
        row.visibility = Visibility.PUBLIC
        await self._session.flush()
        await self._audit.record(
            action=AuditAction.FACTOR_PUBLISH,
            resource_type="factor",
            resource_id=str(row.id),
            detail={"name": row.name, "version": row.version},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        await self._session.commit()
        return await self._out(row)

    # ------------------------------------------------- 因子计算（阶段 6 切片⑤）
    async def _job_status(self, job_id: uuid.UUID | None) -> str | None:
        if job_id is None:
            return None
        row = await self._session.execute(
            select(Job.status).where(Job.id == job_id, Job.org_id == stable_uuid(self._scope.org_id))
        )
        value = row.scalar_one_or_none()
        return str(value) if value else None

    async def _run_out(self, row: FactorComputeRun) -> FactorComputeRunOut:
        dataset = await DatasetRepository(self._session, self._scope).get(str(row.dataset_id))
        return FactorComputeRunOut(
            id=str(row.id),
            factor_id=str(row.factor_id),
            project_id=str(row.project_id),
            dataset_id=str(row.dataset_id),
            dataset_name=dataset.name if dataset else None,
            job_id=str(row.job_id) if row.job_id else None,
            job_status=await self._job_status(row.job_id),
            metrics=dict(row.metrics or {}),
            data_range=dict(row.data_range or {}),
            ic_uri=row.ic_uri,
            values_uri=row.values_uri,
            created_at=row.created_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )

    async def submit_compute(
        self, factor_id: str, data: FactorComputeSubmitIn, *, job_service: JobService
    ) -> dict[str, Any]:
        """入队因子计算任务，返回 ``{job_id, run_id, status}``。

        payload 携带**表达式快照**（当前 version），入队后因子再被修改不影响本次运行。
        """
        if self._settings is None:  # pragma: no cover - 装配恒有 settings
            raise ValidationAppError("服务未装配 settings")
        factor = await FactorRepository(self._session, self._scope).get(factor_id)
        if factor is None:
            raise NotFoundError("因子不存在或不属于当前组织")
        dataset = await DatasetRepository(self._session, self._scope).get(data.dataset_id)
        if dataset is None:
            raise NotFoundError("数据集不存在或不属于当前组织")
        if not (dataset.start_date and dataset.end_date):
            raise ValidationAppError("数据集尚无日期范围（导入未完成），不能提交计算")

        # 股票池校验（阶段 6 D6，fail-closed）：非 all 必须存在于数据集 instruments/
        ensure_universe(
            self._settings,
            org_id=self._scope.org_id,
            storage_uri=dataset.storage_uri,
            universe=data.universe,
        )
        start = data.start_date or dataset.start_date
        end = data.end_date or dataset.end_date
        if start > end:
            raise ValidationAppError(f"计算区间非法：{start.isoformat()} > {end.isoformat()}")
        if start < dataset.start_date or end > dataset.end_date:
            raise ValidationAppError(
                f"计算区间 [{start.isoformat()}~{end.isoformat()}] 超出数据集区间 "
                f"[{dataset.start_date.isoformat()}~{dataset.end_date.isoformat()}]"
            )

        # 同因子已有活跃计算 → 409（业务级拦截，与训练同口径）
        for active in await JobRepository(self._session, self._scope).active_by_kind(kind="factor_compute"):
            if (active.payload or {}).get("factor_id") == str(factor.id):
                raise ConflictError("该因子已有排队/运行中的计算任务，请等待其完成")

        run = FactorComputeRun(
            org_id=stable_uuid(self._scope.org_id),
            created_by=stable_uuid(self._scope.user_id),
            project_id=factor.project_id,
            factor_id=factor.id,
            dataset_id=dataset.id,
            metrics={},
            data_range={},
        )
        self._session.add(run)
        await self._session.flush()
        run_id = str(run.id)
        # run 行先于消息可见（worker 拾取时不依赖本 session 的后续提交）
        await self._session.commit()

        payload = {
            "run_id": run_id,
            "factor_id": str(factor.id),
            "project_id": str(factor.project_id),
            "dataset_id": str(dataset.id),
            "expression": factor.expression,  # 表达式快照（含 version 语义）
            "version": factor.version,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "universe": data.universe,
            "max_instruments": int(data.max_instruments),
            "target": DEFAULT_TARGET,
        }
        try:
            job_id = await job_service.enqueue(
                kind=JobKind.FACTOR_COMPUTE,
                payload=payload,
                requested_by=self._user.username,
                project_id=factor.project_id,
            )
        except Exception:
            # 补偿：入队失败回滚 run 行，避免孤儿记录
            stale = await FactorComputeRunRepository(self._session, self._scope).get(run_id)
            if stale is not None:
                await self._session.delete(stale)
            await self._session.commit()
            raise

        await self._session.refresh(run)  # 入队期间 worker 可能已动过 run 行
        run.job_id = uuid.UUID(str(job_id))
        await self._session.flush()
        await self._audit.record(
            action=AuditAction.FACTOR_COMPUTE,
            resource_type="factor_compute_run",
            resource_id=run_id,
            detail={
                "factor_id": str(factor.id),
                "expression": factor.expression,
                "version": factor.version,
                "job_id": job_id,
                "dataset_id": str(dataset.id),
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "universe": data.universe,
            },
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        await self._session.commit()
        return {"job_id": job_id, "run_id": run_id, "status": "queued"}

    async def list_compute_runs(
        self, factor_id: str, *, page: int, page_size: int
    ) -> PageOut[FactorComputeRunOut]:
        if await FactorRepository(self._session, self._scope).get(factor_id) is None:
            raise NotFoundError("因子不存在或不属于当前组织")
        rows, total = await FactorComputeRunRepository(self._session, self._scope).list_by_factor(
            factor_id=factor_id, page=page, page_size=page_size
        )
        items = [await self._run_out(r) for r in rows]
        return PageOut[FactorComputeRunOut](items=items, total=total, page=page, page_size=page_size)

    async def ic_curve(self, factor_id: str, run_id: str) -> IcCurveOut:
        """日度 rank-IC 序列：对象存储 CSV → JSON 点列，>1500 点等步长降采样。"""
        try:
            fid = uuid.UUID(str(factor_id))
        except ValueError as exc:
            raise NotFoundError("计算记录不存在或不属于当前组织/因子") from exc
        repo = FactorComputeRunRepository(self._session, self._scope)
        run = await repo.get(run_id)
        if run is None or run.factor_id != fid:
            raise NotFoundError("计算记录不存在或不属于当前组织/因子")
        if not run.ic_uri:
            raise ValidationAppError("因子计算尚未完成（IC 序列未生成），请等待任务结束")
        if self._storage is None:  # pragma: no cover - 装配恒有 storage
            raise ValidationAppError("对象存储未装配")
        try:
            raw = await self._storage.get(run.ic_uri)
        except KeyError as exc:
            raise ValidationAppError("IC 序列对象缺失（可能已被清理）") from exc

        rows: list[list] = []
        for line in raw.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("date,"):
                continue
            date_s, _, ic_s = line.partition(",")
            try:
                rows.append([date_s, round(float(ic_s), 6)])
            except ValueError:
                continue  # 容忍表头/坏行
        if not rows:
            raise ValidationAppError("IC 序列为空")

        total = len(rows)
        if total <= CURVE_MAX_POINTS:
            return IcCurveOut(points=rows, total=total, downsampled=False)
        step = -(-total // CURVE_MAX_POINTS)  # ceil
        sampled = rows[::step]
        if sampled[-1] != rows[-1]:
            sampled.append(rows[-1])
        return IcCurveOut(points=sampled, total=total, downsampled=True)


__all__ = ["FactorService"]
