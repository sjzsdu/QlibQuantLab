"""身份仓库：organizations / users / org_members。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from qqlab.core.ids import stable_uuid
from qqlab.models import Organization, OrgMember, User


class IdentityRepository:
    """身份表本身没有 ``created_by``，所以不继承 BaseRepository。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------------------------------------------------------- organizations
    async def get_org(self, org_id: str) -> Organization | None:
        stmt = select(Organization).where(Organization.id == stable_uuid(org_id))
        return (await self.session.execute(stmt)).scalars().first()

    async def ensure_org(
        self, org_id: str, *, slug: str, name: str, rename_existing: bool = True
    ) -> Organization:
        """确保组织存在。

        ``rename_existing=False``（阶段 7）：外部 IdP 不携带组织显示名时（如 Casdoor
        JWT 只有 owner 名），回落名 ``Org {id[:8]}`` 绝不能覆盖平台里已有的组织名 ——
        否则用户经 ORG_MAP 映射进既有组织的首次登录就会把组织改名。
        """
        existing = await self.get_org(org_id)
        if existing is not None:
            if rename_existing and existing.name != name:
                existing.name = name
                await self.session.flush()
            return existing
        org = Organization(
            id=stable_uuid(org_id),
            slug=slug,
            name=name,
            status="active",
            settings={},
        )
        self.session.add(org)
        await self.session.flush()
        return org

    # ------------------------------------------------------------------ users
    async def upsert_user(
        self,
        *,
        user_id: str,
        username: str,
        email: str | None,
        display_name: str | None,
        provider: str,
    ) -> User:
        uid = stable_uuid(user_id)
        row = (await self.session.execute(select(User).where(User.id == uid))).scalars().first()
        if row is None:
            row = User(
                id=uid,
                username=username,
                email=email,
                display_name=display_name,
                auth_provider=provider,
                external_id=user_id,
                status="active",
            )
            self.session.add(row)
        else:
            row.username = username
            row.email = email
            row.display_name = display_name
            row.auth_provider = provider
            row.external_id = user_id
        row.last_login_at = datetime.now(tz=UTC)
        await self.session.flush()
        return row

    async def get_user(self, user_id: str) -> User | None:
        stmt = select(User).where(User.id == stable_uuid(user_id))
        return (await self.session.execute(stmt)).scalars().first()

    async def find_user_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        return (await self.session.execute(stmt)).scalars().first()

    async def username_exists(self, username: str) -> bool:
        return await self.find_user_by_username(username) is not None

    # ------------------------------------------------------------ org_members
    async def upsert_membership(
        self,
        *,
        org_id: str,
        user_id: str,
        roles: list[str] | tuple[str, ...],
        status: str = "active",
    ) -> OrgMember:
        org_pk, user_pk = stable_uuid(org_id), stable_uuid(user_id)
        stmt = select(OrgMember).where(OrgMember.org_id == org_pk, OrgMember.user_id == user_pk)
        row = (await self.session.execute(stmt)).scalars().first()
        if row is None:
            row = OrgMember(
                id=uuid.uuid4(),
                org_id=org_pk,
                user_id=user_pk,
                roles=list(roles),
                status=status,
            )
            self.session.add(row)
        else:
            row.roles = list(roles)
            row.status = status
            row.deleted_at = None
        await self.session.flush()
        return row

    async def get_membership(self, org_id: str, user_id: str) -> OrgMember | None:
        stmt = select(OrgMember).where(
            OrgMember.org_id == stable_uuid(org_id),
            OrgMember.user_id == stable_uuid(user_id),
            OrgMember.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_members(
        self,
        org_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        org_pk = stable_uuid(org_id)
        offset, limit = (max(1, page) - 1) * min(max(1, page_size), 200), min(max(1, page_size), 200)
        base = select(OrgMember).where(
            OrgMember.org_id == org_pk,
            OrgMember.deleted_at.is_(None),
            OrgMember.status == "active",
        )
        total = int(
            (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        )
        members = (
            (
                await self.session.execute(
                    base.order_by(OrgMember.created_at.asc()).offset(offset).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        if not members:
            return [], total
        user_rows = (
            (await self.session.execute(select(User).where(User.id.in_([m.user_id for m in members]))))
            .scalars()
            .all()
        )
        users = {u.id: u for u in user_rows}
        out: list[dict[str, Any]] = []
        for m in members:
            u = users.get(m.user_id)
            out.append(
                {
                    "user_id": str(m.user_id),
                    "username": u.username if u else "",
                    "display_name": u.display_name if u else None,
                    "email": u.email if u else None,
                    "roles": list(m.roles or []),
                    "status": m.status,
                    "joined_at": m.created_at,
                }
            )
        return out, total

    async def remove_member(self, org_id: str, user_id: str) -> bool:
        row = await self.get_membership(org_id, user_id)
        if row is None:
            return False
        row.deleted_at = datetime.now(tz=UTC)
        await self.session.flush()
        return True


__all__ = ["IdentityRepository"]
