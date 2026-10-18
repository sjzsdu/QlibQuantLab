"""任务仓库：jobs / job_logs / backtests 的读写（**强制租户过滤**）。

worker 处理任务时同样受租户边界约束：job 按 org_id 读取，
跨租户读到 None 即失败（handler 会把任务标记为 failed）。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update

from qqlab.core.ids import stable_uuid
from qqlab.models import Backtest, Job, JobLog, JobStatus
from qqlab.repositories.base import BaseRepository

WORKER_ID = "qqlab-worker"


def payload_hash(kind: str, payload: dict) -> str:
    raw = json.dumps({"kind": kind, "payload": payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


class JobRepository(BaseRepository):
    def _base(self):  # noqa: ANN202
        return select(Job).where(Job.org_id == stable_uuid(self.scope.org_id))

    async def create(
        self,
        *,
        kind: str,
        payload: dict,
        project_id: str | uuid.UUID | None = None,
        requested_by: str = "",
        max_attempts: int = 3,
        created_by: str | uuid.UUID | None = None,
    ) -> Job:
        """入队一条任务。

        ``payload["org_key"]`` 由本方法从 scope 注入（外部 org 串，如 ``dev-org``）：
        worker 用它派生 Qlib 数据目录与对象存储键（与 API 层同源），
        并在执行前校验 ``stable_uuid(org_key) == job.org_id``，防止串租户。
        ``created_by`` 缺省取 scope.user_id（外部用户串 → users.id）。
        """
        full_payload = {**payload, "org_key": self.scope.org_id}
        job = Job(
            org_id=stable_uuid(self.scope.org_id),
            created_by=stable_uuid(created_by or self.scope.user_id),
            project_id=uuid.UUID(str(project_id)) if project_id else None,
            kind=kind,
            status=JobStatus.QUEUED,
            payload=full_payload,
            requested_by=requested_by,
            max_attempts=max_attempts,
            payload_hash=payload_hash(kind, full_payload),
            queued_at=datetime.now(tz=UTC),
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get(self, job_id: str | uuid.UUID) -> Job | None:
        try:
            jid = uuid.UUID(str(job_id))
        except ValueError:
            return None
        return (await self.session.execute(self._base().where(Job.id == jid))).scalars().first()

    async def find_by_hash(self, kind: str, payload: dict, *, status: str) -> Job | None:
        # 与 create() 同源：哈希按注入 org_key 后的 payload 计算
        h = payload_hash(kind, {**payload, "org_key": self.scope.org_id})
        stmt = self._base().where(Job.kind == kind, Job.payload_hash == h, Job.status == status)
        return (await self.session.execute(stmt)).scalars().first()

    async def count(self, *, status: str | None = None, kind: str | None = None) -> int:
        stmt = select(func.count()).select_from(Job).where(Job.org_id == stable_uuid(self.scope.org_id))
        if status:
            stmt = stmt.where(Job.status == status)
        if kind:
            stmt = stmt.where(Job.kind == kind)
        return int((await self.session.execute(stmt)).scalar_one())

    async def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        kind: str | None = None,
        status: str | None = None,
    ) -> tuple[list[Job], int]:
        """分页列举任务（阶段 4 只读子集；供 UI 轮询导入进度）。"""
        offset, limit = self.page_offsets(page, page_size)
        stmt = self._base()
        if kind:
            stmt = stmt.where(Job.kind == kind)
        if status:
            stmt = stmt.where(Job.status == status)
        total = int(
            (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        )
        rows = (
            (await self.session.execute(stmt.order_by(Job.created_at.desc()).offset(offset).limit(limit)))
            .scalars()
            .all()
        )
        return list(rows), total

    async def mark_running(self, job_id: str | uuid.UUID) -> bool:
        """queued → running 的比较并交换（attempts 自增，带心跳时间）。"""
        job = await self.get(job_id)
        if job is None or job.status != JobStatus.QUEUED:
            return False
        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.locked_by = WORKER_ID
        job.started_at = job.started_at or datetime.now(tz=UTC)
        job.heartbeat_at = datetime.now(tz=UTC)
        await self.session.flush()
        return True

    async def heartbeat(self, job_id: str | uuid.UUID, *, progress: int | None = None) -> None:
        job = await self.get(job_id)
        if job is None:
            return
        job.heartbeat_at = datetime.now(tz=UTC)
        if progress is not None:
            job.progress = max(0, min(100, int(progress)))
        await self.session.flush()

    async def mark_succeeded(self, job_id: str | uuid.UUID, *, log_uri: str | None = None) -> None:
        job = await self.get(job_id)
        if job is None:
            return
        job.status = JobStatus.SUCCEEDED
        job.progress = 100
        job.error = None
        job.log_uri = log_uri or job.log_uri
        job.finished_at = datetime.now(tz=UTC)
        await self.session.flush()

    async def mark_failed(self, job_id: str | uuid.UUID, error: str) -> None:
        job = await self.get(job_id)
        if job is None:
            return
        job.status = JobStatus.FAILED
        job.error = error[:4000]
        job.finished_at = datetime.now(tz=UTC)
        await self.session.flush()

    async def mark_canceled(self, job_id: str | uuid.UUID, *, reason: str = "用户取消") -> bool:
        """running → canceled 的原子 CAS（Core UPDATE ... WHERE status=running）。

        worker 在 progress 检查点调用；API **绝不**直接 UPDATE running 任务（S3-15）。
        """
        jid = uuid.UUID(str(job_id))
        result = await self.session.execute(
            update(Job)
            .where(
                Job.org_id == stable_uuid(self.scope.org_id),
                Job.id == jid,
                Job.status == JobStatus.RUNNING,
            )
            .values(status=JobStatus.CANCELED, error=reason[:4000], finished_at=datetime.now(tz=UTC))
            .execution_options(synchronize_session=False)
        )
        if not result.rowcount:
            return False
        self.session.expire_all()  # Core UPDATE 绕过 ORM，身份映射需失效（sync 方法）
        return True

    async def mark_canceled_if_queued(self, job_id: str | uuid.UUID, *, reason: str = "用户取消") -> bool:
        """queued → canceled 的原子 CAS（API 直接取消未开跑的任务；与 worker 抢跑不竞态）。"""
        jid = uuid.UUID(str(job_id))
        result = await self.session.execute(
            update(Job)
            .where(
                Job.org_id == stable_uuid(self.scope.org_id),
                Job.id == jid,
                Job.status == JobStatus.QUEUED,
            )
            .values(status=JobStatus.CANCELED, error=reason[:4000], finished_at=datetime.now(tz=UTC))
            .execution_options(synchronize_session=False)
        )
        if not result.rowcount:
            return False
        self.session.expire_all()
        return True

    async def list_logs(
        self, job_id: str | uuid.UUID, *, since_seq: int = 0, limit: int = 200
    ) -> list[JobLog]:
        """``seq > since_seq`` 的增量日志（按 seq 升序），供前端 2s 轮询。"""
        jid = uuid.UUID(str(job_id))
        stmt = (
            select(JobLog)
            .where(JobLog.job_id == jid, JobLog.seq > since_seq)
            .order_by(JobLog.seq.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def active_by_kind(self, *, kind: str) -> list[Job]:
        """当前组织内某 kind 的活跃任务（queued/running），小表全取后由调用方过滤 payload。"""
        stmt = self._base().where(Job.kind == kind, Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))
        return list((await self.session.execute(stmt)).scalars().all())

    async def append_log(self, job_id: str | uuid.UUID, message: str, *, level: str = "info") -> None:
        jid = uuid.UUID(str(job_id))
        seq = int(
            (
                await self.session.execute(
                    select(func.coalesce(func.max(JobLog.seq), -1)).where(JobLog.job_id == jid)
                )
            ).scalar_one()
            + 1
        )
        self.session.add(
            JobLog(
                org_id=stable_uuid(self.scope.org_id),
                job_id=jid,
                seq=seq,
                level=level,
                message=message[:4000],
            )
        )
        await self.session.flush()


async def recover_stale_running_jobs(session, *, stale_minutes: int = 10) -> dict[str, int]:
    """R6-2：worker 启动时把孤儿 ``running`` 任务收敛回 ``queued``/``failed``。

    背景：worker 被 OOM/kill -9/容器重建时，已 ``mark_running`` 的任务不会走异常
    分支落终态，会永远卡在 ``running``，前端轮询与 ``attempts`` 都不再推进。

    判据：``status=running`` 且 ``heartbeat_at`` 早于 ``now - stale_minutes``
    （``heartbeat_at IS NULL`` 视为同样陈旧，覆盖 mark_running 后、首个 progress 前崩溃）。
    收敛：``attempts < max_attempts`` → 回 ``queued``（清 locked_by，重新可被消费）；
    否则 → ``failed``（写明原因）。

    **单副本前提**：本函数假定「原消费者已死」——dev/prod compose 的 worker 都是
    单服务、无 replicas，启动时旧进程必已退出，故安全。**扩多副本前必须改为**
    「校验 ``locked_by`` 不属于任何存活消费者（心跳表）」，否则 worker B 重启会把
    worker A 正在跑的长任务（如无 progress 检查点的 LightGBM 训练 >10min）重新入队
    导致双执行。阈值可配（``WORKER_STALE_JOB_MINUTES``），且应保证「检查点间隔 < 阈值/2」。
    """
    cutoff = datetime.now(tz=UTC) - timedelta(minutes=max(1, stale_minutes))
    stale = (Job.status == JobStatus.RUNNING) & (
        (Job.heartbeat_at.is_(None)) | (Job.heartbeat_at < cutoff)
    )
    # 可重试的回 queued；已耗尽 attempts 的落 failed
    requeued = (
        await session.execute(
            update(Job)
            .where(stale, Job.attempts < Job.max_attempts)
            .values(
                status=JobStatus.QUEUED,
                locked_by=None,
                heartbeat_at=None,
                error="worker 重启回收：上一消费者已退出，任务重新排队",
            )
            .execution_options(synchronize_session=False)
        )
    ).rowcount
    failed = (
        await session.execute(
            update(Job)
            .where(stale, Job.attempts >= Job.max_attempts)
            .values(
                status=JobStatus.FAILED,
                locked_by=None,
                heartbeat_at=None,
                error="worker 重启回收：上一消费者已退出且重试次数耗尽",
                finished_at=datetime.now(tz=UTC),
            )
            .execution_options(synchronize_session=False)
        )
    ).rowcount
    await session.commit()
    return {"requeued": int(requeued or 0), "failed": int(failed or 0)}


class BacktestRepository(BaseRepository):
    def _base(self):  # noqa: ANN202
        return select(Backtest).where(Backtest.org_id == stable_uuid(self.scope.org_id))

    async def get(self, backtest_id: str | uuid.UUID) -> Backtest | None:
        try:
            bid = uuid.UUID(str(backtest_id))
        except ValueError:
            return None
        return (await self.session.execute(self._base().where(Backtest.id == bid))).scalars().first()

    async def save_result(
        self,
        backtest_id: str | uuid.UUID,
        *,
        metrics: dict,
        data_range: dict,
        limitations: str,
        curve_uri: str | None,
        positions_uri: str | None = None,
        job_id: str | uuid.UUID | None = None,
    ) -> None:
        bt = await self.get(backtest_id)
        if bt is None:
            return
        bt.metrics = metrics
        bt.data_range = data_range
        bt.limitations = limitations
        bt.curve_uri = curve_uri or bt.curve_uri
        if positions_uri is not None:
            bt.positions_uri = positions_uri
        if job_id is not None:
            bt.job_id = uuid.UUID(str(job_id))
        await self.session.flush()

    async def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        strategy_id: str | None = None,
        project_id: str | None = None,
    ) -> tuple[list[Backtest], int]:
        offset, limit = self.page_offsets(page, page_size)
        stmt = self._base()
        if strategy_id:
            stmt = stmt.where(Backtest.strategy_id == stable_uuid(strategy_id))
        if project_id:
            stmt = stmt.where(Backtest.project_id == stable_uuid(project_id))
        total = int(
            (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        )
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(Backtest.created_at.desc()).offset(offset).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total

    async def add(self, backtest: Backtest) -> Backtest:
        self.session.add(backtest)
        await self.session.flush()
        return backtest


__all__ = ["BacktestRepository", "JobRepository", "WORKER_ID", "payload_hash"]
