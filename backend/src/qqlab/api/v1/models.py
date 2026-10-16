"""模型与训练 API（阶段 5）：模型 CRUD + 算法目录 + 提交训练 + 训练记录。

- 创建收 ``factor_ids``（引用因子库并在服务层快照表达式）；
- ``POST /models/{id}/train`` 入队 train 任务，返回 job/run 供轮询；
- ``GET /models/catalog`` 静态目录（与阶段 1「worker 探测」的偏差已登记
  docs/stage5/06-risks.md）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from qqlab.api.deps import (
    get_audit_ctx,
    get_container,
    get_db_session,
    require_permission,
    success,
)
from qqlab.container import Container
from qqlab.core.tenant import OrgScope
from qqlab.ports.auth import CurrentUser
from qqlab.schemas import (
    ModelCatalogItem,
    ModelCreateIn,
    ModelUpdateIn,
    OkOut,
    PageOut,
    TrainingRunOut,
    TrainSubmitIn,
)
from qqlab.services import AuditContext, JobService, ModelService
from qqlab.services.model_service import TRAIN_ALGOS

router = APIRouter(prefix="/models", tags=["models"])
runs_router = APIRouter(prefix="/training-runs", tags=["training-runs"])


def _service(session, user: CurrentUser, ctx: AuditContext, container: Container) -> ModelService:
    return ModelService(
        session=session,
        scope=OrgScope(org_id=user.org_id, user_id=user.user_id, roles=user.roles),
        user=user,
        audit=container.audit,
        ctx=ctx,
        storage=container.storage,
    )


# ------------------------------------------------------------------ 模型 CRUD
@router.get("", summary="模型列表")
async def list_models(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, max_length=100),
    project_id: str | None = Query(None, max_length=64),
    user=Depends(require_permission("model.read")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
    container=Depends(get_container),
) -> dict:
    service = _service(session, user, ctx, container)
    result = await service.list(page=page, page_size=page_size, keyword=keyword, project_id=project_id)
    return success(request, result.model_dump())


@router.get("/catalog", summary="可用训练算法目录")
async def model_catalog(request: Request, user=Depends(require_permission("model.read"))) -> dict:
    items = [
        ModelCatalogItem(
            algo=algo,
            label=label,
            available=True,
            note="阶段 5 唯一算法（D5-0a）" if algo == "lgb" else "",
        )
        for algo, label in sorted(TRAIN_ALGOS.items())
    ]
    return success(request, [i.model_dump() for i in items])


@router.post("", summary="创建模型（因子引用即快照）")
async def create_model(
    request: Request,
    payload: ModelCreateIn,
    user=Depends(require_permission("model.write")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
    container=Depends(get_container),
) -> dict:
    service = _service(session, user, ctx, container)
    row = await service.create(payload)
    return success(request, row.model_dump(), message="模型已创建")


@router.get("/{model_id}", summary="模型详情")
async def get_model(
    request: Request,
    model_id: str,
    user=Depends(require_permission("model.read")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
    container=Depends(get_container),
) -> dict:
    service = _service(session, user, ctx, container)
    return success(request, (await service.get(model_id)).model_dump())


@router.patch("/{model_id}", summary="修改模型（名称/超参）")
async def update_model(
    request: Request,
    model_id: str,
    payload: ModelUpdateIn,
    user=Depends(require_permission("model.write")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
    container=Depends(get_container),
) -> dict:
    service = _service(session, user, ctx, container)
    row = await service.update(model_id, payload)
    return success(request, row.model_dump(), message="模型已更新")


@router.delete("/{model_id}", summary="删除模型（二次确认）")
async def delete_model(
    request: Request,
    model_id: str,
    confirm: bool = Query(False),
    user=Depends(require_permission("resource.delete")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
    container=Depends(get_container),
) -> dict:
    service = _service(session, user, ctx, container)
    await service.delete(model_id, confirm=confirm)
    return success(request, OkOut(ok=True), message="模型已删除")


# ------------------------------------------------------------------ 训练
@router.post("/{model_id}/train", summary="提交训练任务")
async def submit_train(
    request: Request,
    model_id: str,
    payload: TrainSubmitIn,
    user=Depends(require_permission("train.submit")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
    container=Depends(get_container),
) -> dict:
    service = _service(session, user, ctx, container)
    jobs = JobService(
        container=container, scope=OrgScope(org_id=user.org_id, user_id=user.user_id, roles=user.roles)
    )
    result = await service.submit_train(model_id, payload, job_service=jobs)
    return success(request, result, message="训练任务已入队")


@runs_router.get("", summary="训练记录列表")
async def list_runs(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    model_id: str | None = Query(None, max_length=64),
    project_id: str | None = Query(None, max_length=64),
    user=Depends(require_permission("model.read")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
    container=Depends(get_container),
) -> dict:
    service = _service(session, user, ctx, container)
    result: PageOut[TrainingRunOut] = await service.list_runs(
        page=page, page_size=page_size, model_id=model_id, project_id=project_id
    )
    return success(request, result.model_dump())


@runs_router.get("/{run_id}", summary="训练记录详情")
async def get_run(
    request: Request,
    run_id: str,
    user=Depends(require_permission("model.read")),
    session=Depends(get_db_session),
    ctx=Depends(get_audit_ctx),
    container=Depends(get_container),
) -> dict:
    service = _service(session, user, ctx, container)
    return success(request, (await service.get_run(run_id)).model_dump())


__all__ = ["router", "runs_router"]
