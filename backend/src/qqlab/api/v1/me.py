"""当前用户：/me 与 /me/permissions。未登录一律 401。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from qqlab.api.deps import get_current_user, success
from qqlab.api.deps import permissions_response as permissions_for_dep
from qqlab.schemas import CurrentUserOut, PermissionsOut

router = APIRouter(tags=["me"])


def _out(user) -> dict:  # noqa: ANN001
    return CurrentUserOut(
        user_id=user.user_id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        org_id=user.org_id,
        org_name=user.org_name,
        roles=[r.value for r in user.roles],
        is_authenticated=user.is_authenticated,
        provider=user.provider,
    ).model_dump()


@router.get("/me", summary="当前登录用户")
async def me(request: Request, user=Depends(get_current_user)) -> dict:
    return success(request, _out(user))


@router.get("/me/permissions", summary="当前用户的全部权限点")
async def my_permissions(request: Request, permissions=Depends(permissions_for_dep)) -> dict:
    return success(request, PermissionsOut(permissions=permissions).model_dump())
