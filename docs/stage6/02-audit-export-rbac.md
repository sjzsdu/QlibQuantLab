# 02 · 审计 CSV 导出 + RBAC 全量路由扫描（D6-1 / D6-2）

## 1. RBAC 全量路由扫描（`tests/architecture/test_route_permissions.py`）

阶段 3 引入 RBAC 后，权限点只在各 API 的单元/集成测试里点状断言 —— **新增路由忘挂 `require_permission` 不会被任何测试发现**。本阶段把它变成结构性保证：

- `require_permission()` / `require_roles()` 在装饰时给路由处理函数打属性（`__qqlab_permission__` / `__qqlab_roles__`）；
- 架构测试 `create_app()` 后深度优先遍历全部依赖树收集路由，做三层断言：
  1. **公开白名单**（`PUBLIC_PATTERNS`：`/`、health、`/system/info`、`/auth/*`、`/legal/*`）允许无会话；
  2. **会话级白名单**（`SESSION_ONLY_PATTERNS`：`/me`、`/me/permissions`、`/orgs/current`）必须挂 `get_current_user`，但不要求权限点（读自己的信息）；
  3. **其余全部**必须挂 `require_permission`（权限点 ∈ `PERMISSIONS` 表）或 `require_roles`。

当前基线：**77 条路由 = 11 公开 + 3 仅会话 + 63 守卫**。白名单是显式枚举 —— 新路由漏挂权限 → 测试失败；想把路由挪进白名单必须改测试代码 → 留痕。

## 2. 审计 CSV 流式导出

### 路由

```
GET /api/v1/audit-logs/export?confirm=true[&action=&actor=&outcome=]
  权限：audit.export（admin + auditor）
  缺省 confirm → 400 code 1007（ConfirmationRequired）
  响应：text/csv 流（非信封），列与 API 文档一致
```

- **筛选条件与列表页同参**（action/actor/outcome）——前端「导出 CSV」带当前筛选二次确认，所见即所得；
- **导出动作本身记审计**（`audit.export`，detail 含筛选条件与行数），「谁把审计导出去了」也可审计。

### keyset 分页流式（`page_for_export` + `stream_csv`）

审计表会持续膨胀，导出不能 `OFFSET` 也不能全量进内存：

- 游标 = `(created_at, id)` 复合键（`created_at > after` OR `(= after AND id > after_id)`，id 非 UUID 时经 `stable_uuid` 归一），每批 500 行；
- `stream_csv` 是 async 生成器：先发表头，再逐批 `csv.writer` 写进 buffer yield 出去 —— **边查边发，内存占用 O(batch)**；
- FastAPI 的 `yield` 依赖在响应流结束才关闭（生成器完成于 teardown 之后，已在实机确认），session 生命周期安全。

### CSV 口径

- 列：`created_at,action,resource_type,resource_id,outcome,actor_username,ip,user_agent,request_id,detail`；
- `detail` 为**紧凑 JSON 单列**（`ensure_ascii=False, separators=(",",":")`），与列表 API 的 dict 同源；无 BOM（Excel 场景由前端下载时自行处理，审计导入以程序消费为主）。

## 3. 前端

`/audit` 页右上「导出 CSV」→ AntD Modal 二次确认（明示会记审计）→ `api.ts` 新增的 CSV 下载助手带当前筛选请求 → 浏览器落盘。viewer/researcher 无 `audit.export` 权限，后端 403 兜底（前端按钮对 admin/auditor 可见）。

## 4. 测试

| 用例 | 断言 |
|------|------|
| `test_route_permissions.py` | 77 路由三层断言；权限点全部已注册 |
| `test_audit_export.py`（unit） | keyset 游标稳定性（同秒多行不重不漏）、生成器分批、detail JSON 紧凑序列化 |
| `test_admin_and_audit.py`（api） | 无 confirm → 400/1007；confirm → CSV 表头/行数/筛选生效；viewer → 403；`audit.export` 留痕 |

实机（smoke §2）：209 行导出、`auth.login` 明细含 `{roles,provider}` 紧凑 JSON、`audit.export` total 递增。
