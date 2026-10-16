# 04 · 前端

> 覆盖 `frontend/src/app/{data,factors,projects}`、`components/ExpressionValidator.tsx`、`AppShell.tsx`、`lib/types.ts`。

## 1. 导航

`AppShell.tsx` 增加「数据管理 `/data`」「因子库 `/factors`」两个一级菜单项，并修复了嵌套路由（如 `/data/datasets/[id]`）下父级菜单不高亮的问题（`selectedKeys` + `parentMenuKey`）。

## 2. 页面

| 路由 | 内容 | 关键交互 |
|------|------|----------|
| `/data` | 三 Tab：数据源 / 授权台账 / 数据集 | 台账 Tab 仅 `data.license.manage` 可增改吊销；数据集表单只列出 **active 台账**（合规链在 UI 上可见） |
| `/data/datasets/[id]` | 信息卡 + 导入 + 三预览 Tab | 「导入数据」→ 入队 → **每 2s 轮询** `/jobs/{id}` 直至终态 → 成功后 invalidate 数据集信息与预览 |
| `/factors` | 列表 + 新建 Modal | TextArea 编辑表达式 + `ExpressionValidator` 实时校验反馈 |
| `/factors/[id]` | 编辑 / 校验 / 发布 / 删除 | 发布走 `modal.confirm`；只读角色降级为提示条 |
| `/projects/[id]` | 成员管理 + 可见性 | 移除成员 `Popconfirm`；可见性切换二次确认 |

## 3. ExpressionValidator 组件

`components/ExpressionValidator.tsx` 封装「校验表达式」按钮 + 结果反馈：
- 通过 → `Tag` 成功 + 解析出的字段/函数清单；
- 失败 → `Alert` error + 逐条错误列表（复用 `/v1/factors/validate`）。

## 4. 数据层

- `lib/types.ts` 补齐阶段 4 类型：`DataSource` `DataLicense` `Dataset` `DatasetPreview` `Factor` `ExpressionCheck` `Job` `ProjectMember`。
- 统一走 `useApiQuery` / `useApiMutation`（`hooks/useApi.ts`），自动带 cookie、解信封、401 跳登录。
- 任务轮询用 TanStack Query `refetchInterval`，终态（`succeeded/failed/canceled`）停止。

## 5. 验证

`pnpm lint` ✓ · `pnpm typecheck` ✓ · `pnpm build` ✓（9 路由）· 浏览器冒烟：四域页面均正常渲染，数据集详情三 Tab 加载真实标的/日历数据。

> `.gitignore` 原有的运行期 `data/` 规则会误吞 `frontend/src/app/data/`，已加 `!frontend/src/app/data/` 负向规则放行。
