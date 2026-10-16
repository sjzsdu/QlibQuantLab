"""worker handler 公共骨架：任务生命周期（queued → running → succeeded | failed | canceled）。

统一处理：加载 job（MQ payload 只带 id，**job 行才是权威**，org_id 从中取）→
校验 payload ``org_key``（外部 org 串）与 ``job.org_id`` 一致 →
mark_running（比较并交换）→ 执行 → mark_succeeded / mark_failed / mark_canceled + 日志。

阶段 5 增量（docs/stage5）：
- **独立会话日志**（D5-e）：progress 日志经 ``JobLogSink`` 每行立即提交，
  任务执行中前端轮询 ``GET /jobs/{id}/logs`` 即可见（任务表终态仍走本会话提交）；
- **progress 显式提交**：heartbeat 与 running 状态在 progress 检查点落库，
  轮询端看到真实进度（阶段 3 是 session 退出统一提交，PG 上执行中不可见）；
- **协作式取消**（D5-f）：progress 先查缓存标记 ``job:{id}:cancel``，命中抛
  ``JobCanceled`` → 落 canceled 终态并正常 ack（取消不是失败）。

org_key 由 ``JobRepository.create`` 在入队时从 API 层 scope 注入：数据目录
（``/qlib_data/{org_key}/cn_data``）与对象存储键都以它为租户前缀，必须与
API 层（``scope.org_id`` = 外部串，如 ``dev-org``）同源。
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from qqlab.core.errors import ValidationAppError
from qqlab.core.ids import stable_uuid
from qqlab.core.logging import get_logger
from qqlab.core.tenant import OrgScope
from qqlab.models import Job, JobLog
from qqlab.ports.compute import ProgressCallback
from qqlab.repositories.job import JobRepository
from qqlab.services.job_query_service import cancel_flag_key

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from qqlab.config import Settings
    from qqlab.container import Container

logger = get_logger("qqlab.worker.handlers")

#: execute(job, repo, progress) -> 结果字典
ExecuteFn = Callable[
    [Job, JobRepository, ProgressCallback],
    Awaitable[dict[str, Any]],
]


class JobCanceled(Exception):
    """协作式取消信号：progress 检查点发现取消标记时抛出，run_job 捕获落终态。"""


class JobLogSink:
    """job_logs 独立会话写入器（D5-e）：每行立即提交，执行中即可见。

    - ``seq = max+1``：worker 单并发（``QLIB_WORKER_CONCURRENCY=1``）串行写入，
      与任务会话的终态日志也是先后顺序，不会撞 ``uq_job_logs_job_seq``；
    - 写失败只告警不打断任务（日志可丢，任务不能因日志而失败）；
    - SQLite(StaticPool) 下与任务会话共用单连接——调用全程串行、每步自带提交，
      不存在交叠事务。
    """

    def __init__(self, database, *, org_id: uuid.UUID, job_id: uuid.UUID) -> None:  # noqa: ANN001
        self._database = database
        self._org_id = org_id
        self._job_id = job_id

    async def write(self, message: str, *, level: str = "info") -> None:
        try:
            async with self._database.session() as session:  # 退出即 commit
                seq = (
                    int(
                        (
                            await session.execute(
                                select(func.coalesce(func.max(JobLog.seq), -1)).where(
                                    JobLog.job_id == self._job_id
                                )
                            )
                        ).scalar_one()
                    )
                    + 1
                )
                session.add(
                    JobLog(
                        org_id=self._org_id,
                        job_id=self._job_id,
                        seq=seq,
                        level=level,
                        message=message[:4000],
                    )
                )
        except Exception:  # noqa: BLE001 - 日志失败绝不打断任务
            logger.warning(
                "job_log_sink_failed",
                extra={"job_id": str(self._job_id), "detail": message[:120]},
            )


async def run_job(
    settings: Settings,
    container: Container,
    payload: dict[str, Any],
    *,
    kind: str,
    execute: ExecuteFn,
) -> dict[str, Any]:
    """统一任务生命周期。execute 抛任何异常 → job 标记 failed 后原样上抛。"""
    job_id = payload.get("job_id")
    if not job_id:
        raise ValidationAppError(f"{kind} 任务缺少 job_id")

    async with container.database.session() as session:
        # job 自身按主键直查（MQ 消息由本平台 API 签发，job_id 可信；
        # 租户边界从 job.org_id 派生，后续一切查询都走 OrgScope 强制过滤）
        job = await session.get(Job, uuid.UUID(str(job_id)))
        if job is None:
            raise ValidationAppError(f"job {job_id} 不存在")
        if job.kind != kind:
            raise ValidationAppError(f"job {job_id} kind={job.kind!r} 与 handler {kind!r} 不匹配")

        # ---- org_key 校验（fail-closed）：外部 org 串与 job.org_id 必须同源 ----
        org_key = (job.payload or {}).get("org_key")
        if not org_key or stable_uuid(str(org_key)) != job.org_id:
            detail = (
                f"job payload 缺少 org_key 或与 job.org_id 不一致"
                f"（org_key={org_key!r}, job.org_id={job.org_id}）——入队必须经 JobRepository.create"
            )
            broken = JobRepository(session, OrgScope(org_id=str(job.org_id), user_id=str(job.created_by)))
            if await broken.mark_running(job_id):  # 状态机：queued → running → failed
                await broken.mark_failed(job_id, detail)
                await broken.append_log(job_id, f"failed: {detail}", level="error")
                await session.commit()  # 异常上抛会 rollback，失败状态先落库
            raise ValidationAppError(detail)

        # 外部 org 串做租户前缀（数据目录 / 对象存储键 / spec.org_id 与 API 层同源）
        scope = OrgScope(org_id=str(org_key), user_id=str(job.created_by))
        repo = JobRepository(session, scope)
        sink = JobLogSink(container.database, org_id=job.org_id, job_id=job.id)

        if not await repo.mark_running(job_id):
            logger.warning("job_not_queued", extra={"job_id": str(job_id), "status": job.status})
            return {"skipped": True, "reason": f"job 状态不是 queued（当前 {job.status}）"}

        # 立即提交：running 状态先行可见（轮询端不再看到假 queued；也让后续
        # 协作式取消的 CAS 判断建立在真实状态上）
        await session.commit()
        flag_key = cancel_flag_key(str(job_id))

        async def _honor_cancel(detail: str) -> dict[str, Any] | None:
            """取消标记命中 → 落 canceled 终态 + 清标记，返回终止结果。"""
            with contextlib.suppress(Exception):
                await container.cache.delete(flag_key)
            try:
                await repo.mark_canceled(job_id, reason=detail)
                await repo.append_log(job_id, f"canceled: {detail}", level="warn")
                await session.commit()
            except Exception:  # noqa: BLE001 - 终态写入失败只记录，交上层处理
                logger.exception("job_cancel_persist_failed", extra={"job_id": str(job_id)})
            logger.info("job_canceled", extra={"job_id": str(job_id), "detail": detail})
            return {"canceled": True, "job_id": str(job_id), "reason": detail}

        # 开跑前再查一次（覆盖 mark_running 之后、首个 progress 之前的取消）
        if await container.cache.get(flag_key) is not None:
            result = await _honor_cancel("用户取消（执行开始前收到标记）")
            if result is not None:  # pragma: no cover - 恒非 None
                return result

        async def progress(pct: int, message: str) -> None:
            # 1) 协作式取消检查（D5-f）：API 对 running 任务只置缓存标记
            if await container.cache.get(flag_key) is not None:
                raise JobCanceled(f"用户取消（progress={pct}% 检查点）")
            # 2) 心跳 + 显式提交：running/progress 对轮询端可见（阶段 5）
            await repo.heartbeat(job_id, progress=pct)
            await session.commit()
            # 3) 独立会话落日志（立即可见，D5-e）
            await sink.write(f"[{pct}%] {message}")
            # 注意：extra 键不能用 "message"（LogRecord 保留字段，logging 会抛
            # KeyError: Attempt to overwrite 'message' in LogRecord —— 阶段 3 实测踩过）
            logger.info("job_progress", extra={"job_id": str(job_id), "progress": pct, "detail": message})

        try:
            result = await execute(job, repo, progress)
        except JobCanceled as exc:
            canceled = await _honor_cancel(str(exc))
            return canceled if canceled is not None else {"canceled": True, "job_id": str(job_id)}
        except Exception as exc:  # noqa: BLE001 - 单任务失败不应终止消费者
            try:
                await repo.mark_failed(job_id, str(exc))
                await repo.append_log(job_id, f"failed: {exc}", level="error")
                # 显式提交：异常上抛会让 session 上下文 rollback，失败状态必须先落库
                await session.commit()
            except Exception:  # noqa: BLE001 - 终态写入失败不能吞掉原始异常
                # execute 内 flush 失败（如 JSONB 写入非法值）会把 session 置为
                # PendingRollback —— 不回滚则 mark_failed 自身抛
                # PendingRollbackError，任务永远卡在 queued（阶段 3 实测踩过）。
                # 回滚后重新登记一次拾取（回滚把 running 也撤了，CAS 仍可通过），
                # 再重试落终态；仍失败则只记日志，交由上层原样上抛原始异常。
                logger.warning("job_terminal_state_retry", extra={"job_id": str(job_id), "kind": kind})
                with contextlib.suppress(Exception):
                    await session.rollback()
                try:
                    await repo.mark_running(job_id)
                    await repo.mark_failed(job_id, str(exc))
                    await repo.append_log(job_id, f"failed: {exc}", level="error")
                    await session.commit()
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "job_terminal_state_persist_failed",
                        extra={"job_id": str(job_id), "kind": kind},
                    )
            logger.exception("job_failed_detail", extra={"job_id": str(job_id), "kind": kind})
            raise
        await repo.mark_succeeded(job_id)
        return result
