"""因子服务：表达式 CRUD + 静态校验 + 发布（阶段 4 范围，不含计算）。

- 表达式在**创建/修改**时经 ``core.qlib_expr`` 静态校验（词法/语法/白名单），
  不执行计算 —— 真实求值属阶段 5（worker 用 qlib D.features）；
- 修改表达式 → ``version + 1``（模型训练/回测引用因子版本，需可追溯）；
- 发布 = visibility → public，需二次确认并审计。
"""

from __future__ import annotations

from qqlab.core.errors import ConfirmationRequiredError, ConflictError, NotFoundError, ValidationAppError
from qqlab.core.ids import stable_uuid
from qqlab.core.qlib_expr import ExpressionCheck, check_expression
from qqlab.core.tenant import OrgScope
from qqlab.models import Factor
from qqlab.models import StudyVisibility as Visibility
from qqlab.ports.audit import AuditAction, AuditWriter
from qqlab.ports.auth import CurrentUser
from qqlab.repositories import FactorRepository, ProjectRepository
from qqlab.schemas import ExpressionCheckOut, FactorCreateIn, FactorOut, FactorUpdateIn, PageOut
from qqlab.services.base import AuditContext


class FactorService:
    def __init__(
        self,
        *,
        session,  # noqa: ANN001 - AsyncSession
        scope: OrgScope,
        user: CurrentUser,
        audit: AuditWriter,
        ctx: AuditContext,
    ) -> None:
        self._session = session
        self._scope = scope
        self._user = user
        self._audit = audit
        self._ctx = ctx

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
            detail={"fields": sorted(payload), "version": row.version, "expression_changed": expression_changed},
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


__all__ = ["FactorService"]
