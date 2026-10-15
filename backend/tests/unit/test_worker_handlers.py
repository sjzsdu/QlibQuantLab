"""handler 端到端单测（SQLite + 内存适配器，零外部依赖）。

覆盖阶段 3 的任务链路：
1. dataset_import —— 文件系统校验 + data_sources/data_licenses/datasets 台账 seed（幂等）；
2. backtest —— stub 计算 → 结果三标注回写（metrics / data_range / limitations）；
3. 失败路径 —— 任务标 failed，错误可见。

handler 单测直接喂 ``{"job_id": ...}`` payload（生产入队一律走 ``JobService.enqueue``，
落库提交后发布 MQ 消息 —— 见 test_job_service.py）；``JobRepository.create`` 负责注入
org_key + created_by，与 API 层同源；
``run_job`` 会 fail-closed 校验 ``stable_uuid(org_key) == job.org_id``。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from conftest import make_settings
from qqlab.adapters.compute.stub_compute import StubComputeProvider
from qqlab.container import Container
from qqlab.core.ids import stable_uuid
from qqlab.core.tenant import OrgScope
from qqlab.models import (
    Backtest,
    DataLicense,
    Dataset,
    DataSource,
    Job,
    JobKind,
    JobStatus,
    MLModel,
    Organization,
    Project,
    Strategy,
    User,
)
from qqlab.ports.compute import CostConfig
from qqlab.repositories.job import JobRepository
from qqlab.worker.handlers import make_backtest_handler, make_dataset_import_handler

ORG = "dev-org"
ORG_UUID = stable_uuid(ORG)
USER = "dev-user"
USER_UUID = stable_uuid(USER)


@pytest.fixture
def settings(tmp_path: Path):
    return make_settings(
        COMPUTE_BACKEND="stub",
        QLIB_DATA_ROOT=str(tmp_path / "qlib_data"),
    )


@pytest.fixture
def container(settings) -> Container:
    return Container.build(settings)


def _scope() -> OrgScope:
    return OrgScope(org_id=ORG, user_id=USER)


def _write_fake_dataset(settings) -> Path:
    """构造 dump_bin 目录布局（qlib 未安装时走文件系统校验路径）。"""
    root = Path(settings.QLIB_DATA_ROOT) / ORG / settings.QLIB_DATA_SUBDIR
    (root / "calendars").mkdir(parents=True)
    (root / "instruments").mkdir(parents=True)
    (root / "calendars" / "day.txt").write_text("2024-01-02\n2024-01-03\n2024-01-04\n")
    (root / "instruments" / "all.txt").write_text("AAA.XSHE\tAAA\nBBB.XSHG\tBBB\n")
    return root


async def _seed_identity(container) -> None:
    """种子 Organization + User（TenantMixin.created_by 的归属对象）。"""
    async with container.database.session() as session:
        if await session.get(Organization, ORG_UUID) is None:
            session.add(Organization(id=ORG_UUID, slug="dev", name="Dev Org"))
        if await session.get(User, USER_UUID) is None:
            session.add(User(id=USER_UUID, username="dev"))
        await session.flush()


async def _add_job(container, kind: str, payload: dict) -> uuid.UUID:
    """经 JobRepository.create 入队（自动注入 org_key / created_by / payload_hash）。"""
    await _seed_identity(container)
    async with container.database.session() as session:
        job = await JobRepository(session, _scope()).create(kind=kind, payload=payload)
        return job.id


async def _get_job(container, job_id: uuid.UUID) -> Job | None:
    from sqlalchemy import select

    async with container.database.session() as session:
        stmt = select(Job).where(Job.id == job_id)
        job = (await session.execute(stmt)).scalars().first()
        if job is None:
            return None
        session.expunge(job)
        return job


async def _get_dataset(container) -> Dataset | None:
    from sqlalchemy import select

    async with container.database.session() as session:
        ds = (await session.execute(select(Dataset).where(Dataset.org_id == ORG_UUID))).scalars().first()
        if ds is None:
            return None
        session.expunge(ds)
        return ds


async def _count(container, model) -> int:  # noqa: ANN001
    from sqlalchemy import func, select

    async with container.database.session() as session:
        stmt = select(func.count()).select_from(model).where(model.org_id == ORG_UUID)
        return int((await session.execute(stmt)).scalar_one())


class TestDatasetImportHandler:
    async def test_creates_ledger_rows_idempotent(self, settings, container) -> None:
        _write_fake_dataset(settings)
        handler = make_dataset_import_handler(settings, container)

        job_id = await _add_job(container, JobKind.DATASET_IMPORT, {"region": "cn"})
        result = await handler({"job_id": str(job_id)})

        assert result["instrument_count"] == 2
        assert result["start"] == "2024-01-02"
        assert result["redistribution_allowed"] is False
        assert result["dataset_id"]

        job = await _get_job(container, job_id)
        assert job is not None and job.status == JobStatus.SUCCEEDED
        assert job.progress == 100

        # 台账三件套
        assert await _count(container, DataSource) == 1
        assert await _count(container, DataLicense) == 1
        assert await _count(container, Dataset) == 1

        license_row = None
        async with container.database.session() as session:
            from sqlalchemy import select

            license_row = (
                (await session.execute(select(DataLicense).where(DataLicense.org_id == ORG_UUID)))
                .scalars()
                .first()
            )
            assert license_row is not None
            assert license_row.redistribution_allowed is False
            assert license_row.license_ref.startswith("Yahoo Finance")

        # manifest 落对象存储
        dataset = await _get_dataset(container)
        assert dataset is not None
        manifest = await container.storage.get(f"{ORG}/datasets/{dataset.id}/manifest.json")
        parsed = json.loads(manifest)
        assert parsed["verified_via"] in ("qlib", "filesystem")
        assert parsed["instrument_count"] == 2

        # 幂等：再跑一次仍是 1/1/1
        job2 = await _add_job(container, JobKind.DATASET_IMPORT, {"region": "cn", "run": 2})
        await handler({"job_id": str(job2)})
        assert await _count(container, DataSource) == 1
        assert await _count(container, DataLicense) == 1
        assert await _count(container, Dataset) == 1

    async def test_missing_data_dir_fails_job(self, settings, container) -> None:
        """数据未导入 → 任务 failed，错误信息可读（不被掩盖）。"""
        handler = make_dataset_import_handler(settings, container)
        job_id = await _add_job(container, JobKind.DATASET_IMPORT, {})

        with pytest.raises(Exception, match="数据目录不完整|instruments"):
            await handler({"job_id": str(job_id)})

        job = await _get_job(container, job_id)
        assert job is not None and job.status == JobStatus.FAILED
        assert job.error


class TestRunJobTerminalState:
    async def test_flush_poison_still_marks_failed(self, settings, container) -> None:
        """execute 内 flush 失败（JSON 列写入 complex）→ 终态自愈，任务仍落 failed。

        阶段 3 实测回归：flush TypeError 会把 session 置为 PendingRollback，
        mark_failed 不回滚就自抛 PendingRollbackError → 任务**永远卡 queued**、
        attempts=0、终态丢失。修复：失败路径先回滚 → 重新登记拾取（attempts 不丢）
        → 重试落 failed；重试仍失败只记日志、原样上抛原始异常。
        """
        from qqlab.worker.handlers.base import run_job

        job_id = await _add_job(container, JobKind.DATASET_IMPORT, {})

        async def _poison(job, repo, progress):  # noqa: ARG001
            job.payload = {**(job.payload or {}), "_bad": complex(1, 2)}
            await repo.session.flush()  # TypeError: complex 不是合法 JSON 值
            return {}

        # flush 失败会以 sqlalchemy.exc.StatementError 包装 TypeError 上抛（内含 complex 消息）
        with pytest.raises(Exception, match="complex"):
            await run_job(
                settings,
                container,
                {"job_id": str(job_id)},
                kind=JobKind.DATASET_IMPORT,
                execute=_poison,
            )

        job = await _get_job(container, job_id)
        assert job is not None and job.status == JobStatus.FAILED
        assert job.attempts == 1  # 回滚后重新登记拾取，取证信息不丢
        assert job.error and "complex" in job.error
        assert job.finished_at is not None


class TestBacktestHandler:
    async def _seed_study_rows(self, container, cost_config: dict, params: dict) -> uuid.UUID:
        await _seed_identity(container)
        async with container.database.session() as session:
            source = DataSource(
                org_id=ORG_UUID, created_by=USER_UUID, name="seed-source", kind="yahoo_official"
            )
            session.add(source)
            await session.flush()
            license_row = DataLicense(
                org_id=ORG_UUID,
                created_by=USER_UUID,
                data_source_id=source.id,
                license_ref="seed",
                scope="internal_research",
            )
            session.add(license_row)
            await session.flush()
            dataset = Dataset(
                org_id=ORG_UUID,
                created_by=USER_UUID,
                data_source_id=source.id,
                license_id=license_row.id,
                name="seed-dataset",
                qlib_region="cn",
                freq="day",
            )
            session.add(dataset)
            await session.flush()
            project = Project(
                org_id=ORG_UUID, created_by=USER_UUID, name=f"S3 测试项目-{uuid.uuid4().hex[:8]}"
            )
            session.add(project)
            await session.flush()
            model = MLModel(
                org_id=ORG_UUID,
                created_by=USER_UUID,
                project_id=project.id,
                dataset_id=dataset.id,
                name="seed-model",
                algo="momentum",
            )
            session.add(model)
            await session.flush()
            strategy = Strategy(
                org_id=ORG_UUID,
                created_by=USER_UUID,
                project_id=project.id,
                model_id=model.id,
                name="动量策略",
                signal_config={"lookback": 5, "signal_type": "momentum", "topk": 3},
            )
            session.add(strategy)
            await session.flush()
            backtest = Backtest(
                org_id=ORG_UUID,
                created_by=USER_UUID,
                project_id=project.id,
                strategy_id=strategy.id,
                dataset_id=dataset.id,
                cost_config=cost_config,
                params=params,
            )
            session.add(backtest)
            await session.flush()
            return backtest.id

    async def test_backtest_runs_and_writes_three_annotations(self, settings, container) -> None:
        cost = CostConfig(commission_rate=0.002, slippage_value=25.0, stamp_duty_sell=0.001)
        backtest_id = await self._seed_study_rows(container, cost.to_dict(), {"topk": 3, "lookback": 5})

        compute = StubComputeProvider(container.storage)
        handler = make_backtest_handler(settings, container, compute)
        job_id = await _add_job(container, JobKind.BACKTEST, {"backtest_id": str(backtest_id)})
        result = await handler({"job_id": str(job_id), "backtest_id": str(backtest_id)})

        assert result["engine"] == "stub"
        # 成本 100% 透传：结果里的 cost_applied 与建回测时的 cost_config 逐字段相等
        assert result["cost_applied"] == cost.to_dict()

        from sqlalchemy import select

        async with container.database.session() as session:
            bt = (await session.execute(select(Backtest).where(Backtest.id == backtest_id))).scalars().first()
            assert bt is not None
            assert bt.metrics["cost_applied"] == cost.to_dict()
            assert bt.metrics["engine"] == "stub"
            assert bt.data_range["start"] <= bt.data_range["end"]
            assert bt.limitations and "stub" in bt.limitations
            assert bt.curve_uri and bt.curve_uri.endswith("stub_curve.csv")
            job = (await session.execute(select(Job).where(Job.id == job_id))).scalars().first()
            assert job is not None and job.status == JobStatus.SUCCEEDED
            assert job.progress == 100
            assert job.attempts == 1

        # 曲线真的在对象存储里
        assert await container.storage.get(result["curve_key"])

    async def test_backtest_job_without_backtest_id_fails(self, settings, container) -> None:
        compute = StubComputeProvider(container.storage)
        handler = make_backtest_handler(settings, container, compute)
        job_id = await _add_job(container, JobKind.BACKTEST, {})  # 缺 backtest_id

        with pytest.raises(Exception, match="缺少 backtest_id"):
            await handler({"job_id": str(job_id)})

        job = await _get_job(container, job_id)
        assert job is not None and job.status == JobStatus.FAILED
        assert "backtest_id" in (job.error or "")

    async def test_kind_mismatch_rejected(self, settings, container) -> None:
        compute = StubComputeProvider(container.storage)
        backtest_handler = make_backtest_handler(settings, container, compute)
        job_id = await _add_job(container, JobKind.DATASET_IMPORT, {"region": "cn"})

        with pytest.raises(Exception, match="不匹配"):
            await backtest_handler({"job_id": str(job_id)})

        # 类型不匹配发生在 mark_running 之前 → job 保持 queued（不会被误标失败）
        job = await _get_job(container, job_id)
        assert job is not None and job.status == JobStatus.QUEUED

    async def test_double_dispatch_is_skipped(self, settings, container) -> None:
        """重复消费同一条消息（重投）→ 第二次 skipped，不重复执行。"""
        cost = CostConfig()
        backtest_id = await self._seed_study_rows(container, cost.to_dict(), {"topk": 3})
        compute = StubComputeProvider(container.storage)
        handler = make_backtest_handler(settings, container, compute)
        job_id = await _add_job(container, JobKind.BACKTEST, {"backtest_id": str(backtest_id)})
        payload = {"job_id": str(job_id), "backtest_id": str(backtest_id)}

        first = await handler(payload)
        second = await handler(payload)

        assert first["engine"] == "stub"
        assert second == {"skipped": True, "reason": "job 状态不是 queued（当前 succeeded）"}
