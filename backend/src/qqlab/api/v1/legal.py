"""静态法务文档（公开可读：登录页也要能看到风险提示）。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from qqlab.api.deps import success
from qqlab.services import legal_doc, legal_meta

router = APIRouter(prefix="/legal", tags=["legal"])


@router.get("/meta", summary="法务文档清单")
async def legal_meta_endpoint(request: Request) -> dict:
    return success(request, [m.model_dump() for m in legal_meta()])


@router.get("/{code}", summary="法务文档正文（Markdown）")
async def legal_content(request: Request, code: str) -> dict:
    return success(request, legal_doc(code).model_dump())
