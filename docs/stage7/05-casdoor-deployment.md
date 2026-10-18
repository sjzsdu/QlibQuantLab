# 05 · Casdoor 部署：dev 种子拓扑与生产指南

> 配套：`deploy/casdoor/init_data.json`（dev 种子）、`deploy/casdoor/README.md`（镜像 digest / manifest 探测 / 排查速查）、
> `docker-compose.yml` casdoor 服务块（`--profile casdoor`）。环境变量语义见 `.env.example` Casdoor 段。

## 1. dev 部署（模式 A 栈内，`--profile casdoor`）

```bash
docker compose --profile casdoor up -d casdoor
# 宿主 8001 → 容器 8000；健康即 discovery 200：curl -s localhost:8001/.well-known/openid-configuration
```

服务块要点（`docker-compose.yml`）：

| 项 | 值 | 理由 |
|----|----|------|
| image | `casbin/casdoor-all-in-one:latest` + `platform: ${CASDOOR_PLATFORM:-linux/amd64}` | 与本栈一致（qlib 链 amd64）；Apple Silicon 走 Rosetta。**阶段 6 教训**：镜像源对 `--platform` tag 会错发架构，必须按 digest 锁定（见 §3） |
| 存储 | `driverName=sqlite`、`file:/data/casdoor.db?cache=shared`，卷 `casdoor_data` | dev 零外部依赖；entrypoint 脚本支持 env 覆盖数据源 |
| 种子 | `./deploy/casdoor/init_data.json:/init_data.json:ro` | casdoor 启动时读取应用（`initDataNewOnly=false`：**新建+更新**，幂等） |
| healthcheck | `curl -fsS /.well-known/openid-configuration` | 镜像内有 curl 无 wget；discovery 是本栈真正依赖的活性信号 |
| 端口 | `${HOST_PORT_CASDOOR:-8001}:8000` | 浏览器可达地址 = `CASDOOR_ISSUER=http://localhost:8001` |

### dev 双地址拓扑（D7-7）

```
浏览器 ── http://localhost:8001 ──> casdoor:8000   （authorize / 登出：ISSUER）
后端容器 ─ http://casdoor:8000 ────> casdoor:8000   （token / discovery / JWKS：INTERNAL_URL）
```

- `CASDOOR_ISSUER`（浏览器可达）与 `CASDOOR_INTERNAL_URL`（容器内可达）分设；
- 两者都进 **iss 白名单**（`Settings.casdoor_issuers`）—— 因为 casdoor 的 iss 按请求 Host 派生（§4）。
- 生产两地址相同时 `CASDOOR_INTERNAL_URL` 留空即可。

## 2. `init_data.json` 种子语义（dev/冒烟专用）

casdoor 启动时幂等应用（同一文件反复重启零 panic，已双连启动实测）。**生产不用它**（见 §5），
手工/脚本建资源时以下坑全部来自 dev 实测：

| 坑 | 规则 |
|----|------|
| owner 字段 | **org 与 application 的 `owner` 必须是 `"admin"`** —— casdoor 会把 owner 归一到 admin；写组织名会导致重启后 UNIQUE 约束 panic 循环。org 名靠 `name` 字段（`{"owner":"admin","name":"qqlab"}`） |
| 归属组织 | 用户/角色的 owner 用组织名 `qqlab`（用户归 org，org 归 admin） |
| signinMethods | 字段名是 **`name`**（`{"name":"Password","displayName":"Password","rule":"All"}`），不是 `signinMethod` |
| themeData / formCss | **必须省略** —— 该版本把类型改成了 object，给字符串会类型不匹配 |
| grantTypes | 含 `password`（ROPC）—— 阶段 7 用它探测 JWT 内嵌 claim 形态（roles 对象数组/owner/aud 数组），仅 dev |
| redirectUris | 4 条：`{origin}/api/v1/auth/callback`（登录）+ `{origin}/login`（post-logout 落地，宽松匹配使 logout 免 `id_token_hint` 成立） |
| 用户密码 | 5 个已知密码的种子用户（admin + 4 个冒烟账号），全部**只设 Password 登录方式** |

种子清单：orgs `admin/built-in` + `admin/qqlab`；app `admin/app-qqlab`（client `qqlab-dev-client` / secret
`qqlab-dev-secret-0123456789abcdef`）；roles admin/researcher/viewer/auditor/operator；users
`built-in/admin`、`qqlab/smoke-{admin,viewer,norole,unknown}`。
冒烟三轮分别验证：直通映射成功、fail-closed（无角色）、fail-closed（平台未知角色 `operator`）。

## 3. 镜像获取（Docker Hub 不可达环境）

镜像源（如 `docker.1ms.run`）**先探 manifest、再按 digest 拉**，最后 retag —— 详细命令固化在
[`deploy/casdoor/README.md`](../../deploy/casdoor/README.md)。阶段 7 实测 digest：

| 架构 | casbin/casdoor-all-in-one digest |
|------|----------------------------------|
| **linux/amd64**（本栈用） | `sha256:ba602519188c5f5c31e77efa5b7b53dcc758bb3625122dd6e33ac5ef25c4772e` |
| linux/arm64 | `sha256:6238df5d4b9d4a86de22b173c544fd4d766e08d41132b3eeb375c98e0ff38154` |

为什么必须探 manifest（评审点② / 阶段 6 教训）：镜像源对 tag 的 `--platform` 拉取可能命中本地缓存或错发架构；
BuildKit 即使本地有同 tag 也会去 docker.io 解析 → 必须**按 digest 拉、本地 digest 匹配**才可靠。

## 4. 实测回写（R7-2：Casdoor 行为与主干文档的差异）

阶段 7 对实跑镜像（`casbin/casdoor-all-in-one`，2026-10-18 实测）的探测结论 —— 后续升级镜像后**先跑 `stage7_smoke` 再上量**：

| 探测项 | 实测结果 | 影响 |
|--------|----------|------|
| discovery issuer | `http://localhost:8001`（按请求 Host） | 与 `CASDOOR_ISSUER` 一致才验签通过 |
| **id_token iss 派生** | 按**兑换请求的 Host**：走 `casdoor:8000` → `http://casdoor:8000`（casdoor#1622） | → iss 白名单含 INTERNAL_URL（§1） |
| `/login/oauth/authorize` | **无服务端路由**（SPA 承接，返回 index.html，由前端读 query 完成登录） | `get_login_url` 的参数照样被 SPA 消费；冒烟用 `/api/login` 直接模拟浏览器（`type=login` → `type=code`） |
| `/api/login type=code` | 授权码 + OAuth 参数以 **query 参数**回传（`clientId,responseType,redirectUri,scope,state,code_challenge,code_challenge_method`），凭据在 body（含 `signinMethod:"Password"`） | 冒烟的「模拟浏览器」实现依据 |
| ROPC（`grant_type=password`） | 返回完整 user struct 进 id_token：`owner`、`roles` 为**对象数组**、`aud` 数组、`azp` | roles 三形态归一 + D7-2 owner 直通的实证来源 |
| JWKS | RSA/RS256，kid `cert-built-in` | 冒烟/单测均按此形态 |
| **logout（无 `id_token_hint`）** | 落点已注册时，**带与不带 hint 都 302 到落地页**（该构建源码与主干不一致，主干要求 hint） | `get_logout_url` 不扩契约（01 决策 5）；**升级镜像时此项必复测**（R7-2 主风险） |
| 参数less `/api/logout` | 清会话返回 JSON | 平台登出只用带落点的 URL |

## 5. 生产部署（模式 B，指南不在本栈执行）

原则：**生产 IdP 是外部有状态服务，与应用栈解耦** —— `docker-compose.prod.yml` 不含 casdoor 服务（实测 `config` 输出仅 backend/frontend/migrate/worker）。

1. **拉镜像**：按 §3 digest 流程拉 `casbin/casdoor-all-in-one`（生产建议固定 digest，不用 `latest`）。
2. **外部 PostgreSQL**（推荐）：casdoor env `driverName=postgres` + `dataSourceName=postgres://user:pass@host:5432/casdoor?sslmode=disable`；数据卷只放证书/上传。
3. **建资源**（手工或脚本，**不用 init_data.json** —— 那是 dev 种子，含明文密码与 ROPC 开关）：
   - org（组织名 = 期望的 `org_id`，对应 `CASDOOR_ORG_ID_CLAIM=owner` 直通语义）；
   - application：`clientId/clientSecret`（≥32 随机）、
     **RedirectUrls = `https://{前端域名}/api/v1/auth/callback` + 登出落点 `https://{前端域名}/login`**、
     grantTypes 含 `authorization_code`（+ 刷新按需）、signinMethods 按企业要求（可关 Password 只留 OIDC/LDAP/SAML 上游）；
   - 角色：**与平台 `Role` 枚举同名**（admin/researcher/viewer/auditor/operator）—— `ROLE_MAP={}` 直通才成立；
     若 IdP 侧命名不同，用 `CASDOOR_ROLE_MAP` 映射，映射后为空/未知一律 401（fail-closed）。
4. **应用侧 env**：`AUTH_PROVIDER=casdoor` + `CASDOOR_ISSUER=https://idp.example.com`（+ 生产若内网地址不同再设 `INTERNAL_URL`）、
   `CASDOOR_CLIENT_ID/SECRET/REDIRECT_URI`、`CASDOOR_ORG_ID_CLAIM=owner`、`CASDOOR_ROLE_MAP/ORG_MAP` 按需 ——
   缺四要素任一，**后端启动即失败**；生产 `AUTH_PROVIDER=mock` 会被拒绝启动。
5. **健康与验证清单**：
   - `GET {ISSUER}/.well-known/openid-configuration` 200 → casdoor 活；
   - `/api/v1/health/ready` 含 auth 依赖健康（`healthcheck()` = discovery 可达性）；
   - 浏览器走一遍：登录 → `/api/v1/me` 显示 `provider=casdoor` → 写操作 CSRF 正常 → 登出回 `/login?logged_out=1`；
   - 限流验证：连续 6 次 `GET /auth/login` 应第 6 次 429（`RATE_LIMIT_LOGIN_PER_MIN=5`）。
6. **流量入口**：Traefik 只暴露 HTTPS；casdoor 若也走 Traefik，注意其 WebSocket/长连接与静态超时项由 03 §3 统一约束。

## 6. 故障排查速查

| 症状 | 排查 |
|------|------|
| 后端启动 `缺少必填配置` | `AUTH_PROVIDER=casdoor` 但 `CASDOOR_*` 四要素缺项（启动即失败，fail-fast） |
| 回调 401「授权码兑换失败」 | redirect_uri 与应用注册**逐字符**不一致；code/state 已用过或过期（state TTL 600s） |
| 回调 401「签名密钥未知」 | kid 不在 JWKS（缓存陈旧/密钥轮换）→ 代码会强刷一次；仍失败查 `GET {api_base}/.well-known/jwks` |
| 回调 400「登录 state 无效或已过期」 | 未从本平台 `GET /auth/login` 发起（state 一次性 + 600s） |
| 401「缺少组织 claim」 | `CASDOOR_ORG_ID_CLAIM` 与实际 JWT 字段不符（默认 `owner`，dev/ROPC 实测如此） |
| 401「角色未授权……ROLE_MAP」 | 映射后含平台未知角色 —— 配 `CASDOOR_ROLE_MAP` 或在平台加角色，**不要**改 fail-closed 语义 |
| 登出后仍登录 | 落点未注册进应用 RedirectUrls（`post_logout_redirect_uri` 必须绝对地址且已注册） |
| 容器不健康 | `docker logs casdoor`；种子里 owner/字段名坑见 §2；discovery 是否 200 |
