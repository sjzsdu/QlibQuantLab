#!/usr/bin/env python
"""阶段 3 smoke 入队脚本（在 **backend 容器** 内运行，有 DB 访问）：

  # 1) 入队数据导入（校验 qlib 数据目录 + 登记 data_sources/data_licenses/datasets 台账）
  docker compose --profile qlib exec backend python /scripts/enqueue_backtest_smoke.py dataset_import

  # 2) 入队最小回测（stub 或 qlib 计算，取决于 COMPUTE_BACKEND；决策 #7：脚本入队，不开公共 API）
  docker compose --profile qlib exec backend python /scripts/enqueue_backtest_smoke.py backtest

入队一律走 ``JobService.enqueue``（落库提交 → 发布 MQ 消息，唯一入队路径）。
任务由 worker 消费。观测进度：
  docker compose logs -f worker
  docker compose exec postgres psql -U qqlab -c "select id,kind,status,progress,error from jobs order by created_at desc limit 5;"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid


def _container():
    from qqlab.config import Settings
    from qqlab.container import Container

    return Container.build(Settings())


def _scope():
    """与 mock 登录同源的默认租户（.env 里 MOCK_* 决定；生产由 Casdoor claim 决定）。"""
    from qqlab.core.tenant import OrgScope

    return OrgScope(
        org_id=os.getenv("MOCK_ORG_ID", "dev-org"),
        user_id=os.getenv("MOCK_USER_ID", "dev-user"),
    )


async def enqueue_dataset_import(container, scope) -> str:
    from qqlab.models import JobKind
    from qqlab.services.job_service import JobService

    return await JobService(container=container, scope=scope).enqueue(
        kind=JobKind.DATASET_IMPORT,
        payload={"region": os.getenv("QLIB_REGION", "cn")},
        requested_by="smoke-script",
    )


async def enqueue_backtest(container, scope, *, topk: int, lookback: int, cost_overrides: dict) -> str:
    """入队一次最小回测（信号 = 动量 topk 纯规则；费用三件套必填）。"""
    from sqlalchemy import select

    from qqlab.models import Backtest, Dataset, JobKind, Project, Strategy
    from qqlab.services.job_service import JobService

    async with container.database.session() as session:
        # 复用已有 dataset（dataset_import 任务完成后才有）；没有则提示先跑导入
        dataset = (
            (await session.execute(select(Dataset).where(Dataset.org_id == _stable(scope.org_id))))
            .scalars()
            .first()
        )
        if dataset is None:
            raise SystemExit("未找到 dataset —— 先跑 enqueue_dataset_import.py 并等 worker 完成")

        # 复用/创建最小 study 链（project → strategy → backtest）
        project = (
            (await session.execute(select(Project).where(Project.org_id == _stable(scope.org_id))))
            .scalars()
            .first()
        )
        if project is None:
            project = Project(org_id=_stable(scope.org_id), created_by=_stable(scope.user_id), name="smoke")
            session.add(project)
            await session.flush()

        strategy = Strategy(
            org_id=_stable(scope.org_id),
            created_by=_stable(scope.user_id),
            project_id=project.id,
            name=f"动量 smoke-{uuid.uuid4().hex[:6]}",
            signal_config={
                "signal_type": "momentum",
                "lookback": lookback,
                "topk": topk,
            },
        )
        session.add(strategy)
        await session.flush()

        # 费用三件套（决策：100% 透传，不使用任何 qlib 默认值）
        cost = {
            "commission_rate": 0.0003,
            "min_commission": 5.0,
            "slippage": {"type": "fixed_bp", "value": 10.0},
            "impact_cost": {"type": "linear", "rate_per_million": 0.0001},
            "settlement_fee": 0.00002,
            "stamp_duty_sell": 0.0005,
        }
        cost.update(cost_overrides)

        backtest = Backtest(
            org_id=_stable(scope.org_id),
            created_by=_stable(scope.user_id),
            project_id=project.id,
            strategy_id=strategy.id,
            dataset_id=dataset.id,
            cost_config=cost,
            params={"topk": topk, "lookback": lookback},
            start_date=None,  # None = 用 dataset 全区间
            end_date=None,
        )
        session.add(backtest)
        await session.flush()
        backtest_id = str(backtest.id)

    # study 链提交后再入队（JobService 负责"落库提交 → 发布 MQ"的顺序）
    return await JobService(container=container, scope=scope).enqueue(
        kind=JobKind.BACKTEST,
        payload={"backtest_id": backtest_id},
        requested_by="smoke-script",
    )


def _stable(org_or_user: str):
    from qqlab.core.ids import stable_uuid

    return stable_uuid(org_or_user)


async def main() -> int:
    parser = argparse.ArgumentParser(description="阶段 3 smoke 入队")
    parser.add_argument("kind", choices=["dataset_import", "backtest"])
    parser.add_argument("--topk", type=int, default=5)
    parser.add_argument("--lookback", type=int, default=20)
    parser.add_argument(
        "--cost",
        default="",
        help="费用覆盖（JSON），如 '{\"commission_rate\": 0.001}'",
    )
    args = parser.parse_args()

    container = _container()
    scope = _scope()
    cost_overrides = json.loads(args.cost) if args.cost else {}

    if args.kind == "dataset_import":
        job_id = await enqueue_dataset_import(container, scope)
    else:
        job_id = await enqueue_backtest(
            container, scope, topk=args.topk, lookback=args.lookback, cost_overrides=cost_overrides
        )

    print(json.dumps({"kind": args.kind, "job_id": job_id, "org": scope.org_id}, ensure_ascii=False))
    print("跟踪：docker compose logs -f worker", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
