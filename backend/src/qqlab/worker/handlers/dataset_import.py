"""数据导入 handler：校验 qlib 数据目录 + 登记/回填数据集快照。

两种模式（阶段 4 决策）：

- **更新模式**（payload 带 ``dataset_id``，阶段 4 API 路径）：数据源与授权台账
  已由 UI 创建（服务层强制合规），handler 只做目录校验 + 回填
  （instrument_count / start_date / end_date / storage_uri / status=active）；
- **种子模式**（payload 不带 ``dataset_id``，阶段 3 smoke 与既有测试兼容）：
  幂等 upsert 1 条 data_sources（yahoo_official）+ 1 条 data_licenses（禁止再分发）
  + 1 条 datasets。

校验优先走 qlib（与回测同一条取数路径）；worker 未装 qlib（stub 环境）时
降级为**文件系统解析**（calendars/instruments 目录），两种路径结果同形。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from qqlab.core.errors import NotFoundError, ValidationAppError
from qqlab.core.ids import stable_uuid
from qqlab.core.logging import get_logger
from qqlab.models import DataLicense, Dataset, DataSource
from qqlab.repositories.job import JobRepository
from qqlab.worker.handlers.base import run_job

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from qqlab.config import Settings
    from qqlab.container import Container
    from qqlab.models import Job

logger = get_logger("qqlab.worker.dataset_import")

#: 平台不内置未授权数据：这条台账记录的语义是「Yahoo 公开数据，研究用途，禁止再分发」
SOURCE_NAME = "Yahoo Finance（经 qlib 官方脚本导入）"
LICENSE_REF = "Yahoo Finance Terms of Service — 公开行情，仅供研究，禁止再分发原始数据"


def probe_dataset(settings: Settings, org_id: str) -> dict[str, Any]:
    """校验数据可用性并返回快照（instrument_count / start / end / via）。

    优先走 qlib（与回测同一条取数路径）；worker 未装 qlib（stub 环境）时
    降级为文件系统解析。数据缺失在两条路径下都是**失败**，不会被掩盖。
    """
    from qqlab.worker.qlib_env import data_dir_for, probe_dataset_via_qlib  # noqa: PLC0415

    try:
        return probe_dataset_via_qlib(settings, org_id)
    except ImportError:
        return _probe_filesystem(Path(data_dir_for(settings, org_id)))


def _probe_filesystem(data_root: Path) -> dict[str, Any]:
    calendar = data_root / "calendars" / "day.txt"
    instruments = data_root / "instruments" / "all.txt"
    if not calendar.exists() or not instruments.exists():
        raise ValidationAppError(
            f"数据目录不完整：{data_root}（缺少 calendars/day.txt 或 instruments/all.txt；"
            "先执行 make qlib-data 导入数据）"
        )
    cal_lines = [line.strip() for line in calendar.read_text().splitlines() if line.strip()]
    inst_lines = [line.strip() for line in instruments.read_text().splitlines() if line.strip()]
    if not cal_lines or not inst_lines:
        raise ValidationAppError(f"数据目录内容为空：{data_root}")
    return {
        "instrument_count": len(inst_lines),
        "start": cal_lines[0],
        "end": cal_lines[-1],
        "via": "filesystem",
    }


async def _write_manifest(
    container: Container, job: Job, dataset: Dataset, stats: dict[str, Any], org_key: str
) -> None:
    region = str((job.payload or {}).get("region") or dataset.qlib_region)
    manifest = {
        "org_id": org_key,
        "dataset_id": str(dataset.id),
        "region": region,
        "freq": dataset.freq,
        "instrument_count": int(stats["instrument_count"]),
        "start": stats["start"],
        "end": stats["end"],
        "verified_via": stats["via"],
        "license_ref": None,  # 更新模式：台账在 UI 登记，manifest 只记数据事实
        "imported_at": datetime.now(tz=UTC).isoformat(),
    }
    manifest_key = f"{org_key}/datasets/{dataset.id}/manifest.json"
    await container.storage.put(
        manifest_key,
        json.dumps(manifest, ensure_ascii=False, indent=2).encode(),
        content_type="application/json",
    )


async def _apply_stats(dataset: Dataset, stats: dict[str, Any], storage_uri: str) -> None:
    dataset.instrument_count = int(stats["instrument_count"])
    dataset.start_date = datetime.fromisoformat(stats["start"]).date()
    dataset.end_date = datetime.fromisoformat(stats["end"]).date()
    if not dataset.storage_uri:
        dataset.storage_uri = storage_uri
    dataset.status = "active"


async def _execute_update_mode(
    settings: Settings,
    container: Container,
    job: Job,
    repo: JobRepository,
    progress,  # noqa: ANN001 - ProgressCallback
    stats: dict[str, Any],
) -> dict[str, Any]:
    """阶段 4 路径：目录校验 + 回填既有数据集行（fail-closed org 边界）。"""
    from qqlab.worker.qlib_env import data_dir_for  # noqa: PLC0415

    session = repo.session
    scope = repo.scope
    dataset_id = str(job.payload.get("dataset_id") or "")
    try:
        did = stable_uuid(dataset_id)
    except ValueError as exc:
        raise NotFoundError(f"数据集不存在或不属于当前组织：{dataset_id}") from exc
    dataset = (
        (
            await session.execute(
                select(Dataset).where(Dataset.org_id == stable_uuid(scope.org_id), Dataset.id == did)
            )
        )
        .scalars()
        .first()
    )
    if dataset is None:
        raise NotFoundError(f"数据集不存在或不属于当前组织：{dataset_id}")

    await progress(60, "回填数据集快照")
    await _apply_stats(dataset, stats, data_dir_for(settings, scope.org_id))
    await session.flush()

    await _write_manifest(container, job, dataset, stats, scope.org_id)
    await repo.append_log(
        job.id,
        f"数据集就绪 via={stats['via']} instruments={stats['instrument_count']} "
        f"range={stats['start']}~{stats['end']}",
    )
    logger.info("dataset_updated", extra={"dataset_id": str(dataset.id), **stats})
    return {"dataset_id": str(dataset.id), "mode": "update", "instrument_count": stats["instrument_count"]}


async def _execute_seed_mode(
    settings: Settings,
    container: Container,
    job: Job,
    repo: JobRepository,
    progress,  # noqa: ANN001 - ProgressCallback
    stats: dict[str, Any],
) -> dict[str, Any]:
    """阶段 3 路径（smoke 兼容）：幂等 upsert 数据源 + 台账 + 数据集。"""
    from qqlab.worker.qlib_env import data_dir_for  # noqa: PLC0415

    payload = job.payload or {}
    scope = repo.scope
    session = repo.session
    region = str(payload.get("region") or settings.QLIB_REGION)
    dataset_name = str(payload.get("dataset_name") or f"{region} 日线（Yahoo 公开数据）")

    await progress(40, "登记数据源（幂等 upsert）")
    org = stable_uuid(scope.org_id)
    source = (
        (
            await session.execute(
                select(DataSource).where(DataSource.org_id == org, DataSource.name == SOURCE_NAME)
            )
        )
        .scalars()
        .first()
    )
    if source is None:
        source = DataSource(
            org_id=org,
            created_by=job.created_by,  # 审计归属：谁入队的导入任务
            name=SOURCE_NAME,
            kind="yahoo_official",
            vendor="Yahoo Finance",
            homepage="https://finance.yahoo.com",
            notes="经 qlib 官方 get_data.py + dump_bin 导入；平台不内置未授权行情数据。",
        )
        session.add(source)
        await session.flush()

    await progress(60, "登记授权台账（禁止再分发）")
    license_row = (
        (
            await session.execute(
                select(DataLicense).where(
                    DataLicense.org_id == org,
                    DataLicense.data_source_id == source.id,
                    DataLicense.license_ref == LICENSE_REF,
                )
            )
        )
        .scalars()
        .first()
    )
    if license_row is None:
        license_row = DataLicense(
            org_id=org,
            created_by=job.created_by,
            data_source_id=source.id,
            scope="internal_research",
            license_ref=LICENSE_REF,
            allowed_use="internal research only（回测 / 因子研究 / 可视化）",
            redistribution_allowed=False,
            granted_by="platform-default",
            granted_at=datetime.now(tz=UTC),
        )
        session.add(license_row)
        await session.flush()

    await progress(80, "写入数据集快照")
    storage_uri = data_dir_for(settings, scope.org_id)
    dataset = (
        (
            await session.execute(
                select(Dataset).where(Dataset.org_id == org, Dataset.storage_uri == storage_uri)
            )
        )
        .scalars()
        .first()
    )
    if dataset is None:
        dataset = Dataset(
            org_id=org,
            created_by=job.created_by,
            project_id=None,
            data_source_id=source.id,
            license_id=license_row.id,
            name=dataset_name,
            qlib_region=region,
            freq="day",
            storage_uri=storage_uri,  # 幂等键：同目录重复导入不新增行
        )
        session.add(dataset)
        await session.flush()
    await _apply_stats(dataset, stats, storage_uri)
    await session.flush()

    manifest = {
        "org_id": scope.org_id,
        "dataset_id": str(dataset.id),
        "region": region,
        "freq": "day",
        "instrument_count": stats["instrument_count"],
        "start": stats["start"],
        "end": stats["end"],
        "verified_via": stats["via"],
        "license_ref": LICENSE_REF,
        "redistribution_allowed": False,
        "imported_at": datetime.now(tz=UTC).isoformat(),
    }
    manifest_key = f"{scope.org_id}/datasets/{dataset.id}/manifest.json"
    await container.storage.put(
        manifest_key,
        json.dumps(manifest, ensure_ascii=False, indent=2).encode(),
        content_type="application/json",
    )

    await repo.append_log(
        job.id,
        f"数据集就绪 via={stats['via']} instruments={stats['instrument_count']} "
        f"range={stats['start']}~{stats['end']}",
    )
    logger.info("dataset_registered", extra={"dataset_id": str(dataset.id), **stats})
    return {"dataset_id": str(dataset.id), "mode": "seed", **manifest}


async def _execute(
    settings: Settings,
    container: Container,
    job: Job,
    repo: JobRepository,
    progress,  # noqa: ANN001 - ProgressCallback
) -> dict[str, Any]:
    payload = job.payload or {}
    await progress(10, "校验 qlib 数据目录")
    stats = probe_dataset(settings, repo.scope.org_id)
    if payload.get("dataset_id"):
        return await _execute_update_mode(settings, container, job, repo, progress, stats)
    return await _execute_seed_mode(settings, container, job, repo, progress, stats)


def make_dataset_import_handler(settings: Settings, container: Container):  # noqa: ANN201
    async def handle(payload: dict[str, Any]) -> dict[str, Any]:
        return await run_job(
            settings,
            container,
            payload,
            kind="dataset_import",
            execute=lambda job, repo, progress: _execute(settings, container, job, repo, progress),
        )

    return handle
