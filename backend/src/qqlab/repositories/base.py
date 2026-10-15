"""仓库层（Repository）：只做数据访问与**强制租户过滤**。

不含业务决策 —— 业务规则在 services，校验在 schemas，权限在 api/deps。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qqlab.core.tenant import OrgScope
from qqlab.models import User


class BaseRepository:
    """所有业务仓库的基类：持有会话与租户作用域。"""

    def __init__(self, session: AsyncSession, scope: OrgScope) -> None:
        self.session = session
        self.scope = scope

    # ---- 通用工具 ----
    async def usernames(self, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
        """批量把 user_id 翻译成 username（展示用，避免前端看到 UUID）。"""
        unique = list({uuid.UUID(str(i)) for i in ids})
        if not unique:
            return {}
        rows = await self.session.execute(select(User.id, User.username).where(User.id.in_(unique)))
        return {uid: name for uid, name in rows.all()}

    @staticmethod
    def page_offsets(page: int, page_size: int) -> tuple[int, int]:
        page = max(1, page)
        page_size = min(max(1, page_size), 200)
        return (page - 1) * page_size, page_size


__all__ = ["BaseRepository"]
