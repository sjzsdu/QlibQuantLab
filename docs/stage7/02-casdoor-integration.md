# 02 · Casdoor 接入：授权码 + PKCE + JWKS 全链路

> 对应实现：`backend/src/qqlab/adapters/auth/casdoor_provider.py`（模块 docstring 与本文互引）、
> `api/v1/auth.py`、`services/auth_service.py`、`config.py`、`container.py`。
> 实机验证：`scripts/stage7_smoke.py`（17 项）+ `tests/unit/test_casdoor_provider.py` + `tests/api/test_auth_flow.py`。

## 1. 端口契约与装配

`AuthPort` 五方法**一字不改**（阶段 1 定稿），mock / casdoor 同一契约：

| 方法 | mock | casdoor（阶段 7 实装） |
|------|------|------------------------|
| `get_login_url(state, redirect_to)` | 拼站内 `/auth/mock/enter` | 拼 `{ISSUER}/login/oauth/authorize?...` + PKCE |
| `handle_callback(code, state)` | 以 profile 入会话 | code+verifier 换 token → JWKS 验签 → claim 映射 |
| `verify_token(token)` | 校验平台 HS256 会话 | **同 mock**（D7-8：IdP 令牌只回调用一次） |
| `get_logout_url(redirect_to)` | 站内登出落点 | Casdoor `/api/logout` RP-initiated（post-logout 落点） |
| `healthcheck()` | 恒 True | discovery 端点可达性（3s 超时） |

装配在 `container.py`：`AUTH_PROVIDER=casdoor` 时构造 `CasdoorAuthProvider(settings, cache=container.cache)` —— **JWKS 缓存走平台 `CacheProvider`**（dev memory / prod redis，适配器无状态）。
依赖只进 adapters：`httpx` + `pyjwt[crypto]`（RS256 由 cryptography 提供）；架构测试 `FORBIDDEN_SDKS` 含 casdoor，业务代码 import 扫描仍只认 `qqlab.ports`。

### 启动即校验（`config.py`）

- `AUTH_PROVIDER=casdoor` 缺 `CASDOOR_ISSUER / CLIENT_ID / CLIENT_SECRET / REDIRECT_URI` 任一 → `ValueError`，**启动失败**（开发也一样，fail-fast）。
- 生产（`APP_ENV=production`）下 `AUTH_PROVIDER=mock` → 直接拒绝启动。
- `CASDOOR_ROLE_MAP / ORG_MAP` 走 `_json_str_map` validator：必须是 JSON 对象（`{}` 合法 = 直通）。

## 2. 登录全链路（时序）

```
浏览器                平台后端                      Casdoor
  │  GET /api/v1/auth/login            │                   │
  │───────────────────────────────────>│ state 签发落缓存   │
  │            {url, state}            │ (TTL 600s, 存落点) │
  │<───────────────────────────────────│                    │
  │  302 {ISSUER}/login/oauth/authorize?client_id&response_type=code
  │    &redirect_uri&scope&state&code_challenge=S256(verifier)
  │──────────────────────────────────────────────────────> │ SPA 登录表单
  │  （会话 cookie 在 → 直接发码）                          │ /api/login type=code
  │<── 302 {REDIRECT_URI}?code=...&state=... ──────────────│
  │  GET /api/v1/auth/callback?code&state                   │
  │───────────────────────────────────>│ POST /api/login/oauth/access_token
  │                                    │  (code+verifier+secret)────────> │
  │                                    │<──── id_token (RS256) ──────────│
  │                                    │ JWKS 验签(RS256/exp/aud/iss)     │
  │                                    │ claim 归一 → org/role 映射        │
  │  302 / + Set-Cookie(qqlab_session HttpOnly, qqlab_csrf) │ ensure_org   │
  │<───────────────────────────────────│ audit auth.login 落表(org 内)     │
```

### 2.1 PKCE S256 —— verifier 无状态派生

```python
verifier  = b64url(HMAC-SHA256(client_secret, b"qqlab-pkce:" + state))
challenge = b64url(sha256(verifier))
```

- `get_login_url` 是**同步**端口方法 → 不能 await 写缓存；推导式零状态。
- 生产 `BACKEND_WORKERS=4` 多进程 → 推导式天然共享，落缓存反而要求跨进程共享存储。
- verifier 与 `client_secret` 绑定：截获 `code+state` 的攻击者无法构造 verifier。
- 代价：`state` 必须在登录发起侧签发且可复算 —— 正好与 `auth_service` 的 state 缓存（`_STATE_TTL=600`，一次性 `_consume_state`）互补：state 缓存管「未使用过 + 未过期」，HMAC 管「verifier 可复算」。

### 2.2 token 兑换与 iss 双白名单（casdoor#1622）

- 兑换走 `_api_base`（`CASDOOR_INTERNAL_URL` 优先，否则 `ISSUER`）：`POST /api/login/oauth/access_token`。
- **实测事实**：Casdoor 的 `iss` 按**请求 Host 派生**（casdoor#1622）—— 经 `http://casdoor:8000` 兑换时 id_token 的 iss 是 `http://casdoor:8000`；经宿主端口兑换时是 `http://localhost:8001`。
  → `Settings.casdoor_issuers = (ISSUER, INTERNAL_URL去重)`，`pyjwt.decode(issuer=...)` 接受任一。
- 网络错误 → `DependencyUnavailableError`（503 语义「身份服务不可达」）；非 200 → `UnauthorizedError`「授权码兑换失败」。

### 2.3 JWKS 验签

- `GET /api_base/.well-known/jwks`，按 token header `kid` 选钥 → `RSAAlgorithm.from_jwk`。
- 缓存：`qqlab:auth:jwks:{issuer}`，TTL **3600s**；**未知 kid 强制刷新一次**（密钥轮换不等 TTL）。
- `pyjwt.decode(algorithms=["RS256"], aud=CLIENT_ID, issuer=白名单, options=require exp/iss/aud)`。
- 实测：dev 种子的 kid = `cert-built-in`（casdoor 内置证书），JWKS 单 RSA 密钥。
- 缓存损坏（JSON 解析失败）→ 静默重拉；TTL 过期语义由 `test_memory_cache_ttl_expiry_semantics` 锁死（评审点③）。

### 2.4 claim 归一与身份映射（fail-closed）

| 环节 | 规则 |
|------|------|
| org | `claims[CASDOOR_ORG_ID_CLAIM]`（默认 `owner`）缺失 → 401；`ORG_MAP` 命中替换，否则**直通原值**（D7-2，dev 即 org 名 `qqlab`） |
| roles | `CASDOOR_ROLE_CLAIM`（默认 `roles`）**三形态归一**：字符串 / 字符串数组 / **Role 对象数组**（`[{owner,name}...]` 取 `name` —— Casdoor JWT 内嵌完整 user struct 时的形态） |
| ROLE_MAP | 逐个映射；映射后为空 → 401「账号未分配任何角色，拒绝登录（fail-closed）」（D7-3） |
| 平台角色 | `Role.parse_all` 失败（映射结果含未知角色）→ 401「角色未授权……请联系管理员配置 ROLE_MAP」；**不降级、不猜测** |
| sub / username | `sub` 缺失 → 401；username 取 `preferred_username/name/sub`；display 取 `displayName/name/username` |

**smoke 实证**（三形态之一）：`roles` claim 为 Role 对象数组时仍归一成 `['admin']` / `['viewer']`；`smoke-norole`（无角色）与 `smoke-unknown`（角色 `operator` 不在平台角色表）均 401 fail-closed。

### 2.5 ensure_org 与 rename 守卫

登录成功 → `identity.ensure_org(org_id, slug, name, rename_existing=user.org_name is not None)`：

- Casdoor token **不带组织显示名**（`org_name=None`）→ 缺省按 slug 生成显示名。
- **守卫**：只有当前用户本来就没绑定组织显示名（`org_name is None`）才允许 ensure_org 为已存在的平台组织补名/改名；
  若用户已带组织名（mock/已建组织），**绝不重命名既有组织** —— 防止 casdoor `org_name=None` 回退把平台已存在的组织（如 `built-in`）改掉。单测：`test_identity_ensure_org.py` 3 例。

### 2.6 会话与前端（零改动承诺）

- 回调成功仍由**平台自己签发** HS256 会话 JWT（`APP_JWT_SECRET`，TTL `APP_JWT_TTL_SECONDS=28800`）：
  `Set-Cookie qqlab_session`（HttpOnly、SameSite=Lax、生产 Secure）+ `qqlab_csrf`（双提交，写请求带 `X-CSRF-Token`）。
- 前端只认 `useCurrentUser()` / `/api/v1/me`（返回 `provider/org_id/roles/username`）；
  登录页读 `/system/info.auth_provider`：`casdoor` → 隐藏 mock profile 选择器与「一键进入」（D7-10）。
- 因此 mock → casdoor 切换 = **只改环境变量，前后端代码零改动**（README 承诺兑现）。

## 3. 登录限流（全 `/api/v1/auth*` 路径）

- `RATE_LIMIT_LOGIN_PER_MIN=5`，路径判定 `path.startswith("/api/v1/auth")` —— **`GET /auth/login` 发起与 `GET /auth/callback` 回调各计一次**（一轮真实登录 = 2 命中）。
- 身份 = **会话用户** `user:<id>`（cookie 有效）否则 **IP**；带无效 cookie 的请求落回 IP 桶。
- dev `RATE_LIMIT_ENABLED=true` 实测生效：冒烟两轮各 4 命中必须错峰 60s（承接 R6-3）；429 语义与审计见 `test_ratelimit.py`。

## 4. 审计与安全事件

| 事件 | 落点 | 实测 |
|------|------|------|
| 登录成功 `auth.login` | `audit_logs` 行（org 内可查），detail `{roles, provider}` | smoke：`/audit-logs?action=auth.login` total 递增 |
| 登录失败 `auth.login_failed`（`error=` 回调 / 坏 state） | 发生在身份解析前 → **无 org 归属 → 不落租户审计表**（`DbAuditWriter` 跨租户隔离设计）；结构化日志 `audit_skipped_no_org` 留存（本阶段补强：含 `action/detail/ip/outcome/request_id`） | smoke：`docker logs backend` 断言 `audit_skipped_no_org` + `auth.login_failed` |
| 登出 `GET /auth/logout` | 清 session/csrf Cookie（值为带引号空值 + Max-Age=0）+ 返回 `{redirect_to}`；日志 | smoke：Cookie 清除断言 |

> 为什么失败登录不落表：`audit_logs` 查询强制 org 范围（跨租户 = 404 的同一条硬约束），
> 失败登录尚无身份即无 org；写入只会产生**任何租户都查不到**的行。安全信号改由结构化日志承载，
> 与 HTTP 中间件的 401 行（`path=/api/v1/auth/callback status=401` + `request_id`）可互相关联。详见 06-risks R7-3。

## 5. 登出（RP-initiated）

- `GET /api/v1/auth/logout?next=...` → `get_logout_url(next)`：
  `{ISSUER}/api/logout?post_logout_redirect_uri={origin}/login?logged_out=1&next=...&client_id=...`
- 落点是**绝对地址**且必须注册进 Casdoor 应用 RedirectUrls（casdoor `IsRedirectUriValid` 为宽松匹配 —— dev 种子把 `/login` 落地一并注册）。
- **实测（R7-2 回写）**：该镜像构建下，落点已注册时**带与不带 `id_token_hint` 都 302 到落地页** → 契约不扩参数（见 05 §4）；平台侧 Cookie 清除 + `logged_out=1` 落地页前端处理。

## 6. mock ↔ casdoor 切换

```bash
# dev 切 Casdoor（不改 .env，冒烟/体验用）
docker compose --profile casdoor up -d casdoor       # 宿主 8001 → 容器 8000（种子自动应用）
docker compose -f docker-compose.yml -f docker-compose.casdoor-smoke.yml up -d backend
python3 scripts/stage7_smoke.py                      # 17 项
docker compose up -d backend                         # 还原：只用默认文件即不含覆盖 env

# 生产：AUTH_PROVIDER=casdoor + CASDOOR_* 四要素（缺一项启动即失败），见 docs/stage7/03/05
```

`docker-compose.casdoor-smoke.yml` 是**可复现工件**（不是一次性文件）：内容 = 冒烟用的 casdoor env 块，
文档 05 引用它作为「切 Casdoor 的最小环境清单」。
