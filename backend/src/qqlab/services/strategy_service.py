"""策略服务：信号配置 CRUD + 绑定模型 + 公开发布（阶段 5）。

``signal_config`` 存 ``{"source": "rule"|"model", "lookback": N}``：
- rule → 动量规则（回看窗口 lookback），不依赖模型；
- model → ``strategy.model_id`` 绑定，回测时取该模型**最近一次产出 artifact 的
  成功训练**做样本外预测（strategies 表只有 model_id 列，运行时版本不入表，
  口径见 docs/stage5）。

发布 = visibility → public + version+1，需二次确认（对齐因子发布）。
"""

from __future__ import annotations

from datetime import UTC, datetime

from qqlab.core.errors import ConfirmationRequiredError, ConflictError, NotFoundError, ValidationAppError
from qqlab.core.ids import stable_uuid
from qqlab.core.tenant import OrgScope
from qqlab.models import MLModel, Strategy
from qqlab.models import StudyVisibility as Visibility
from qqlab.ports.audit import AuditAction, AuditWriter
from qqlab.ports.auth import CurrentUser
from qqlab.repositories import ModelRepository, ProjectRepository, StrategyRepository
from qqlab.schemas import PageOut, StrategyCreateIn, StrategyOut, StrategyUpdateIn
from qqlab.services.base import AuditContext


class StrategyService:
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
    async def _out(self, row: Strategy) -> StrategyOut:
        project = await ProjectRepository(self._session, self._scope).get(str(row.project_id))
        model_name: str | None = None
        if row.model_id:
            model = await ModelRepository(self._session, self._scope).get(str(row.model_id))
            model_name = model.name if model else None
        names = await StrategyRepository(self._session, self._scope).usernames([row.created_by])
        config = dict(row.signal_config or {})
        return StrategyOut(
            id=str(row.id),
            project_id=str(row.project_id),
            project_name=project.name if project else None,
            model_id=str(row.model_id) if row.model_id else None,
            model_name=model_name,
            name=row.name,
            description=row.description,
            signal_source=str(config.get("source", "rule")),
            signal_config=config,
            visibility=row.visibility,
            is_public=row.is_public,
            version=row.version,
            published_at=row.published_at,
            published_by=row.published_by,
            created_by=names.get(row.created_by, "（空）"),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    # ------------------------------------------------------------- 校验
    async def _ensure_model(self, model_id: str) -> MLModel:
        model = await ModelRepository(self._session, self._scope).get(model_id)
        if model is None:
            raise NotFoundError("模型不存在或不属于当前组织")
        return model

    # ------------------------------------------------------------- CRUD
    async def list(
        self, *, page: int, page_size: int, keyword: str | None, project_id: str | None
    ) -> PageOut[StrategyOut]:
        repo = StrategyRepository(self._session, self._scope)
        rows, total = await repo.list(page=page, page_size=page_size, keyword=keyword, project_id=project_id)
        items = [await self._out(r) for r in rows]
        return PageOut[StrategyOut](items=items, total=total, page=page, page_size=page_size)

    async def get(self, strategy_id: str) -> StrategyOut:
        row = await StrategyRepository(self._session, self._scope).get(strategy_id)
        if row is None:
            raise NotFoundError("策略不存在或不属于当前组织")
        return await self._out(row)

    async def create(self, data: StrategyCreateIn) -> StrategyOut:
        project = await ProjectRepository(self._session, self._scope).get(data.project_id)
        if project is None:
            raise NotFoundError("项目不存在或不属于当前组织")
        repo = StrategyRepository(self._session, self._scope)
        if await repo.count_by_name(data.name.strip(), project_id=project.id):
            raise ConflictError(f"同项目下已存在同名策略：{data.name}")
        model_id: str | None = None
        if data.signal_source == "model":
            model = await self._ensure_model(data.model_id or "")
            model_id = str(model.id)
        row = await repo.add(
            Strategy(
                org_id=stable_uuid(self._scope.org_id),
                created_by=stable_uuid(self._scope.user_id),
                project_id=project.id,
                model_id=stable_uuid(model_id) if model_id else None,
                name=data.name.strip(),
                description=data.description,
                signal_config={"source": data.signal_source, "lookback": data.lookback},
            )
        )
        await self._audit.record(
            action=AuditAction.STRATEGY_CREATE,
            resource_type="strategy",
            resource_id=str(row.id),
            detail={"name": row.name, "signal_source": data.signal_source, "model_id": model_id},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        await self._session.commit()
        return await self._out(row)

    async def update(self, strategy_id: str, data: StrategyUpdateIn) -> StrategyOut:
        repo = StrategyRepository(self._session, self._scope)
        row = await repo.get(strategy_id)
        if row is None:
            raise NotFoundError("策略不存在或不属于当前组织")
        payload = data.model_dump(exclude_unset=True)
        config = dict(row.signal_config or {})
        config.setdefault("source", "rule")

        # 信号源切换：显式 signal_source 或单独提交 model_id 都算切到 model
        new_source = payload.get("signal_source", config.get("source", "rule"))
        if "model_id" in payload and payload["model_id"] and "signal_source" not in payload:
            new_source = "model"
        if new_source == "model":
            model_ref = payload.get("model_id") or (str(row.model_id) if row.model_id else None)
            if not model_ref:
                raise ValidationAppError("切换到模型信号需要 model_id")
            model = await self._ensure_model(model_ref)
            row.model_id = model.id
        else:
            row.model_id = None
        config["source"] = new_source
        if "lookback" in payload and payload["lookback"] is not None:
            config["lookback"] = int(payload["lookback"])
        row.signal_config = config
        if "name" in payload and payload["name"] is not None:
            new_name = str(payload["name"]).strip()
            if new_name != row.name and await repo.count_by_name(new_name, project_id=row.project_id):
                raise ConflictError(f"同项目下已存在同名策略：{new_name}")
            row.name = new_name
        if "description" in payload:
            row.description = payload["description"]

        await self._session.flush()
        await self._audit.record(
            action=AuditAction.STRATEGY_UPDATE,
            resource_type="strategy",
            resource_id=str(row.id),
            detail={"fields": sorted(payload), "signal_source": config.get("source")},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        await self._session.commit()
        return await self._out(row)

    async def publish(self, strategy_id: str, *, confirm: bool) -> StrategyOut:
        if not confirm:
            raise ConfirmationRequiredError("strategy.publish")
        row = await StrategyRepository(self._session, self._scope).get(strategy_id)
        if row is None:
            raise NotFoundError("策略不存在或不属于当前组织")
        row.visibility = Visibility.PUBLIC
        row.is_public = True
        row.version = row.version + 1
        row.published_at = datetime.now(tz=UTC)
        row.published_by = self._user.username
        await self._session.flush()
        await self._audit.record(
            action=AuditAction.STRATEGY_PUBLISH,
            resource_type="strategy",
            resource_id=str(row.id),
            detail={"name": row.name, "version": row.version},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        await self._session.commit()
        return await self._out(row)


__all__ = ["StrategyService"]
