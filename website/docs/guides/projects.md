---
title: 项目
sidebar_label: 项目
description: 项目指南：创建、可见性、成员与删除的门槛，字段含义、接口对应、权限要求与常见错误码。
---

# 项目

项目（Project）是研究内容的最小容器：数据集、因子、模型、策略、回测都挂在项目下。它同时是**可见性**的边界 —— 同一个组织里，不同课题不应该互相看见。

![项目列表页](/img/screens/projects.webp)

## 创建一个项目

在 `项目` 页点 **新建项目**，填名称与描述即可。新项目默认 `private`。

等价的接口调用：

```bash
curl -s -X POST localhost:8000/api/v1/projects \
  -H 'Content-Type: application/json' \
  -H "X-CSRF-Token: $CSRF" -b cookies.txt \
  -d '{"name": "CSI300 动量因子研究", "description": "研究 20 日动量在中证 300 上的稳定性"}'
```

:::note 非安全方法需要双提交 CSRF
除 GET/HEAD 之外的请求要带 `qqlab_csrf` cookie 对应的 `X-CSRF-Token` 头。前端已自动处理；写脚本时先 `GET /api/v1/me` 拿到 cookie 与 token。
:::

### 字段

| 字段 | 说明 | 约束 |
| --- | --- | --- |
| `name` | 项目名 | 必填，≤200 字符 |
| `description` | 描述 | 可空 |
| `visibility` | `private` / `org` / `public` | 新建固定为 `private`，之后单独切换 |
| `org_id` | 所属组织 | **不可传**，来自会话 |

## 可见性

| 取值 | 谁能看见 |
| --- | --- |
| `private` | 项目成员（创建者自动是成员） |
| `org` | 本组织所有成员 |
| `public` | 本组织 + 被显式分享的场景 |

切换可见性是高危操作：**仅 admin**，且必须带 `?confirm=true`。

```bash
curl -s -X POST "localhost:8000/api/v1/projects/$PID/visibility?confirm=true" \
  -H 'Content-Type: application/json' \
  -H "X-CSRF-Token: $CSRF" -b cookies.txt \
  -d '{"visibility": "org"}'
```

漏掉 `confirm=true` 会得到 `1007`（需要二次确认），不会静默生效。

## 成员

| 操作 | 接口 | 需要权限 |
| --- | --- | --- |
| 查看成员 | `GET /api/v1/projects/{id}/members` | `project.read` |
| 添加成员 | `POST /api/v1/projects/{id}/members` | `project.member.manage`（admin / researcher） |
| 移除成员 | `DELETE /api/v1/projects/{id}/members/{user_id}?confirm=true` | `project.member.manage` |

添加成员时 `username` 必须是**本组织**的用户，`role` 取 `viewer` / `researcher` / `admin`。跨组织用户不在候选里 —— 多租户边界先于成员关系。

## 删除

`DELETE /api/v1/projects/{id}?confirm=true`，**仅 admin**。删除是级联的：项目下的数据集、因子、模型、回测都会失效，所以务必先看一眼项目里有什么。

## 权限速查

| 动作 | admin | researcher | viewer | auditor |
| --- | --- | --- | --- | --- |
| 读项目 | ✅ | ✅ | ✅ | ✅ |
| 新建 / 编辑 | ✅ | ✅ | — | — |
| 管理成员 | ✅ | ✅ | — | — |
| 切换可见性 | ✅ | — | — | — |
| 删除 | ✅ | — | — | — |

## 常见错误码

| code | HTTP | 在这里的含义 | 怎么办 |
| --- | --- | --- | --- |
| `1001` | 401 | 未登录或会话过期 | 重新登录 |
| `1002` | 403 | 权限不足（如 viewer 想建项目） | 换有权限的角色，或让 admin 授权 |
| `1003` | 404 | 项目不存在，**或属于其他组织** | 检查 id；跨组织访问故意返回 404 而不是 403 |
| `1004` | 409 | 同名 / 冲突（如重复添加成员） | 换名称或先移除成员 |
| `1005` | 422 | 字段不合法（空名、超长） | 看 `message` 里的具体字段 |
| `1007` | 422 | 缺 `?confirm=true` | 高危操作补上二次确认参数 |
| `1006` | 429 | 触发限流（写操作默认 120 次/分钟） | 降速重试 |

## 相关

- [核心概念 · 角色与权限](/docs/concepts#角色与权限)
- [因子指南](/docs/guides/factors) —— 因子必须属于某个项目
- [回测指南](/docs/guides/backtests)
