"""RBAC 权限矩阵。"""

from __future__ import annotations

import pytest

from qqlab.core.rbac import ALL_PERMISSIONS, PERMISSIONS, has_permission, permissions_for, roles_for
from qqlab.ports.auth import Role

ADMIN = (Role.ADMIN,)
RESEARCHER = (Role.RESEARCHER,)
VIEWER = (Role.VIEWER,)
AUDITOR = (Role.AUDITOR,)


@pytest.mark.parametrize(
    ("roles", "permission", "expected"),
    [
        (ADMIN, "project.read", True),
        (VIEWER, "project.read", True),
        (AUDITOR, "project.read", True),
        (RESEARCHER, "project.write", True),
        (VIEWER, "project.write", False),
        (AUDITOR, "project.write", False),
        (ADMIN, "project.delete", True),
        (RESEARCHER, "project.delete", False),
        (ADMIN, "strategy.publish", True),
        (RESEARCHER, "strategy.publish", False),
        (AUDITOR, "audit.read", True),
        (VIEWER, "audit.read", False),
        (RESEARCHER, "backtest.export", True),
        (VIEWER, "backtest.export", False),
        (ADMIN, "admin.config", True),
        (RESEARCHER, "admin.config", False),
    ],
)
def test_permission_matrix(roles, permission, expected) -> None:  # noqa: ANN001
    assert has_permission(roles, permission) is expected


def test_unknown_permission_raises() -> None:
    with pytest.raises(KeyError):
        has_permission(ADMIN, "does.not.exist")


def test_every_permission_has_known_roles() -> None:
    for permission in ALL_PERMISSIONS:
        allowed = roles_for(permission)
        assert allowed, f"{permission} 没有任何角色可用"
        assert allowed <= frozenset(Role)


def test_permissions_for_admin_is_superset_of_viewer() -> None:
    assert set(permissions_for(VIEWER)) <= set(permissions_for(ADMIN))


def test_permissions_sorted_and_deduped() -> None:
    perms = permissions_for((Role.ADMIN, Role.RESEARCHER))
    assert perms == sorted(set(perms))
    assert len(perms) == len(set(perms))
    assert len(PERMISSIONS) == len(ALL_PERMISSIONS)
