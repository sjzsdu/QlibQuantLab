"""RBAC 全量覆盖（D6-2）：枚举全部路由，断言权限声明无一遗漏。

三层断言：
1. **公开白名单**（健康检查 / 认证流 / 法务文档 / 根路由）：允许无会话；
2. **会话级白名单**（``/me`` ``/orgs/current``）：必须挂 ``get_current_user``，
   但不要求具体权限点（登录即可读自己的信息）；
3. **其余全部路由**：必须挂 ``require_permission``（标记 ``__qqlab_permission__``）
   或 ``require_roles``（标记 ``__qqlab_roles__``），且权限点 ∈ ``PERMISSIONS`` 表。

白名单是显式枚举：新增路由若漏挂权限点，本测试立即失败；
把路由挪进白名单必须改测试代码 —— 留痕。
"""

from __future__ import annotations

import fnmatch

import pytest
from fastapi.routing import _IncludedRouter

from conftest import make_settings
from qqlab.api.deps import get_current_user
from qqlab.core.rbac import PERMISSIONS, is_known
from qqlab.main import create_app

#: 公开路由（无需会话）。``/auth/*``：登录发起、mock 进入、OIDC 回调、登出
#: （登出挂的是 get_optional_user，无会话也返回 200，语义如此）。
PUBLIC_PATTERNS = (
    "/",
    "/api/v1/health/live",
    "/api/v1/health/ready",
    "/api/v1/system/info",
    "/api/v1/auth/*",
    "/api/v1/legal/*",
    # 阶段 8 · D8-1：Prometheus scrape 无会话（dev/test 免鉴权；生产由 METRICS_TOKEN
    # 自管：空 = 404 fail-closed，非空 = Bearer/X-Metrics-Token 校验，见 api/v1/metrics.py）
    "/api/v1/metrics",
)

#: 会话即可、不要求权限点的路由（读自己的身份与权限、读当前组织）。
SESSION_ONLY_PATTERNS = (
    "/api/v1/me",
    "/api/v1/me/permissions",
    "/api/v1/orgs/current",
)


def _collect_calls(dependant) -> list:  # noqa: ANN001
    """深度优先收集依赖树上全部 ``.call`` 对象。"""
    calls = [dependant.call] if dependant.call is not None else []
    for sub in dependant.dependencies:
        calls.extend(_collect_calls(sub))
    return calls


@pytest.fixture(scope="module")
def app():  # noqa: ANN001
    return create_app(make_settings())


def _api_routes(app):  # noqa: ANN001
    """展开全部有效路由（FastAPI ≥0.143 的 ``_IncludedRouter`` 延迟展开）。

    返回 ``(_EffectiveRouteContext)`` 列表 —— 带完整 ``path`` 与合并后的 ``dependant``
    （子路由 include 时的额外 dependencies 已合并进去）。
    """
    from fastapi.routing import APIRoute

    contexts = []
    for route in app.routes:
        if isinstance(route, _IncludedRouter):
            contexts.extend(route.effective_route_contexts())
        elif isinstance(route, APIRoute):
            # 顶层直接挂载的路由（根 / 与 include 前的老式路由）
            ctx = type("C", (), {})()
            ctx.path = route.path
            ctx.methods = route.methods
            ctx.dependant = route.dependant
            contexts.append(ctx)
    return contexts


def _match(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path, p) for p in patterns)


def test_public_whitelist_routes_exist(app) -> None:  # noqa: ANN001
    """白名单里的路径必须真实存在（防白名单腐烂成死代码）。"""
    paths = {c.path for c in _api_routes(app)}
    for pattern in PUBLIC_PATTERNS + SESSION_ONLY_PATTERNS:
        if "*" in pattern:
            assert any(fnmatch.fnmatch(p, pattern) for p in paths), f"公开白名单无匹配路由: {pattern}"
        else:
            assert pattern in paths, f"白名单路径不存在: {pattern}"


def test_every_route_has_permission_or_is_whitelisted(app) -> None:  # noqa: ANN001
    """非白名单路由必须挂权限点/角色守卫，且权限点合法。"""
    uncovered: list[str] = []
    bad_permission: list[str] = []
    no_session: list[str] = []

    for route in _api_routes(app):
        path = route.path
        methods = sorted(getattr(route, "methods", None) or ["GET"])
        if _match(path, PUBLIC_PATTERNS):
            continue

        calls = _collect_calls(route.dependant)
        perms = [getattr(c, "__qqlab_permission__", None) for c in calls]
        perms = [p for p in perms if p]
        roles = [getattr(c, "__qqlab_roles__", None) for c in calls]
        roles = [r for r in roles if r]

        has_session = any(c is get_current_user for c in calls)
        if not has_session:
            # 会话级白名单要求至少挂 get_current_user；公开白名单已 continue
            no_session.append(f"{methods} {path}")

        if _match(path, SESSION_ONLY_PATTERNS):
            if not has_session:
                uncovered.append(f"{methods} {path} (会话白名单但未挂 get_current_user)")
            continue

        if not perms and not roles:
            uncovered.append(f"{methods} {path}")
        for p in perms:
            if not is_known(p):
                bad_permission.append(f"{methods} {path} -> {p}")

    assert not no_session, "未挂 get_current_user 的路由（须挂守卫或移入公开白名单）:\n" + "\n".join(
        sorted(no_session)
    )
    assert not uncovered, "缺权限声明的路由:\n" + "\n".join(sorted(uncovered))
    assert not bad_permission, "未知权限点:\n" + "\n".join(sorted(bad_permission))


def test_permission_points_declared_in_rbac_table() -> None:
    """PERMISSIONS 表本身是唯一事实源（有测试锁 ALL_PERMISSIONS 非空）。"""
    assert len(PERMISSIONS) >= 29
    assert "audit.export" in PERMISSIONS
    assert "backtest.export" in PERMISSIONS
    assert "factor.compute" in PERMISSIONS
