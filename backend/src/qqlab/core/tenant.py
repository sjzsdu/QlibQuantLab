"""租户作用域：org_id 是唯一租户边界。

所有查询都必须经过 :class:`OrgScope`；缓存 key、锁 key、对象存储 key 也统一由它加前缀，
避免跨租户污染（见 docs/stage1/03-data-model.md §3）。
"""

from __future__ import annotations

from dataclasses import dataclass

from qqlab.ports.auth import Role


@dataclass(frozen=True, slots=True)
class OrgScope:
    org_id: str
    user_id: str
    roles: tuple[Role, ...] = ()

    # ---- 派生 key（禁止在业务代码里手写前缀） ----
    def cache_key(self, *parts: object) -> str:
        return ":".join(["qqlab", self.org_id, *(str(p) for p in parts)])

    def lock_key(self, resource: str, resource_id: str) -> str:
        return ":".join(["lock", self.org_id, resource, resource_id])

    def storage_key(self, *parts: object) -> str:
        return "/".join([self.org_id, *(str(p).strip("/") for p in parts)])

    def qlib_data_root(self, root: str) -> str:
        """每个 org 独立的 Qlib 数据目录。"""
        return f"{root.rstrip('/')}/{self.org_id}"

    @classmethod
    def system(cls) -> OrgScope:
        """系统级作用域（种子数据、健康检查），仅内部使用。"""
        return cls(org_id="system", user_id="system", roles=(Role.ADMIN,))
