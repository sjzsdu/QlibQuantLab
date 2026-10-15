# 03 · 前端骨架代码要点（阶段 2 交付的 `frontend/`）

> 完整代码见 `frontend/src/`。本文件讲**契约与登录态**，页面只搭骨架，业务表单留给阶段 4–5。

## 1. 技术栈（已锁定）

| 库 | 版本 | 用途 |
|----|------|------|
| next | 15.5.27 | App Router，`output: "standalone"`（生产单文件运行） |
| react | 19.3.0 | — |
| antd | 5.29.3 | 组件库、`App` 上下文、消息与弹窗 |
| @tanstack/react-query | 5.104.2 | 服务端状态、重试策略、缓存失效 |
| echarts | 阶段 5 引入 | 曲线与指标可视化 |
| TypeScript / ESLint | strict | `pnpm typecheck` + `pnpm lint` 全绿 |

## 2. 后端地址只出现在一处

```ts
// next.config.ts
const backendInternalUrl = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";
async rewrites() {
  return [{ source: "/api/:path*", destination: `${backendInternalUrl}/api/:path*` }];
}
```

浏览器**永远只用相对路径 `/api/...`**：开发模式与生产都是 Next 服务端转发。因此
- 阶段 2 契约里的 `NEXT_PUBLIC_API_BASE=/api` 只是显式标注，业务代码不拼它；
- 生产镜像必须在**构建期**注入 `BACKEND_INTERNAL_URL`（rewrites 会被序列化进产物），`docker-compose.prod.yml` 已用 `build.args` 传入 `http://backend:8000`。

## 3. 全站唯一的 HTTP 客户端 `lib/api.ts`

```ts
const BASE_URL = "/api";
export async function apiRequest<T>(path, init = {}): Promise<Envelope<T>> {
  const method = (init.method ?? "GET").toUpperCase();
  if (!SAFE_METHODS.has(method)) {                 // 非安全方法 → 附加 CSRF 头
    const token = getCsrfToken();                   // 读 cookie: qqlab_csrf
    if (token) headers.set("X-CSRF-Token", token);
  }
  const res = await fetch(`${BASE_URL}${path}`, { ...init, headers, credentials: "include" });
  // → 解信封 { code, message, data, request_id }；code !== 0 抛 ApiError
  // → 401 统一 replace 到 /login?next=...（登录页自身除外，避免死循环）
}
```

| 硬性约束 | 实现点 |
|----------|--------|
| 相对路径、无主机名 | `BASE_URL = "/api"` |
| 携带 cookie | `credentials: "include"` |
| CSRF 双提交 | `lib/cookies.ts` 读 `qqlab_csrf` → `X-CSRF-Token` |
| 401 处理 | `ApiError.isUnauthenticated` → 跳 `/login?next=` |
| 信封统一解开 | `Envelope<T>` 类型 + `code !== 0` 走 `ApiError`（带 `requestId` 便于对日志） |

## 4. 登录态：`AuthContext` → `useCurrentUser()`

```tsx
// contexts/AuthContext.tsx —— 唯一 Provider，数据来自 GET /v1/me 与 /v1/me/permissions
const meQuery = useQuery<CurrentUser | null>({
  queryKey: ["auth", "me"],
  queryFn: async () => {
    try { return await apiFetch<CurrentUser>("/v1/me"); }
    catch (e) { if (e instanceof ApiError && e.isUnauthenticated) return null; throw e; }
  },
  retry: (n, e) => !(e instanceof ApiError && e.status >= 400) && n < 2,   // 4xx 不重试
});

// 暴露：user / isLoading / permissions / can(...roles) / hasPermission(perm) / login / logout / refresh
```

```ts
// hooks/useCurrentUser.ts —— 业务代码只准用这个 hook
export function useCurrentUser(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useCurrentUser 必须在 <AuthProvider> 内部使用");
  return context;
}
```

规则（阶段 1 定的红线，阶段 6 会做 e2e 校验）：

- 前端业务代码**不得**直接读 cookie、不得 `fetch` 任何第三方地址、不得引入 Casdoor SDK；
- 权限判断只用 `can("admin")` 或 `hasPermission("project.write")`，与后端 `core/rbac.py` 同一套权限点字符串（`lib/types.ts` 里集中声明）；
- 登录走 `login(next?)`：先 `GET /api/v1/auth/login` 拿 `{url}`，再整页跳转（mock 下就是一键进入）；登出走 `logout()` → 后端清 cookie → 跳 `/login`。

## 5. 页面骨架（7 条路由）

| 路由 | 文件 | 阶段 2 内容 |
|------|------|-------------|
| `/` | `app/page.tsx` | 首页：风险提示 + 免责声明 + 模块入口卡片（未开放的模块标「阶段 N 开放」） |
| `/login` | `app/login/page.tsx` | Mock 一键进入：可选 profile（admin/researcher/viewer/auditor），登录后回 `next` |
| `/projects` | `app/projects/page.tsx` | 项目列表骨架（TanStack Query 拉 `/v1/projects`，空态 + 新建按钮占位） |
| `/audit` | `app/audit/page.tsx` | 审计日志表（分页 + action 过滤，权限点 `audit.read`） |
| `/legal/[code]` | `app/legal/[code]/page.tsx` | 协议 / 风险提示 / 免责声明，markdown 渲染（`lib/markdown.ts`，**输出前转义 HTML**） |
| `/_not-found` | `app/not-found.tsx` | 404 |
| `/` layout | `app/layout.tsx` | `AuthProvider` + `QueryClientProvider` + AntD `App` + **全站风险提示条** |

组件：`AppShell`（侧栏/顶栏/用户菜单/登出）、`RequireAuth`（未登录跳 `/login`）、`RiskBanner`（首屏常驻风险提示）、`EmptyState`。

`RiskBanner` 在 `layout.tsx` 全局挂载，**任何页面都能看到**风险提示；法务三件套（`/legal/terms|risk|disclaimer`）由 `GET /api/v1/legal/{code}` 提供正文，前端不硬编码法务文案，后端改 `src/qqlab/legal/*.md` 即可生效。

## 6. 目录与约定

```
frontend/src/
├── app/            # App Router 页面（见上表）
├── components/     # AppShell / RequireAuth / RiskBanner / EmptyState
├── contexts/AuthContext.tsx   # ★ 唯一认证入口
├── hooks/          # useCurrentUser（★ 唯一取用户方式）· useApi（React Query 封装）
└── lib/            # api.ts（★ 唯一 HTTP 客户端）· cookies.ts · types.ts · markdown.ts
```

- 组件用函数组件 + hooks；服务端组件只放静态展示，交互页一律 `"use client"`。
- 类型集中在 `lib/types.ts`，字段名与后端 `schemas/common.py` 的 `*Out` 一一对应（`user_id` / `org_id` / `roles` / `created_by`）。
- `created_by` 后端返回 **username**（不是 UUID），前端直接显示。

## 7. 构建与镜像

- `pnpm build`：typecheck 通过（`typescript.ignoreBuildErrors: false`），lint 单独跑（`eslint.ignoreDuringBuilds: true`，避免构建被 lint 阻塞）。
- `Dockerfile` 四阶段：`deps`（按 lockfile 装依赖）→ `dev`（compose bind mount 用）→ `builder`（`ARG BACKEND_INTERNAL_URL` 注入后 `pnpm build`）→ `runner`（只拷 `standalone` 产物，非 root `nextjs:1001`）。
- 阶段 2 实测：`pnpm lint` ✅、`pnpm typecheck` ✅、`pnpm build` ✅（7/7 静态页生成）。
