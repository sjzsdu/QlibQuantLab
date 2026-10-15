"""管理端服务：成员管理 + 系统配置。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from qqlab.core.errors import ConfirmationRequiredError, ConflictError, NotFoundError, ValidationAppError
from qqlab.core.ids import stable_uuid
from qqlab.core.tenant import OrgScope
from qqlab.ports.audit import AuditAction, AuditWriter
from qqlab.ports.auth import CurrentUser, Role
from qqlab.repositories import IdentityRepository, SystemConfigRepository
from qqlab.schemas import ConfigOut, ConfigUpdateIn, MemberAddIn, MemberOut, PageOut
from qqlab.services.base import AuditContext

_KNOWN_ROLES = frozenset(Role)


class AdminService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        scope: OrgScope,
        user: CurrentUser,
        audit: AuditWriter,
        ctx: AuditContext,
    ) -> None:
        self._session = session
        self._scope = scope
        self._user = user
        self._audit = audit
        self._ctx = ctx
        self._identity = IdentityRepository(session)
        self._configs = SystemConfigRepository(session, scope.org_id)

    # ------------------------------------------------------------ 成员
    async def list_members(self, *, page: int = 1, page_size: int = 50) -> PageOut[MemberOut]:
        rows, total = await self._identity.list_members(self._scope.org_id, page=page, page_size=page_size)
        return PageOut(
            items=[MemberOut(**row) for row in rows],
            total=total,
            page=max(1, page),
            page_size=min(max(1, page_size), 200),
        )

    async def add_member(self, data: MemberAddIn) -> MemberOut:
        roles = _validate_roles(data.roles)
        existing = await self._identity.find_user_by_username(data.username)
        if existing is None:
            # 尚未登录过的用户：先建占位身份，首次登录时由 AuthService 补齐外部信息
            existing = await self._identity.upsert_user(
                user_id=data.username,
                username=data.username,
                email=data.email,
                display_name=data.display_name or data.username,
                provider="mock",
            )
        user_id = str(existing.id)
        membership = await self._identity.get_membership(self._scope.org_id, user_id)
        if membership is not None and membership.deleted_at is None:
            raise ConflictError(f"用户 {data.username} 已在组织中")
        await self._identity.upsert_membership(
            org_id=self._scope.org_id,
            user_id=user_id,
            roles=roles,
            status="active",
        )
        await self._audit.record(
            action=AuditAction.ADMIN_MEMBER_ROLE_CHANGE,
            resource_type="user",
            resource_id=user_id,
            detail={"op": "add", "username": data.username, "roles": roles},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        return await self._member_out(user_id)

    async def update_member_roles(self, user_id: str, roles: list[str]) -> MemberOut:
        normalized = _validate_roles(roles)
        membership = await self._identity.get_membership(self._scope.org_id, user_id)
        if membership is None:
            raise NotFoundError("成员不存在或不属于当前组织")
        before = list(membership.roles or [])
        await self._identity.upsert_membership(
            org_id=self._scope.org_id,
            user_id=user_id,
            roles=normalized,
            status=membership.status,
        )
        await self._audit.record(
            action=AuditAction.ADMIN_MEMBER_ROLE_CHANGE,
            resource_type="user",
            resource_id=str(stable_uuid(user_id)),
            detail={"before": before, "after": normalized},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        return await self._member_out(user_id)

    async def remove_member(self, user_id: str, *, confirm: bool) -> bool:
        if not confirm:
            raise ConfirmationRequiredError("admin.member.remove")
        if user_id == self._scope.user_id or stable_uuid(user_id) == stable_uuid(self._scope.user_id):
            raise ValidationAppError("不能移除自己")
        removed = await self._identity.remove_member(self._scope.org_id, user_id)
        if not removed:
            raise NotFoundError("成员不存在或不属于当前组织")
        await self._audit.record(
            action=AuditAction.ADMIN_MEMBER_ROLE_CHANGE,
            resource_type="user",
            resource_id=str(stable_uuid(user_id)),
            detail={"op": "remove"},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        return True

    async def _member_out(self, user_id: str) -> MemberOut:
        target = str(stable_uuid(user_id))
        rows, _ = await self._identity.list_members(self._scope.org_id, page=1, page_size=200)
        for row in rows:
            if row["user_id"] == target:
                return MemberOut(**row)
        raise NotFoundError("成员不存在或不属于当前组织")

    # ------------------------------------------------------------ 系统配置
    async def list_configs(self, *, redact: bool = True) -> list[ConfigOut]:
        rows = await self._configs.list_all()
        return [
            ConfigOut(
                config_key=row.config_key,
                value={} if (row.is_secret and redact) else dict(row.value or {}),
                is_secret=row.is_secret,
                updated_by=row.updated_by,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    async def update_config(self, config_key: str, data: ConfigUpdateIn) -> ConfigOut:
        if not config_key.strip():
            raise ValidationAppError("config_key 不能为空")
        row = await self._configs.upsert(
            config_key=config_key.strip(),
            value=data.value,
            is_secret=data.is_secret,
            updated_by=self._user.username,
        )
        await self._audit.record(
            action=AuditAction.ADMIN_CONFIG_UPDATE,
            resource_type="system_config",
            resource_id=row.config_key,
            detail={"is_secret": row.is_secret, "keys": sorted(row.value.keys())},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        return ConfigOut(
            config_key=row.config_key,
            value={} if row.is_secret else dict(row.value or {}),
            is_secret=row.is_secret,
            updated_by=row.updated_by,
            updated_at=row.updated_at,
        )


def _validate_roles(roles: list[str]) -> list[str]:
    if not roles:
        raise ValidationAppError("角色列表不能为空")
    normalized: list[str] = []
    for raw in roles:
        value = str(raw).strip().lower()
        if value not in _KNOWN_ROLES:
            raise ValidationAppError(f"未知角色: {raw}（可选: {sorted(_KNOWN_ROLES)}）")
        if value not in normalized:
            normalized.append(value)
    return normalized


__all__ = ["AdminService"]
