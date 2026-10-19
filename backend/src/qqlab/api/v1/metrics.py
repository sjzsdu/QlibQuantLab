"""Prometheus 指标端点（阶段 8 · D8-1/D8-2）：``GET /api/v1/metrics``。

三分法（D8-2）的后两类在 **scrape 时现查**，第一类（HTTP RED）由
``app.state.metrics`` 进程内注册表渲染（见 qqlab.core.metrics）：

- **队列**（jobs 表，``METRICS_QUEUE_WINDOW_HOURS`` 滑动窗口）：深度按 kind/status
  分组现值；窗口内完成量按 kind/status 分组（失败率 = failed/succeeded+failed
  在 PromQL 里现算）；时长与排队等待取窗口内样本的 avg/p95 —— 用 **gauge** 而非
  histogram，因为分桶是滑动窗口、不是单调累计，冒充 histogram 会骗过
  ``histogram_quantile``/``rate``；
- **worker**（CacheProvider，单副本固定键）：心跳年龄 → ``qqlab_worker_up``，
  回收计数（缓存丢失即归零，HELP 里写明）。

鉴权（D8-1）：dev/test 免鉴权；生产要求 ``METRICS_TOKEN``（空 = fail-closed 404，
不给探测面），校验 ``Authorization: Bearer`` 或 ``X-Metrics-Token``。
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from qqlab.api.deps import get_db_session, get_settings
from qqlab.config import Settings
from qqlab.core.errors import NotFoundError, UnauthorizedError
from qqlab.core.logging import get_logger
from qqlab.models import Job, JobStatus

logger = get_logger("qqlab.metrics")

router = APIRouter(tags=["system"])

_MEDIA_TYPE = "text/plain; version=0.0.4; charset=utf-8"

#: 时长/等待样本上限（按完成时间倒序取窗口内）—— 防窗口内任务暴增时 Python 端爆内存
_SAMPLE_LIMIT = 5000

#: 单次 scrape 中单个分组的样本下限：样本太少时 p95 没有统计意义，只出 avg
_MIN_SAMPLES_FOR_QUANTILE = 5

_COMPLETED = (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELED)


def _aware(value: datetime | None) -> datetime | None:
    """sqlite 返回 naive UTC，补回时区（列是 DateTime(timezone=True)）。"""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _seconds(before: datetime | None, after: datetime | None) -> float | None:
    b, a = _aware(before), _aware(after)
    if b is None or a is None:
        return None
    return max(0.0, (a - b).total_seconds())


async def _queue_lines(session: AsyncSession, settings: Settings) -> list[str]:
    """队列三分量：深度（现值）/ 窗口完成量 / 时长与等待 avg+p95。"""
    window_start = datetime.now(UTC) - timedelta(hours=max(1, settings.METRICS_QUEUE_WINDOW_HOURS))
    lines: list[str] = []

    depth = (
        await session.execute(
            select(Job.kind, Job.status, func.count())
            .where(Job.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)))
            .group_by(Job.kind, Job.status)
        )
    ).all()
    lines.append("# HELP qqlab_jobs_depth 当前队列深度（queued/running 现值，按 kind）")
    lines.append("# TYPE qqlab_jobs_depth gauge")
    for kind, status, count in depth:
        lines.append(f'qqlab_jobs_depth{{kind="{kind}",status="{status}"}} {count}')

    finished = (
        await session.execute(
            select(Job.kind, Job.status, func.count())
            .where(Job.status.in_(_COMPLETED), Job.finished_at >= window_start)
            .group_by(Job.kind, Job.status)
        )
    ).all()
    lines.append(
        f"# HELP qqlab_jobs_finished_window 最近 {settings.METRICS_QUEUE_WINDOW_HOURS}h 完成的任务数"
        "（失败率 PromQL 现算：failed/(succeeded+failed)）"
    )
    lines.append("# TYPE qqlab_jobs_finished_window gauge")
    for kind, status, count in finished:
        lines.append(f'qqlab_jobs_finished_window{{kind="{kind}",status="{status}"}} {count}')

    samples = (
        await session.execute(
            select(Job.kind, Job.created_at, Job.started_at, Job.finished_at)
            .where(Job.status.in_((JobStatus.SUCCEEDED, JobStatus.FAILED)), Job.finished_at >= window_start)
            .order_by(Job.finished_at.desc())
            .limit(_SAMPLE_LIMIT)
        )
    ).all()

    by_kind: dict[str, dict[str, list[float]]] = {}
    for kind, created, started, finished_at in samples:
        duration = _seconds(started, finished_at)
        wait = _seconds(created, started)
        bucket = by_kind.setdefault(kind, {"duration": [], "wait": []})
        if duration is not None:
            bucket["duration"].append(duration)
        if wait is not None:
            bucket["wait"].append(wait)

    seen_families: set[str] = set()  # 同族 HELP/TYPE 只发一次（跨 kind）
    for kind in sorted(by_kind):
        for metric, values in by_kind[kind].items():
            if not values:
                continue
            label = "执行时长" if metric == "duration" else "排队等待"
            values.sort()
            avg = sum(values) / len(values)
            avg_family = f"qqlab_job_{metric}_seconds_avg"
            if avg_family not in seen_families:  # HELP/TYPE 每个指标族只发一次（规范要求）
                seen_families.add(avg_family)
                lines.append(f"# HELP {avg_family} 窗口内完成任务的{label}均值（秒，gauge 滑动窗口）")
                lines.append(f"# TYPE {avg_family} gauge")
            lines.append(f'{avg_family}{{kind="{kind}"}} {avg:.3f}')
            if len(values) >= _MIN_SAMPLES_FOR_QUANTILE:
                idx = min(len(values) - 1, int(0.95 * (len(values) - 1)))
                p95_family = f"qqlab_job_{metric}_seconds_p95"
                if p95_family not in seen_families:
                    seen_families.add(p95_family)
                    lines.append(f"# HELP {p95_family} 窗口内完成任务的{label}p95（秒，gauge 滑动窗口）")
                    lines.append(f"# TYPE {p95_family} gauge")
                lines.append(f'{p95_family}{{kind="{kind}"}} {values[idx]:.3f}')
    return lines


async def _worker_lines(cache, settings: Settings) -> list[str]:  # noqa: ANN001 - CacheProvider
    """worker 心跳与回收计数（CacheProvider 固定键，单副本语义）。"""
    from qqlab.core.worker_heartbeat import (  # noqa: PLC0415 - 局部 import：渲染期再取键常量
        RECYCLED_KEY,
        heartbeat_age,
    )

    lines: list[str] = []
    age = await heartbeat_age(cache, interval=settings.WORKER_HEARTBEAT_INTERVAL_SECONDS)
    up = 1 if age is not None and age <= settings.WORKER_HEARTBEAT_INTERVAL_SECONDS * 3 else 0
    lines.append("# HELP qqlab_worker_up worker 心跳存活（1=3 倍间隔内有心跳，0=无/过期）")
    lines.append("# TYPE qqlab_worker_up gauge")
    lines.append(f"qqlab_worker_up {up}")
    if age is not None:
        lines.append("# HELP qqlab_worker_heartbeat_age_seconds 最近一次 worker 心跳距今秒数")
        lines.append("# TYPE qqlab_worker_heartbeat_age_seconds gauge")
        lines.append(f"qqlab_worker_heartbeat_age_seconds {age:.1f}")

    raw = await cache.get(RECYCLED_KEY)
    try:
        recycled = int(raw) if raw is not None else 0
    except ValueError:
        recycled = 0
    lines.append(
        "# HELP qqlab_worker_recycled_total worker 启动时回收的孤儿任务累计数"
        "（存 CacheProvider：缓存丢失/未启动即归零）"
    )
    lines.append("# TYPE qqlab_worker_recycled_total counter")
    lines.append(f"qqlab_worker_recycled_total {recycled}")
    return lines


@router.get("/metrics", summary="Prometheus 指标（文本 exposition 0.0.4）", response_class=Response)
async def metrics(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    if not settings.METRICS_ENABLED:
        raise NotFoundError("指标端点未启用")
    if settings.is_production:
        token = settings.METRICS_TOKEN
        if not token:
            # fail-closed：生产没配 token = 端点不存在（不暴露探测面）
            raise NotFoundError("指标端点未启用")
        provided = request.headers.get("x-metrics-token", "")
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer ") and not provided:
            provided = auth[7:].strip()
        if not provided or not secrets.compare_digest(provided, token):
            raise UnauthorizedError("指标端点 token 无效")

    container = request.app.state.container
    lines = list(request.app.state.metrics.render())
    try:
        lines += await _queue_lines(session, settings)
        scrape_ok = True
    except Exception:  # noqa: BLE001 - scrape 失败不让整个端点 500（其余指标仍可读）
        logger.exception("queue_metrics_scrape_failed")
        scrape_ok = False
    lines.append("# HELP qqlab_queue_scrape_ok 队列指标 scrape 是否成功（0=失败，看日志）")
    lines.append("# TYPE qqlab_queue_scrape_ok gauge")
    lines.append(f"qqlab_queue_scrape_ok {1 if scrape_ok else 0}")

    try:
        lines += await _worker_lines(container.cache, settings)
        worker_ok = True
    except Exception:  # noqa: BLE001 - 同上
        logger.exception("worker_metrics_scrape_failed")
        worker_ok = False
    lines.append("# HELP qqlab_worker_scrape_ok worker 指标 scrape 是否成功（0=失败，看日志）")
    lines.append("# TYPE qqlab_worker_scrape_ok gauge")
    lines.append(f"qqlab_worker_scrape_ok {1 if worker_ok else 0}")

    return Response(content="\n".join(lines) + "\n", media_type=_MEDIA_TYPE)
