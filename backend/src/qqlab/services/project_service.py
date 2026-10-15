"""项目服务：增删改查 + 审计 + 租户约束。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from qqlab.core.errors import ConfirmationRequiredError, ConflictError, NotFoundError, ValidationAppError
from qqlab.core.ids import stable_uuid
from qqlab.core.tenant import OrgScope
from qqlab.models import Project, ProjectMember
from qqlab.ports.audit import AuditAction, AuditWriter
from qqlab.ports.auth import CurrentUser
from qqlab.repositories import (
    IdentityRepository,
    ProjectMemberRepository,
    ProjectRepository,
)
from qqlab.schemas import (
    PageOut,
    ProjectCreateIn,
    ProjectMemberAddIn,
    ProjectMemberOut,
    ProjectOut,
    ProjectUpdateIn,
)
from qqlab.services.base import AuditContext


class ProjectService:
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
        self._repo = ProjectRepository(session, scope)

    # ---------------------------------------------------------------- 读
    async def list(
        self, *, page: int = 1, page_size: int = 20, keyword: str | None = None
    ) -> PageOut[ProjectOut]:
        items, total = await self._repo.list(page=page, page_size=page_size, keyword=keyword)
        names = await self._repo.created_by_names(items)
        return PageOut(
            items=[_to_out(p, names) for p in items],
            total=total,
            page=max(1, page),
            page_size=min(max(1, page_size), 200),
        )

    async def get(self, project_id: str) -> ProjectOut:
        project = await self._require(project_id)
        names = await self._repo.created_by_names([project])
        return _to_out(project, names)

    # ---------------------------------------------------------------- 写
    async def create(self, data: ProjectCreateIn) -> ProjectOut:
        name = data.name.strip()
        if not name:
            raise ValidationAppError("项目名称不能为空")
        if await self._repo.count_by_name(name):
            raise ConflictError(f"当前组织下已存在同名项目：{name}")

        project = Project(
            id=uuid.uuid4(),
            org_id=stable_uuid(self._scope.org_id),
            created_by=stable_uuid(self._scope.user_id),
            name=name,
            description=(data.description or "").strip() or None,
            visibility="private",  # 默认私有
        )
        await self._repo.add(project)

        # 建立者自动成为项目成员
        self._session.add(
            ProjectMember(
                id=uuid.uuid4(),
                org_id=stable_uuid(self._scope.org_id),
                project_id=project.id,
                user_id=stable_uuid(self._scope.user_id),
                role="owner",
            )
        )
        await self._session.flush()

        await self._audit.record(
            action=AuditAction.PROJECT_CREATE,
            resource_type="project",
            resource_id=str(project.id),
            detail={"name": project.name, "visibility": project.visibility},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        names = await self._repo.created_by_names([project])
        return _to_out(project, names)

    async def update(self, project_id: str, data: ProjectUpdateIn) -> ProjectOut:
        project = await self._require(project_id)
        before = {"name": project.name, "description": project.description}

        if data.name is not None:
            name = data.name.strip()
            if not name:
                raise ValidationAppError("项目名称不能为空")
            if name != project.name and await self._repo.count_by_name(name, exclude_id=project.id):
                raise ConflictError(f"当前组织下已存在同名项目：{name}")
            project.name = name
        if data.description is not None:
            project.description = data.description.strip() or None

        await self._session.flush()
        await self._audit.record(
            action=AuditAction.PROJECT_UPDATE,
            resource_type="project",
            resource_id=str(project.id),
            detail={"before": before, "after": {"name": project.name, "description": project.description}},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        names = await self._repo.created_by_names([project])
        return _to_out(project, names)

    async def delete(self, project_id: str, *, confirm: bool) -> str:
        """二次确认 + 软删除。"""
        if not confirm:
            raise ConfirmationRequiredError("project.delete")
        project = await self._require(project_id)
        project.deleted_at = datetime.now(tz=UTC)
        await self._session.flush()
        await self._audit.record(
            action=AuditAction.PROJECT_DELETE,
            resource_type="project",
            resource_id=str(project.id),
            detail={"name": project.name},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        return str(project.id)

    # ---------------------------------------------------------------- 成员
    async def list_members(self, project_id: str) -> list[ProjectMemberOut]:
        project = await self._require(project_id)
        repo = ProjectMemberRepository(self._session, self._scope)
        rows = await repo.list(project.id)
        names = await repo.user_names(rows)
        return [
            ProjectMemberOut(
                user_id=str(m.user_id),
                username=names.get(m.user_id, str(m.user_id)),
                role=m.role,
                added_at=m.created_at,
            )
            for m in rows
        ]

    async def add_member(self, project_id: str, data: ProjectMemberAddIn) -> ProjectMemberOut:
        project = await self._require(project_id)
        username = data.username.strip()
        identity = IdentityRepository(self._session)
        user = await identity.find_user_by_username(username)
        if user is None:
            raise NotFoundError(f"用户不存在或不属于当前组织：{username}")
        membership = await identity.get_membership(self._scope.org_id, str(user.id))
        if membership is None or membership.deleted_at is not None or membership.status != "active":
            raise NotFoundError(f"用户不存在或不属于当前组织：{username}")
        repo = ProjectMemberRepository(self._session, self._scope)
        if await repo.get(project.id, str(user.id)) is not None:
            raise ConflictError(f"用户 {username} 已是项目成员")
        member = await repo.add(
            ProjectMember(
                org_id=stable_uuid(self._scope.org_id),
                project_id=project.id,
                user_id=user.id,
                role=data.role,
            )
        )
        await self._audit.record(
            action=AuditAction.PROJECT_MEMBER_ADD,
            resource_type="project",
            resource_id=str(project.id),
            detail={"username": username, "role": data.role},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        return ProjectMemberOut(
            user_id=str(member.user_id),
            username=username,
            role=member.role,
            added_at=member.created_at,
        )

    async def remove_member(self, project_id: str, user_id: str, *, confirm: bool) -> bool:
        if not confirm:
            raise ConfirmationRequiredError("project.member.remove")
        project = await self._require(project_id)
        repo = ProjectMemberRepository(self._session, self._scope)
        existing = await repo.get(project.id, user_id)
        if existing is None:
            raise NotFoundError("成员不存在或不属于该项目")
        if stable_uuid(user_id) == stable_uuid(self._scope.user_id):
            raise ValidationAppError("不能移除自己")
        await repo.remove(project.id, stable_uuid(user_id))
        await self._audit.record(
            action=AuditAction.PROJECT_MEMBER_REMOVE,
            resource_type="project",
            resource_id=str(project.id),
            detail={"user_id": user_id},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        return True

    # ---------------------------------------------------------------- 可见性
    async def set_visibility(self, project_id: str, visibility: str, *, confirm: bool) -> ProjectOut:
        """private ⇄ org ⇄ public；对外发布属高危操作，需二次确认。"""
        if not confirm:
            raise ConfirmationRequiredError("project.visibility.change")
        project = await self._require(project_id)
        before = project.visibility
        project.visibility = visibility
        await self._session.flush()
        await self._audit.record(
            action=AuditAction.PROJECT_VISIBILITY_CHANGE,
            resource_type="project",
            resource_id=str(project.id),
            detail={"before": before, "after": visibility},
            user=self._user,
            request_id=self._ctx.request_id,
            ip=self._ctx.ip,
        )
        names = await self._repo.created_by_names([project])
        return _to_out(project, names)

    # ---------------------------------------------------------------- 内部
    async def _require(self, project_id: str) -> Project:
        project = await self._repo.get(project_id)
        if project is None:
            # 跨租户访问与不存在返回同一种错误，避免探测他人资源
            raise NotFoundError("项目不存在或无权访问")
        return project


def _to_out(project: Project, created_by_names: dict[uuid.UUID, str]) -> ProjectOut:
    return ProjectOut(
        id=str(project.id),
        name=project.name,
        description=project.description,
        visibility=project.visibility,
        default_benchmark=project.default_benchmark,
        created_by=created_by_names.get(project.created_by, str(project.created_by)),
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


__all__ = ["ProjectService"]
