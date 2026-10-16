"""研究链路仓库：models / training_runs / strategies（**强制租户过滤**）。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select

from qqlab.core.ids import stable_uuid
from qqlab.models import MLModel, Strategy, TrainingRun
from qqlab.repositories.base import BaseRepository


class ModelRepository(BaseRepository):
    def _base(self):  # noqa: ANN202
        return select(MLModel).where(MLModel.org_id == stable_uuid(self.scope.org_id))

    async def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        keyword: str | None = None,
        project_id: str | None = None,
    ) -> tuple[list[MLModel], int]:
        offset, limit = self.page_offsets(page, page_size)
        stmt = self._base()
        if keyword:
            like = f"%{keyword.strip()}%"
            stmt = stmt.where(or_(MLModel.name.like(like), MLModel.algo.like(like)))
        if project_id:
            stmt = stmt.where(MLModel.project_id == stable_uuid(project_id))
        total = int(
            (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        )
        rows = (
            (await self.session.execute(stmt.order_by(MLModel.created_at.desc()).offset(offset).limit(limit)))
            .scalars()
            .all()
        )
        return list(rows), total

    async def get(self, model_id: str | uuid.UUID) -> MLModel | None:
        try:
            mid = uuid.UUID(str(model_id))
        except ValueError:
            return None
        return (await self.session.execute(self._base().where(MLModel.id == mid))).scalars().first()

    async def count_by_name(self, name: str, *, project_id: uuid.UUID) -> int:
        stmt = self._base().where(MLModel.project_id == project_id, MLModel.name == name)
        return int(
            (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        )

    async def add(self, model: MLModel) -> MLModel:
        self.session.add(model)
        await self.session.flush()
        return model


class TrainingRunRepository(BaseRepository):
    def _base(self):  # noqa: ANN202
        return select(TrainingRun).where(TrainingRun.org_id == stable_uuid(self.scope.org_id))

    async def get(self, run_id: str | uuid.UUID) -> TrainingRun | None:
        try:
            rid = uuid.UUID(str(run_id))
        except ValueError:
            return None
        return (await self.session.execute(self._base().where(TrainingRun.id == rid))).scalars().first()

    async def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        model_id: str | None = None,
        project_id: str | None = None,
    ) -> tuple[list[TrainingRun], int]:
        offset, limit = self.page_offsets(page, page_size)
        stmt = self._base()
        if model_id:
            stmt = stmt.where(TrainingRun.model_id == stable_uuid(model_id))
        if project_id:
            stmt = stmt.where(TrainingRun.project_id == stable_uuid(project_id))
        total = int(
            (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        )
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(TrainingRun.created_at.desc()).offset(offset).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total

    async def latest(self, model_id: str | uuid.UUID) -> TrainingRun | None:
        """某模型最近一次训练记录（列表页 last_run 用）。"""
        stmt = (
            self._base()
            .where(TrainingRun.model_id == stable_uuid(model_id))
            .order_by(TrainingRun.created_at.desc())
        )
        return (await self.session.execute(stmt.limit(1))).scalars().first()

    async def latest_succeeded(self, model_id: str | uuid.UUID) -> TrainingRun | None:
        """最近一次**产出 artifact** 的成功训练（模型信号回测绑定的运行时版本）。"""
        stmt = (
            self._base()
            .where(TrainingRun.model_id == stable_uuid(model_id), TrainingRun.artifact_uri.is_not(None))
            .order_by(TrainingRun.created_at.desc())
        )
        return (await self.session.execute(stmt.limit(1))).scalars().first()

    async def add(self, run: TrainingRun) -> TrainingRun:
        self.session.add(run)
        await self.session.flush()
        return run


class StrategyRepository(BaseRepository):
    def _base(self):  # noqa: ANN202
        return select(Strategy).where(Strategy.org_id == stable_uuid(self.scope.org_id))

    async def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        keyword: str | None = None,
        project_id: str | None = None,
    ) -> tuple[list[Strategy], int]:
        offset, limit = self.page_offsets(page, page_size)
        stmt = self._base()
        if keyword:
            like = f"%{keyword.strip()}%"
            stmt = stmt.where(or_(Strategy.name.like(like), Strategy.description.like(like)))
        if project_id:
            stmt = stmt.where(Strategy.project_id == stable_uuid(project_id))
        total = int(
            (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        )
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(Strategy.created_at.desc()).offset(offset).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total

    async def get(self, strategy_id: str | uuid.UUID) -> Strategy | None:
        try:
            sid = uuid.UUID(str(strategy_id))
        except ValueError:
            return None
        return (await self.session.execute(self._base().where(Strategy.id == sid))).scalars().first()

    async def count_by_name(self, name: str, *, project_id: uuid.UUID) -> int:
        stmt = self._base().where(Strategy.project_id == project_id, Strategy.name == name)
        return int(
            (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        )

    async def count_bounding(self, model_id: str | uuid.UUID) -> int:
        """绑定某模型的策略数（模型删除前的 RESTRICT 预检）。"""
        stmt = self._base().where(Strategy.model_id == stable_uuid(model_id))
        return int(
            (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        )

    async def add(self, strategy: Strategy) -> Strategy:
        self.session.add(strategy)
        await self.session.flush()
        return strategy


__all__ = ["ModelRepository", "StrategyRepository", "TrainingRunRepository"]
