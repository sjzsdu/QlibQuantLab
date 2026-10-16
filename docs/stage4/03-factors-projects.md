# 03 · 因子与项目

> 覆盖 `core/qlib_expr.py`、`factor_service.py`、`project_service.py`。

## 1. 因子表达式静态校验（阶段 4 的核心约束）

`core/qlib_expr.py` 是一个**递归下降解析器**，只做静态检查、**绝不执行**任何计算（这是「API 进程零 qlib」的一部分）。

| 层 | 内容 |
|----|------|
| 词法 | 数字字面量 / 字段 `$open` `$high` `$low` `$close` `$volume` `$factor` `$vwap` / 标识符 / 运算符 / 括号 |
| 语法 | 标准算术优先级 + 一元负号；产出表达式树 |
| 白名单 | 函数约 35 个（`Ref` `Mean` `Std` `Rank` `If` `Abs` `Log` `Power` …），带元数校验（如 `Ref(x, n)` 恰 2 参） |
| 上限 | `MAX_LENGTH=500`、`MAX_DEPTH=10`（防病态输入） |

`check_expression()` **永不抛异常**，返回 `ExpressionCheckOut{valid, errors[], fields[], functions[]}`。前端 `ExpressionValidator` 组件在编辑时给出通过/失败反馈（错误精确到「第 N 列」）。

## 2. 因子版本与发布

- **表达式变更**（create 除外，update 时）→ `version + 1`；审计 detail 记 `expression_changed`。
- **发布** = 可见性 `private/org → public`，走 `?confirm=true` 两步确认（`POST /v1/factors/{id}/publish`）。发布后 `FactorOut.visibility = "public"`，全组织可见。
- 删除同样 `?confirm=true`，审计记 `op=delete`（留痕，不物理静默）。

> 阶段 4 因子**只做定义**：静态校验通过 ≠ 数值正确。真实求值、因子预览、IC/分层回测属阶段 5。

## 3. 项目成员与可见性

| 端点 | 权限 | 说明 |
|------|------|------|
| `GET /v1/projects/{id}/members` | 项目成员 | 列表 |
| `POST /v1/projects/{id}/members` | `project.manage` | 按用户名加入（org 内用户），写审计 |
| `DELETE /v1/projects/{id}/members/{uid}?confirm=true` | `project.manage` | **禁止移除自己**（防把自己锁在门外） |
| `PATCH /v1/projects/{id}/visibility?confirm=true` | `project.manage` | `private/org/public`，两步确认 + 审计 |

跨租户访问一律 **404**（不泄露存在性）；RBAC 不足 → **403 / code 1002**。前端 `projects/[id]` 页按 `hasPermission()` 降级渲染（只读角色看不到操作按钮）。

## 4. 只读任务端点（阶段 5 任务中心的前奏）

- `GET /v1/jobs?page&page_size&kind&status` — 分页列表。
- `GET /v1/jobs/{id}` — 单个任务，供导入后 2s 轮询直至终态。

只读、不提供取消/重试/日志流（阶段 5）。列表返回完整 `Paged`（`items/total/page/page_size`）；成员列表返回 `{items, total}`。
