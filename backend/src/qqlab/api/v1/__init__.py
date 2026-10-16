"""v1 路由聚合。"""

from fastapi import APIRouter

from qqlab.api.v1 import (
    admin,
    audit,
    auth,
    backtests,
    data,
    factors,
    health,
    jobs,
    legal,
    me,
    models,
    orgs,
    projects,
    strategies,
)

v1_router = APIRouter()
for _router in (
    health.router,
    auth.router,
    me.router,
    orgs.router,
    legal.router,
    projects.router,
    admin.router,
    audit.router,
    data.router,
    factors.router,
    models.router,
    models.runs_router,
    strategies.router,
    backtests.router,
    jobs.router,
):
    v1_router.include_router(_router)

__all__ = ["v1_router"]
