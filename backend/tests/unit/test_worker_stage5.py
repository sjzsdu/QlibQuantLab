"""阶段 5 worker 单测：训练 handler + 模型信号回测 + 取消状态机 + 增量日志。

对应 docs/stage5 决策：
- D5-e 独立会话日志：progress 日志经 JobLogSink 立即提交，seq 连续唯一；
- D5-f 取消双通道：queued → 原子 CAS；running → 缓存标记 + progress 检查点协作式；
- D5-6 artifact 口径：训练产物落对象存储，模型信号回测从 artifact_uri 读回。
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

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
    JobLog,
    JobStatus,
    MLModel,
    Organization,
    Project,
    Strategy,
    TrainingRun,
    User,
)
from qqlab.ports.compute import CostConfig
from qqlab.repositories.job import JobRepository
from qqlab.services.job_query_service import cancel_flag_key
from qqlab.worker.handlers import (
    make_backtest_handler,
    make_train_handler,
)
from qqlab.worker.handlers.base import run_job

ORG = "dev-org"
ORG_UUID = stable_uuid(ORG)
USER = "dev-user"
USER_UUID = stable_uuid(USER)

SPLIT = {"train": ["2023-01-03", "2023-06-30"], "valid": ["2023-07-03", "2023-12-29"]}
FACTOR_SNAPSHOT = [
    {
        "factor_id": str(uuid.uuid4()),
        "name": "mom5",
        "expression": "$close / Ref($close, 5) - 1",
        "version": 1,
        "factor_type": "expression",
    }
]


@pytest.fixture
def settings(tmp_path):
    from sqlalchemy import create_engine

    from qqlab.models import Base

    db_file = tmp_path / "stage5-handlers.db"
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)
    engine.dispose()
    return make_settings(
        COMPUTE_BACKEND="stub",
        QLIB_DATA_ROOT=str(tmp_path / "qlib_data"),
        DATABASE_URL=f"sqlite+aiosqlite:///{db_file}",
    )


@pytest.fixture
def container(settings) -> Container:
    return Container.build(settings)


def _scope() -> OrgScope:
    return OrgScope(org_id=ORG, user_id=USER)


async def _seed_identity(container) -> None:
    async with container.database.session() as session:
        if await session.get(Organization, ORG_UUID) is None:
            session.add(Organization(id=ORG_UUID, slug="dev", name="Dev Org"))
        if await session.get(User, USER_UUID) is None:
            session.add(User(id=USER_UUID, username="dev"))
        await session.flush()


async def _add_job(container, kind: str, payload: dict) -> uuid.UUID:
    await _seed_identity(container)
    async with container.database.session() as session:
        job = await JobRepository(session, _scope()).create(kind=kind, payload=payload)
        return job.id


async def _get_job(container, job_id: uuid.UUID) -> Job | None:
    from sqlalchemy import select

    async with container.database.session() as session:
        job = (await session.execute(select(Job).where(Job.id == job_id))).scalars().first()
        if job is None:
            return None
        session.expunge(job)
        return job


async def _get_logs(container, job_id: uuid.UUID) -> list[JobLog]:
    from sqlalchemy import select

    async with container.database.session() as session:
        stmt = select(JobLog).where(JobLog.job_id == job_id).order_by(JobLog.seq.asc())
        return list((await session.execute(stmt)).scalars().all())


async def _seed_study(container) -> dict:
    """种子 数据源(带 vendor)/授权/数据集(带区间)/项目/模型/训练记录。返回引用集。"""
    await _seed_identity(container)
    async with container.database.session() as session:
        source = DataSource(
            org_id=ORG_UUID, created_by=USER_UUID, name="seed-source", kind="market", vendor="SeedVendor"
        )
        session.add(source)
        await session.flush()
        license_row = DataLicense(
            org_id=ORG_UUID,
            created_by=USER_UUID,
            data_source_id=source.id,
            license_ref="seed-license",
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
            start_date=date(2023, 1, 3),
            end_date=date(2023, 12, 29),
        )
        session.add(dataset)
        await session.flush()
        project = Project(org_id=ORG_UUID, created_by=USER_UUID, name=f"S5 项目-{uuid.uuid4().hex[:6]}")
        session.add(project)
        await session.flush()
        model = MLModel(
            org_id=ORG_UUID,
            created_by=USER_UUID,
            project_id=project.id,
            dataset_id=dataset.id,
            name="seed-lgb",
            algo="lgb",
            hyperparams={"n_estimators": 50},
            training_config={"target": "Ref($close, -1) / $close - 1"},
            factor_snapshot=FACTOR_SNAPSHOT,
            status="training",
        )
        session.add(model)
        await session.flush()
        run = TrainingRun(
            org_id=ORG_UUID,
            created_by=USER_UUID,
            project_id=project.id,
            model_id=model.id,
            dataset_id=dataset.id,
            metrics={},
            data_range={},
        )
        session.add(run)
        await session.flush()
        return {
            "dataset_id": dataset.id,
            "project_id": project.id,
            "model_id": model.id,
            "run_id": run.id,
        }


def _train_payload(refs: dict) -> dict:
    return {
        "training_run_id": str(refs["run_id"]),
        "model_id": str(refs["model_id"]),
        "dataset_id": str(refs["dataset_id"]),
        "project_id": str(refs["project_id"]),
        "algo": "lgb",
        "hyperparams": {"n_estimators": 50},
        "target": "Ref($close, -1) / $close - 1",
        "factors": FACTOR_SNAPSHOT,
        "split": SPLIT,
        "max_instruments": 0,
    }


class TestTrainHandler:
    async def test_train_end_to_end(self, settings, container) -> None:
        refs = await _seed_study(container)
        handler = make_train_handler(settings, container, StubComputeProvider(container.storage))
        job_id = await _add_job(container, JobKind.TRAIN, _train_payload(refs))

        result = await handler({"job_id": str(job_id)})

        assert result["engine"] == "stub"
        assert result["artifact_key"].endswith("stub_model.pkl")
        assert result["model_id"] == str(refs["model_id"])

        from sqlalchemy import select

        async with container.database.session() as session:
            run = (
                (await session.execute(select(TrainingRun).where(TrainingRun.id == refs["run_id"])))
                .scalars()
                .first()
            )
            assert run is not None
            assert run.metrics["engine"] == "stub"
            assert run.metrics["n_factors"] == 1
            assert run.artifact_uri and run.artifact_uri.endswith("stub_model.pkl")
            assert run.finished_at is not None and run.started_at is not None
            assert run.job_id == job_id
            # 四标注：切分 + 数据来源授权 + limitations 全在 data_range
            assert run.data_range["train"] == SPLIT["train"]
            assert run.data_range["valid"] == SPLIT["valid"]
            assert run.data_range["source"]["vendor"] == "SeedVendor"
            assert run.data_range["source"]["license_ref"] == "seed-license"
            assert run.data_range["limitations"]
            model = (
                (await session.execute(select(MLModel).where(MLModel.id == refs["model_id"])))
                .scalars()
                .first()
            )
            assert model is not None and model.status == "trained"

        job = await _get_job(container, job_id)
        assert job is not None and job.status == JobStatus.SUCCEEDED
        assert job.progress == 100

        # artifact 真的在对象存储里（handler 统一落，D5-6）
        assert await container.storage.get(result["artifact_key"])

        # 增量日志：seq 从 0 连续唯一，且含独立 sink 写入的进度行
        logs = await _get_logs(container, job_id)
        assert [log.seq for log in logs] == list(range(len(logs)))
        assert any("%]" in log.message for log in logs)

    async def test_train_missing_factors_fails(self, settings, container) -> None:
        refs = await _seed_study(container)
        handler = make_train_handler(settings, container, StubComputeProvider(container.storage))
        payload = {**_train_payload(refs), "factors": []}
        job_id = await _add_job(container, JobKind.TRAIN, payload)

        with pytest.raises(Exception, match="缺少因子"):
            await handler({"job_id": str(job_id)})

        job = await _get_job(container, job_id)
        assert job is not None and job.status == JobStatus.FAILED

    async def test_train_missing_run_fails(self, settings, container) -> None:
        refs = await _seed_study(container)
        handler = make_train_handler(settings, container, StubComputeProvider(container.storage))
        payload = {**_train_payload(refs), "training_run_id": str(uuid.uuid4())}
        job_id = await _add_job(container, JobKind.TRAIN, payload)

        with pytest.raises(Exception, match="training_run"):
            await handler({"job_id": str(job_id)})

        job = await _get_job(container, job_id)
        assert job is not None and job.status == JobStatus.FAILED

    async def test_retry_relinks_run_to_current_job(self, settings, container) -> None:
        """重试任务（D5-12 复制 payload 换新 job_id）执行后，run 必须改链到当前任务。

        实机回归（阶段 5）：旧口径 ``run.job_id = run.job_id or job.id`` 让 run 永久
        关联最初的（已取消）任务 → 列表/详情 join 出 `job_status=canceled`，尽管重试
        已成功、metrics/artifact 都已回写（见 05-testing §4）。
        """
        refs = await _seed_study(container)
        handler = make_train_handler(settings, container, StubComputeProvider(container.storage))
        first = await _add_job(container, JobKind.TRAIN, _train_payload(refs))
        await handler({"job_id": str(first)})

        # 重试 = 复制 payload + retry_of（新 job_id、同 training_run_id）
        retry = await _add_job(
            container, JobKind.TRAIN, {**_train_payload(refs), "retry_of": str(first)}
        )
        result = await handler({"job_id": str(retry)})
        assert result["engine"] == "stub"

        from sqlalchemy import select

        async with container.database.session() as session:
            run = (
                (await session.execute(select(TrainingRun).where(TrainingRun.id == refs["run_id"])))
                .scalars()
                .first()
            )
            assert run is not None
            assert run.job_id == retry  # 关联当前执行任务，而非最初的 first

        job = await _get_job(container, retry)
        assert job is not None and job.status == JobStatus.SUCCEEDED


class TestBacktestModelSignal:
    async def _seed_model_backtest(self, container, *, with_run: bool) -> uuid.UUID:
        refs = await _seed_study(container)
        async with container.database.session() as session:
            strategy = Strategy(
                org_id=ORG_UUID,
                created_by=USER_UUID,
                project_id=refs["project_id"],
                model_id=refs["model_id"],
                name="模型信号策略",
                signal_config={"source": "model", "lookback": 5},
            )
            session.add(strategy)
            await session.flush()
            backtest = Backtest(
                org_id=ORG_UUID,
                created_by=USER_UUID,
                project_id=refs["project_id"],
                strategy_id=strategy.id,
                dataset_id=refs["dataset_id"],
                cost_config=CostConfig(commission_rate=0.002, slippage_value=25.0).to_dict(),
                params={"topk": 3},
            )
            session.add(backtest)
            await session.flush()
            backtest_id = backtest.id
        if with_run:
            # 训练成功 + artifact 落对象存储（模型信号回测读回）
            async with container.database.session() as session:
                from sqlalchemy import select

                run = (
                    (await session.execute(select(TrainingRun).where(TrainingRun.id == refs["run_id"])))
                    .scalars()
                    .first()
                )
                assert run is not None
                run.artifact_uri = f"{ORG}/experiments/{refs['project_id']}/{refs['model_id']}/stub_model.pkl"
                await session.flush()
            await container.storage.put(run.artifact_uri, b"stub-artifact")
        return backtest_id

    async def test_model_signal_backtest_succeeds(self, settings, container) -> None:
        backtest_id = await self._seed_model_backtest(container, with_run=True)
        compute = StubComputeProvider(container.storage)
        handler = make_backtest_handler(settings, container, compute)
        job_id = await _add_job(container, JobKind.BACKTEST, {"backtest_id": str(backtest_id)})

        result = await handler({"job_id": str(job_id)})

        assert result["engine"] == "stub"
        assert result["signal_source"] == "model"

        from sqlalchemy import select

        async with container.database.session() as session:
            bt = (await session.execute(select(Backtest).where(Backtest.id == backtest_id))).scalars().first()
            assert bt is not None
            assert bt.metrics["signal_source"] == "model"
            assert bt.data_range["signal_source"] == "model"
            assert bt.data_range["training_run_id"]
            assert bt.data_range["source"]["vendor"] == "SeedVendor"  # 四标注第 4 项
            assert bt.limitations and "模型" in bt.limitations
            assert bt.curve_uri and "stub_curve" in bt.curve_uri
        assert await container.storage.get(result["curve_key"])

    async def test_model_signal_without_run_fails(self, settings, container) -> None:
        backtest_id = await self._seed_model_backtest(container, with_run=False)
        compute = StubComputeProvider(container.storage)
        handler = make_backtest_handler(settings, container, compute)
        job_id = await _add_job(container, JobKind.BACKTEST, {"backtest_id": str(backtest_id)})

        with pytest.raises(Exception, match="成功训练"):
            await handler({"job_id": str(job_id)})

        job = await _get_job(container, job_id)
        assert job is not None and job.status == JobStatus.FAILED


class TestCancelStateMachine:
    """D5-f：queued 直接 CAS；running 只走缓存标记（绝不 UPDATE jobs）。"""

    async def test_queued_cancel_cas(self, settings, container) -> None:
        job_id = await _add_job(container, JobKind.BACKTEST, {"backtest_id": "x"})
        async with container.database.session() as session:
            repo = JobRepository(session, _scope())
            assert await repo.mark_canceled_if_queued(job_id) is True
            await session.commit()
        job = await _get_job(container, job_id)
        assert job is not None and job.status == JobStatus.CANCELED
        # 二次 CAS 失败（已不是 queued）
        async with container.database.session() as session:
            repo = JobRepository(session, _scope())
            assert await repo.mark_canceled_if_queued(job_id) is False

    async def test_running_cancel_cas(self, settings, container) -> None:
        job_id = await _add_job(container, JobKind.BACKTEST, {"backtest_id": "x"})
        async with container.database.session() as session:
            repo = JobRepository(session, _scope())
            assert await repo.mark_running(job_id) is True
            await session.commit()
        async with container.database.session() as session:
            repo = JobRepository(session, _scope())
            assert await repo.mark_canceled(job_id, reason="用户取消（progress 检查点）") is True
            await session.commit()
        job = await _get_job(container, job_id)
        assert job is not None and job.status == JobStatus.CANCELED
        assert "用户取消" in (job.error or "")

    async def test_pre_execute_flag_honored(self, settings, container) -> None:
        """mark_running 后、execute 前收到取消标记 → 不执行直接落 canceled。"""
        job_id = await _add_job(container, JobKind.BACKTEST, {"backtest_id": "x"})
        await container.cache.set(cancel_flag_key(str(job_id)), b"1", ttl=60)
        called = False

        async def execute(job, repo, progress):  # noqa: ARG001
            nonlocal called
            called = True
            return {}

        result = await run_job(
            settings, container, {"job_id": str(job_id)}, kind=JobKind.BACKTEST, execute=execute
        )
        assert result["canceled"] is True
        assert called is False
        job = await _get_job(container, job_id)
        assert job is not None and job.status == JobStatus.CANCELED
        # 标记被消费（清理），避免残留
        assert await container.cache.get(cancel_flag_key(str(job_id))) is None

    async def test_progress_checkpoint_cancel(self, settings, container) -> None:
        """running 中置标记 → 下个 progress 检查点抛 JobCanceled → 落 canceled 且不抛错。"""
        job_id = await _add_job(container, JobKind.BACKTEST, {"backtest_id": "x"})

        async def execute(job, repo, progress):
            await progress(10, "第一步")
            await container.cache.set(cancel_flag_key(str(job.id)), b"1", ttl=60)
            await progress(20, "第二步")  # 检查点命中 → JobCanceled
            return {}  # pragma: no cover

        result = await run_job(
            settings, container, {"job_id": str(job_id)}, kind=JobKind.BACKTEST, execute=execute
        )
        assert result["canceled"] is True
        job = await _get_job(container, job_id)
        assert job is not None and job.status == JobStatus.CANCELED
        logs = await _get_logs(container, job_id)
        assert any("canceled" in log.message for log in logs)
        assert [log.seq for log in logs] == list(range(len(logs)))  # seq 连续唯一


class TestIncrementalLogs:
    async def test_progress_logs_visible_with_contiguous_seq(self, settings, container) -> None:
        """D5-e：progress 日志独立会话提交 —— 任务未终态时已可读。"""
        job_id = await _add_job(container, JobKind.BACKTEST, {"backtest_id": "x"})
        observed: list[int] = []

        async def execute(job, repo, progress):
            await progress(10, "early")
            # 终态前用**新会话**读日志（独立会话写入 → 立即可见）
            logs = await _get_logs(container, job.id)
            observed.append(len(logs))
            await progress(50, "mid")
            return {"ok": True}

        await run_job(settings, container, {"job_id": str(job_id)}, kind=JobKind.BACKTEST, execute=execute)
        assert observed == [1]  # 第一个 progress 后即可见 1 条

        logs = await _get_logs(container, job_id)
        assert [log.seq for log in logs] == list(range(len(logs)))
        assert any("[10%]" in log.message for log in logs)
        assert any("[50%]" in log.message for log in logs)


def test_default_split_partition() -> None:
    from qqlab.services.model_service import default_split

    split = default_split(date(2023, 1, 3), date(2023, 12, 29))
    train_end = date.fromisoformat(split["train"][1])
    valid_start = date.fromisoformat(split["valid"][0])
    assert train_end + timedelta(days=1) == valid_start
    assert split["train"][0] == "2023-01-03"
    assert split["valid"][1] == "2023-12-29"


def test_default_split_rejects_short_span() -> None:
    from qqlab.core.errors import ValidationAppError
    from qqlab.services.model_service import default_split

    with pytest.raises(ValidationAppError, match="无法默认切分"):
        default_split(date(2023, 1, 3), date(2023, 2, 1))


def test_daily_ic_groups_by_date_on_multiindex_inputs() -> None:
    """``_daily_ic`` 须按**日期**（MultiIndex 末位）分组；输入退化成 RangeIndex 即全空。

    实机回归（阶段 5）：调用点曾传 ``.to_numpy()`` → RangeIndex → ``groupby(level=-1)``
    按行分组（每组 1 行 < 5）→ daily 恒为空 → valid_ic 静默回退 pooled、valid_ir 恒 0
    （见 docs/stage5/05-testing.md §4）。
    """
    import numpy as np
    import pandas as pd

    from qqlab.adapters.compute.qlib_compute import QlibComputeProvider

    idx = pd.MultiIndex.from_product(
        [[f"SH60000{i}" for i in range(6)], pd.date_range("2024-01-02", periods=6)],
        names=["instrument", "date"],
    )
    values = np.linspace(0.01, 0.36, len(idx))
    actual = pd.Series(values, index=idx)
    pred = pd.Series(values[::-1], index=idx)  # 每日横截面内反序 → 稳定负相关

    daily = QlibComputeProvider._daily_ic(pred, actual)
    assert len(daily) == 6  # 6 个交易日，各 6 个标的 → 每日一个 rank-IC
    assert all(-1.0 <= v <= 1.0 for v in daily)

    # 反例：同样数据剥离索引（RangeIndex）→ 按行分组、每组 < 5 → 全部跳过
    assert QlibComputeProvider._daily_ic(pred.to_numpy(), actual.to_numpy()) == []
