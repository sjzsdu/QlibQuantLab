"""回测服务：提交（费用三件套 + 双信号源校验）/ 列表 / 详情 / 净值曲线（阶段 5）。

- 费用假设 ``cost_config`` **三件套必填**（schema 层 422），100% 透传进模拟器；
- ``signal_source=model`` 的策略提交时**前置校验**：模型必须已有产出 artifact 的
  成功训练记录，否则 409（避免任务排队后才失败）；
- 报告四标注口径（docs/stage5 写死）：``data_range``（含数据来源授权，由 worker
  回填）+ ``cost_config`` + ``limitations`` + 数据集→数据源/授权链；
- 净值曲线从对象存储读回，降采样 ≤1500 点供 ECharts。
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from qqlab.core.errors import ConflictError, NotFoundError, ValidationAppError
from qqlab.core.ids import stable_uuid
from qqlab.core.tenant import OrgScope
from qqlab.models import Backtest, Job
from qqlab.ports.audit import AuditAction, AuditWriter
from qqlab.ports.auth import CurrentUser
from qqlab.repositories import (
    BacktestRepository,
    DatasetRepository,
    ModelRepository,
    ProjectRepository,
    StrategyRepository,
    TrainingRunRepository,
)
from qqlab.schemas import BacktestCreateIn, BacktestOut, CurveOut, PageOut
from qqlab.services.base import AuditContext, ensure_universe

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from qqlab.config import Settings
    from qqlab.ports.storage import StorageProvider
    from qqlab.services.job_service import JobService

#: 曲线降采样上限（ECharts 单系列足够细腻，且响应体可控）
CURVE_MAX_POINTS = 1500

#: 导出报告末尾固定风险提示（与前端 RiskBanner 同口径）
EXPORT_DISCLAIMER = (
    "风险提示：本平台不提供任何投资建议，不保证任何策略收益，投资风险由用户自行承担；历史回测不代表未来收益。"
)


class BacktestService:
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
    async def _job_status(self, job_id: uuid.UUID | None) -> str | None:
        if job_id is None:
            return None
        row = await self._session.execute(
            select(Job.status).where(Job.id == job_id, Job.org_id == stable_uuid(self._scope.org_id))
        )
        value = row.scalar_one_or_none()
        return str(value) if value else None

    async def _out(self, row: Backtest) -> BacktestOut:
        project = await ProjectRepository(self._session, self._scope).get(str(row.project_id))
        strategy = await StrategyRepository(self._session, self._scope).get(str(row.strategy_id))
        dataset = await DatasetRepository(self._session, self._scope).get(str(row.dataset_id))
        names = await BacktestRepository(self._session, self._scope).usernames([row.created_by])
        return BacktestOut(
            id=str(row.id),
            project_id=str(row.project_id),
            project_name=project.name if project else None,
            strategy_id=str(row.strategy_id),
            strategy_name=strategy.name if strategy else None,
            dataset_id=str(row.dataset_id),
            dataset_name=dataset.name if dataset else None,
            job_id=str(row.job_id) if row.job_id else None,
            job_status=await self._job_status(row.job_id),
            benchmark=row.benchmark,
            cost_config=dict(row.cost_config or {}),
            params=dict(row.params or {}),
            split_config=dict(row.split_config or {}),
            metrics=dict(row.metrics or {}),
            data_range=dict(row.data_range or {}),
            limitations=row.limitations,
            curve_uri=row.curve_uri,
            positions_uri=row.positions_uri,
            start_date=row.start_date,
            end_date=row.end_date,
            created_by=names.get(row.created_by, "（空）"),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    # ------------------------------------------------------------- 提交
    async def submit(self, data: BacktestCreateIn, *, job_service: JobService) -> BacktestOut:
        strategy = await StrategyRepository(self._session, self._scope).get(data.strategy_id)
        if strategy is None:
            raise NotFoundError("策略不存在或不属于当前组织")
        dataset = await DatasetRepository(self._session, self._scope).get(data.dataset_id)
        if dataset is None:
            raise NotFoundError("数据集不存在或不属于当前组织")
        if not (dataset.start_date and dataset.end_date):
            raise ValidationAppError("数据集尚无日期范围（导入未完成），不能提交回测")

        # 股票池校验（阶段 6 D6）：非 all 必须存在于数据集 instruments/（fail-closed）
        ensure_universe(
            self._settings,
            org_id=self._scope.org_id,
            storage_uri=dataset.storage_uri,
            universe=data.universe,
        )

        config: dict[str, Any] = dict(strategy.signal_config or {})
        if config.get("source") == "model":
            if not strategy.model_id:
                raise ValidationAppError("策略为模型信号但未绑定 model_id")
            run = await TrainingRunRepository(self._session, self._scope).latest_succeeded(
                str(strategy.model_id)
            )
            if run is None:
                model = await ModelRepository(self._session, self._scope).get(str(strategy.model_id))
                raise ConflictError(
                    f"模型「{model.name if model else strategy.model_id}」尚无产出 artifact 的成功训练记录"
                    "——请先完成训练再提交回测"
                )

        start = data.start_date
        end = data.end_date
        row = Backtest(
            org_id=stable_uuid(self._scope.org_id),
            created_by=stable_uuid(self._scope.user_id),
            project_id=strategy.project_id,
            strategy_id=strategy.id,
            dataset_id=dataset.id,
            benchmark=data.benchmark,
            # 费用三件套：API 扁平形态原样入库（worker 侧 CostConfig.from_dict 兼容）
            cost_config=data.cost_config.model_dump(),
            params={
                "topk": data.topk,
                "max_instruments": data.max_instruments,
                "universe": data.universe,
            },
            split_config={
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
            },
            start_date=start,
            end_date=end,
        )
        row = await BacktestRepository(self._session, self._scope).add(row)
        backtest_id = str(row.id)
        # 行先于消息可见（worker 拾取后立即读行，不能等本 session 的收尾提交）
        await self._session.commit()
        try:
            job_id = await job_service.enqueue(
                kind="backtest",
                payload={"backtest_id": backtest_id},
                requested_by=self._user.username,
                project_id=strategy.project_id,
            )
        except Exception:
            # 补偿：入队失败删除刚落库的回测行，避免孤儿记录
            stale = await BacktestRepository(self._session, self._scope).get(backtest_id)
            if stale is not None:
                await self._session.delete(stale)
                await self._session.commit()
            raise
        row.job_id = uuid.UUID(job_id)
        await self._session.flush()
        await self._audit.record(
            action=AuditAction.BACKTEST_SUBMIT,
            resource_type="backtest",
            resource_id=str(row.id),
            detail={
                "strategy_id": str(strategy.id),
                "dataset_id": str(dataset.id),
                "benchmark": row.benchmark,
                "job_id": job_id,
                "cost_config": row.cost_config,
                "signal_source": config.get("source", "rule"),
            },
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        await self._session.commit()
        return await self._out(row)

    # ------------------------------------------------------------- 读取
    async def list(
        self, *, page: int, page_size: int, strategy_id: str | None, project_id: str | None
    ) -> PageOut[BacktestOut]:
        repo = BacktestRepository(self._session, self._scope)
        rows, total = await repo.list(
            page=page, page_size=page_size, strategy_id=strategy_id, project_id=project_id
        )
        items = [await self._out(r) for r in rows]
        return PageOut[BacktestOut](items=items, total=total, page=page, page_size=page_size)

    async def get(self, backtest_id: str) -> BacktestOut:
        row = await BacktestRepository(self._session, self._scope).get(backtest_id)
        if row is None:
            raise NotFoundError("回测不存在或不属于当前组织")
        return await self._out(row)

    async def curve(self, backtest_id: str) -> CurveOut:
        """净值曲线：对象存储 CSV → JSON 点列，>1500 点等步长降采样（保末点）。"""
        row = await BacktestRepository(self._session, self._scope).get(backtest_id)
        if row is None:
            raise NotFoundError("回测不存在或不属于当前组织")
        if not row.curve_uri:
            raise ValidationAppError("回测尚未完成（净值曲线未生成），请等待任务结束")
        if self._storage is None:  # pragma: no cover - 装配恒有 storage
            raise ValidationAppError("对象存储未装配")
        try:
            raw = await self._storage.get(row.curve_uri)
        except KeyError as exc:
            raise ValidationAppError("净值曲线对象缺失（可能已被清理）") from exc

        rows: list[list] = []
        for line in raw.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            date_s, _, nav_s = line.partition(",")
            try:
                rows.append([date_s, round(float(nav_s), 6)])
            except ValueError:
                continue  # 容忍表头/坏行
        if not rows:
            raise ValidationAppError("净值曲线为空")

        total = len(rows)
        if total <= CURVE_MAX_POINTS:
            return CurveOut(points=rows, total=total, downsampled=False)
        step = -(-total // CURVE_MAX_POINTS)  # ceil
        sampled = rows[::step]
        if sampled[-1] != rows[-1]:
            sampled.append(rows[-1])
        return CurveOut(points=sampled, total=total, downsampled=True)

    # ------------------------------------------------------------- 导出（阶段 6 切片④）
    async def export_csv(self, backtest_id: str, *, section: str) -> tuple[str, bytes]:
        """回测导出：返回 ``(下载文件名, CSV 字节)``。审计与二次确认在 API 层。

        - ``report``：报告 CSV（``section,key,value`` 三列），覆盖四标注口径 ——
          ``data_range``（含数据来源授权链，逐层展平）+ ``cost_config`` + ``limitations``
          + 参数/指标/切分，末尾附固定风险提示。UTF-8 BOM 便于 Excel 打开中文。
          内容与页面展示**同源**（都经 ``_out`` 序列化），避免导出与界面口径漂移。
        - ``positions``：逐日持仓明细（对象存储 ``positions.csv`` 原样转发，无 BOM）。
        """
        row = await BacktestRepository(self._session, self._scope).get(backtest_id)
        if row is None:
            raise NotFoundError("回测不存在或不属于当前组织")
        stamp = row.created_at.strftime("%Y%m%d_%H%M%S")

        if section == "positions":
            if not row.positions_uri:
                raise ValidationAppError("该回测尚无持仓明细（任务未完成，或产出早于持仓快照功能上线）")
            if self._storage is None:  # pragma: no cover - 装配恒有 storage
                raise ValidationAppError("对象存储未装配")
            try:
                payload = await self._storage.get(row.positions_uri)
            except KeyError as exc:
                raise ValidationAppError("持仓明细对象缺失（可能已被清理）") from exc
            return f"backtest_{backtest_id}_positions_{stamp}.csv", payload

        out = await self._out(row)
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(["section", "key", "value"])

        def _cell(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, bool):
                return "true" if value else "false"
            if isinstance(value, dict | list):
                return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
            return str(value)

        def _flat(prefix: str, mapping: dict) -> list[tuple[str, Any]]:  # noqa: ANN001
            pairs: list[tuple[str, Any]] = []
            for key in sorted(mapping):
                value = mapping[key]
                path = f"{prefix}.{key}" if prefix else str(key)
                if isinstance(value, dict):
                    pairs.extend(_flat(path, value))
                else:
                    pairs.append((path, value))
            return pairs

        meta_rows = [
            ("backtest_id", out.id),
            ("strategy_id", out.strategy_id),
            ("strategy_name", out.strategy_name),
            ("dataset_id", out.dataset_id),
            ("dataset_name", out.dataset_name),
            ("benchmark", out.benchmark),
            ("signal_source", (out.data_range or {}).get("signal_source")),
            ("universe", (out.data_range or {}).get("universe")),
            ("engine", (out.metrics or {}).get("engine")),
            ("created_by", out.created_by),
            ("created_at", out.created_at.isoformat()),
            ("start_date", out.start_date.isoformat() if out.start_date else None),
            ("end_date", out.end_date.isoformat() if out.end_date else None),
            ("job_status", out.job_status),
        ]
        for key, value in meta_rows:
            writer.writerow(["meta", key, _cell(value)])
        for section_name, mapping in (
            ("param", out.params or {}),
            ("metric", out.metrics or {}),
            ("cost", out.cost_config or {}),
            ("split", out.split_config or {}),
            ("data_range", out.data_range or {}),
        ):
            for key, value in _flat("", mapping):
                writer.writerow([section_name, key, _cell(value)])
        writer.writerow(["disclaimer", "limitations", out.limitations or ""])
        writer.writerow(["disclaimer", "risk", EXPORT_DISCLAIMER])

        return f"backtest_{backtest_id}_report_{stamp}.csv", b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


__all__ = ["BacktestService", "CURVE_MAX_POINTS", "EXPORT_DISCLAIMER"]
