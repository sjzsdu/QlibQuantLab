"""当前组织信息。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from qqlab.api.deps import get_current_user, get_db_session, success
from qqlab.repositories import IdentityRepository
from qqlab.schemas import OrgOut

router = APIRouter(prefix="/orgs", tags=["orgs"])


@router.get("/current", summary="当前组织")
async def current_org(
    request: Request,
    user=Depends(get_current_user),
    session=Depends(get_db_session),
) -> dict:
    org = await IdentityRepository(session).get_org(user.org_id)
    payload = OrgOut(
        id=user.org_id,
        slug=org.slug if org else "",
        name=org.name if org else (user.org_name or ""),
        status=org.status if org else "active",
    )
    return success(request, payload.model_dump())
