"""RBAC：声明式权限表。

路由上写**权限点**而不是硬编码角色，后续加角色/改策略只动这张表。
"""

from __future__ import annotations

from qqlab.ports.auth import Role

# 角色全集
ALL_ROLES: tuple[Role, ...] = (Role.ADMIN, Role.RESEARCHER, Role.VIEWER, Role.AUDITOR)

_EVERYONE = frozenset(ALL_ROLES)
_STAFF = frozenset({Role.ADMIN, Role.RESEARCHER})
_ADMIN = frozenset({Role.ADMIN})
_AUDIT = frozenset({Role.ADMIN, Role.AUDITOR})

#: 权限点 → 允许的角色
PERMISSIONS: dict[str, frozenset[Role]] = {
    # 读
    "project.read": _EVERYONE,
    "data.read": _EVERYONE,
    "factor.read": _EVERYONE,
    "model.read": _EVERYONE,
    "strategy.read": _EVERYONE,
    "backtest.read": _EVERYONE,
    "job.read": _EVERYONE,
    "legal.read": _EVERYONE,
    # 写（researcher 及以上）
    "project.write": _STAFF,
    "project.member.manage": _STAFF,
    "data.write": _STAFF,
    "data.license.manage": _ADMIN,
    "factor.write": _STAFF,
    "factor.compute": _STAFF,
    "model.write": _STAFF,
    "train.submit": _STAFF,
    "strategy.write": _STAFF,
    "backtest.submit": _STAFF,
    "backtest.export": frozenset({Role.ADMIN, Role.RESEARCHER, Role.AUDITOR}),
    "job.control": _STAFF,
    # 高危（admin 专属，且需二次确认）
    "project.delete": _ADMIN,
    "resource.delete": _ADMIN,
    "strategy.publish": _ADMIN,
    "factor.publish": _ADMIN,
    "project.visibility": _ADMIN,
    "admin.config": _ADMIN,
    "admin.member": _ADMIN,
    # 审计
    "audit.read": _AUDIT,
    "audit.export": _AUDIT,
}

ALL_PERMISSIONS: tuple[str, ...] = tuple(PERMISSIONS)


def is_known(permission: str) -> bool:
    return permission in PERMISSIONS


def roles_for(permission: str) -> frozenset[Role]:
    if permission not in PERMISSIONS:
        raise KeyError(f"未知权限点: {permission}")
    return PERMISSIONS[permission]


def has_permission(roles: tuple[Role, ...] | list[Role], permission: str) -> bool:
    allowed = roles_for(permission)
    return any(r in allowed for r in roles)


def permissions_for(roles: tuple[Role, ...] | list[Role]) -> list[str]:
    """反查用户拥有的全部权限点（前端隐藏无权菜单用）。"""
    role_set = frozenset(roles)
    return sorted(p for p, allowed in PERMISSIONS.items() if role_set & allowed)
