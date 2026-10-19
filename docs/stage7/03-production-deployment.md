# 03 · 生产部署定稿：模式 B、Traefik（R9）、Redis 拆分（R11）与切换清单

> 把 [`docs/stage1/07-deployment.md`](../stage1/07-deployment.md) §4「先列在此」的草案**定稿并实测校准**；
> 生产 compose = `docker-compose.prod.yml`（模式 B：不启动任何基础设施，只起 frontend/backend/worker/migrate，
> Traefik 经 labels 接入，应用代码零感知）。Casdoor 生产部署见 [05](./05-casdoor-deployment.md)。

## 1. 生产 compose 验证记录（阶段 7 实测）

```bash
docker compose -f docker-compose.prod.yml config --quiet     # ✅ 通过（插值完整）
docker compose -f docker-compose.prod.yml config --services  # ✅ backend frontend migrate worker
#   （qlib-server 挂 --profile qlib，按需启用；casdoor 不在其中 —— IdP 是外部服务）
docker compose -f docker-compose.prod.yml build backend frontend worker   # ✅ 见 04 §4 回归记录
```

要点核对：`name: qqlab-prod`（与 dev 栈互不干扰）；`env_file: .env` + `restart: always`；
网络 `traefik`（external）+ `internal`（`internal: true`，业务容器不出网，只经 Traefik 暴露）；
backend `--workers ${BACKEND_WORKERS:-4}`（PKCE 无状态派生 + 平台自签会话对此零共享状态要求，见 02 §2.1）；
worker `platform: ${WORKER_PLATFORM:-linux/amd64}`（pyqlib 0.9.7 无 arm64 wheel）+ `traefik.enable=false`。

## 2. 部署顺序（模式 B）

```bash
# 0. 前置：外部 pg/redis/rabbitmq/S3 就绪；Traefik 网络已建；casdoor 已部署并建好应用（docs/stage7/05）
# 1. .env：按 §4 清单改全（生产 AUTH_PROVIDER=mock 会被拒绝启动 —— fail-fast）
# 2. 迁移（一次性）
docker compose -f docker-compose.prod.yml run --rm migrate
# 3. 起栈
docker compose -f docker-compose.prod.yml up -d --build
# 4. Qlib 链路（按需）
docker compose -f docker-compose.prod.yml --profile qlib up -d qlib-server
# 5. 按 §5 验证清单逐项过
```

## 3. R9 · Traefik 长连接（Qlib WebSocket）—— 静态项 + 动态 labels 双侧定稿

**风险**：Traefik 默认的读/写/响应头超时会掐断 qlib-server 的 WebSocket 长连接 → 阶段 7 上线后 worker 数据请求全失败且报错隐蔽。

### 3.1 动态侧（compose labels，已就位 —— `docker-compose.prod.yml` qlib-server 段）

| label | 作用 |
|-------|------|
| `...headers.customRequestHeaders.Connection=upgrade` + `Upgrade=websocket` | WebSocket 升级头穿透 |
| `loadbalancer.passHostHeader=true` | 保留 Host（qlib-server 按 Host 校验） |
| `loadbalancer.responseForwarding.flushInterval=1ms` | 响应即时透传，不攒批 |
| `loadbalancer.sticky.cookie=true` | socket.io 轮询回退的会话黏性 |

### 3.2 静态侧（Traefik 实例的 `traefik.yml`，**不在 compose 里 —— 运维执行项**）

```yaml
entryPoints:
  websecure:
    address: ":443"
    transport:
      respondingTimeouts:
        readTimeout: 0        # WebSocket 长连接不能被读超时掐断
        writeTimeout: 0
      transportingTimeouts:   # Traefik v3 字段；v2 用 respondingTimeouts 同位配置
        responseHeaderTimeout: 0
        idleTimeout: 0
serversTransport:
  insecureSkipVerify: true    # 后端为 http 时
```

### 3.3 验证（进 §5 清单第 4 项）

worker 日志出现 `calendar_response` = wss 穿透 Traefik 成功；再跑一个真实回测（数据请求走 WS）收敛确认。

## 4. R11 · Redis 拆分（Qlib-Server 不支持密码）

**事实**：`qlib_server/utils.py::get_redis_connection()` 只有 `host/port/db`，**无 `password` 参数** ——
模式 B 若把 `QLIB_SERVER_REDIS_*` 指向带密码的外部 Redis，qlib-server 直接连不上。

**定稿方案（方案②，推荐）**：**两个 Redis 分责** ——

```
应用（backend/worker）── CACHE_URL=redis://:pass@app-redis:6379/0   （带密码、可公网侧接入点、随应用规模扩）
qlib-server ────────── QLIB_SERVER_REDIS_HOST=qlib-redis            （免密、仅 internal 网络、不对外）
```

- qlib-server 的 Redis 是**它自己的私有状态**（轮询/内部队列），不是应用缓存 → 单独实例不损失任何共享语义；
- 免密实例只挂 internal 网络（compose `internal: true` 语义），攻击面 = 内网；
- `QLIB_SERVER_REDIS_HOST` 与 `CACHE_URL` 两键彻底解耦（`.env.example` 已注释）；
- 兜底（方案③）：fork qlib-server 给 `get_redis_connection()` 加 `password`（改动极小，须记录补丁 commit）——
  需要单一外部 Redis 时才启用。
- 同理 RabbitMQ：给 qlib-server 建**独立账号**（vhost 授权，dev 的 rabbitmq-init 已是这个模式）。

stage1/08 R11 行状态已回写为「方案定稿 + 切换清单执行项」。

## 5. 生产切换清单（定稿，stage1/07 §4 的实测校准版）

### 5.1 必改环境变量

| 变量 | 改成 | 校验方式 |
|------|------|----------|
| `APP_ENV` | `production` | `/api/v1/system/info` 返回 env=production |
| `APP_JWT_SECRET` | ≥32 字节随机值 | 登录后 8h 内不失效；换值立即全体登出 |
| `SESSION_COOKIE_SECURE` | `true`（生产强制校验） | 浏览器 Cookie 带 `Secure` |
| `CORS_ALLOW_ORIGINS` | 仅生产域名 | 非白名单 Origin 被拒 |
| `DATABASE_URL` / `CACHE_URL` / `MQ_URL` | 外部实例（带密码） | `/ready` 全绿 |
| `STORAGE_BACKEND` / `STORAGE_S3_*` | 外部 S3 | `PUT`+`GET` 往返一致 |
| `AUTH_PROVIDER` | `casdoor` | `/api/v1/auth/login` 返回 Casdoor authorize URL |
| `CASDOOR_ISSUER` | `https://idp.example.com` | discovery 200 且 issuer 一致 |
| `CASDOOR_INTERNAL_URL` | 内网地址不同才填，否则留空 | — |
| `CASDOOR_CLIENT_ID` / `CASDOOR_CLIENT_SECRET` / `CASDOOR_REDIRECT_URI` | 与 IdP 应用注册**逐字符**一致（`https://{前端域名}/api/v1/auth/callback`） | OIDC 登录成功；缺任一**启动即失败** |
| `CASDOOR_ORG_ID_CLAIM` | `owner`（定稿；阶段 1 草案的 `x-org-id` 已废弃） | 登录后 `/me` org_id 正确 |
| `CASDOOR_ROLE_MAP` / `CASDOOR_ORG_MAP` | IdP 角色名与平台不同名时才填 JSON；**留空 = 直通**（映射后为空/未知 → 401 fail-closed） | 各角色登录实测 |
| `WORKER_STALE_JOB_MINUTES` | 默认 10；**worker 单副本前提**见 06-risks R6-2 | 重启 worker 看 `stale_running_recovered` |
| `QLIB_SERVER_WS_URL` | Traefik 暴露的 wss 地址 | worker 启动探测通过 |
| `QLIB_SERVER_REDIS_HOST` / `QLIB_SERVER_QUEUE_*` | **免密** Redis（internal 独立实例，§4）+ qlib-server 专用 RabbitMQ 账号 | qlib-server healthcheck 通过 |
| `TRAEFIK_HOST_WEB/API/QLIB`、`EXTERNAL_TRAEFIK_NETWORK` | 真实域名 / Traefik 网络名 | `curl -I https://…` 200 |

### 5.2 Traefik 侧

- labels：**已在 prod compose 里**（websecure + certresolver + sec-headers + ratelimit + qlib 全套，§3.1）——无需手抄；
- 静态项：§3.2 由运维写进 Traefik 实例配置；
- casdoor 若也挂 Traefik：其路由同样受静态超时约束影响，建议独立 entrypoint 或维持默认超时（casdoor 无长连接）。

### 5.3 切换后验证清单

1. `curl https://api.…/api/v1/health/ready` → `db/cache/mq/storage/auth` 全绿（auth = discovery 可达）。
2. 浏览器 `https://app.…` → 跳 Casdoor → 回跳成功 → `/api/v1/me` 显示真实用户名/组织/角色（`provider=casdoor`）。
3. 写操作 CSRF 正常（改名项目等）；登出 → `/login?logged_out=1` 落地且会话 Cookie 清除。
4. 提交真实回测 → 成功 → 曲线可看；**worker 日志出现 `calendar_response`**（wss 穿透 Traefik，R9 验证）。
5. 审计：`GET /api/v1/audit-logs?action=auth.login` 查到本次登录；`auth.login_failed` 在结构化日志（02 §4）。
6. 负向：直接 Bearer 访问受保护接口 → 401；跨 org 资源 → 404；连续 6 次 `GET /auth/login` → 第 6 次 429（限流）；
   无角色账号登录 → 401 fail-closed（02 §2.4）。
7. 断网演练：停外部 Redis → `/ready` 变红且提示明确；停 casdoor → 登录 503「身份服务不可达」、已登录会话不受影响（平台自签会话，D7-8）。
8. 回滚路径：`AUTH_PROVIDER` 改回 mock **仅限非生产**（生产启动即拒绝）；生产回滚 = 回滚镜像 + `alembic downgrade`（如有迁移）。

### 5.4 R9 / R11 演练验证表（阶段 8 · E 项，D8-9，`deploy/rehearsal/`）

演练入口（与开发/生产栈合并的 override，**不改 `.env`**；文件头有完整用法）：

```bash
# 表 A · Traefik WS 穿透
docker compose -f docker-compose.yml \
  -f deploy/rehearsal/docker-compose.rehearsal-traefik.yml --profile qlib up -d traefik
# 表 B · 双 Redis 拆分（演练后去 override 重建三容器即回滚）
docker compose -f docker-compose.yml \
  -f deploy/rehearsal/docker-compose.rehearsal-dual-redis.yml --profile qlib \
  up -d app-redis qlib-redis backend worker qlib-server
```

#### 表 A · Traefik WS 穿透（R9）——**待运维环境执行**

> 本机未跑真 Traefik：traefik 镜像仅发布在 docker.io（本机当前网络不可达，quay.io 无官方发布）。
> labels 与静态超时已按生产定稿（§3.1 + §3.2，1:1 照抄）固化进 override
> （`traefik:v3.7.15`，2026-10-15 发布含 CVE 修复），在有网环境逐行执行即产出实测结果。

| # | 步骤（命令） | 预期 | 判据含义 |
|---|---|---|---|
| A1 | `docker compose -f docker-compose.yml -f deploy/rehearsal/docker-compose.rehearsal-traefik.yml --profile qlib up -d traefik` | traefik 容器起且 `traefik:v3.7.15` | 演练实例就位（qlibws 入口超时全 0） |
| A2 | `curl -s http://127.0.0.1:8082/api/overview \| head -c 60` | 返回 JSON（dashboard API 活） | docker provider 正常读容器 labels |
| A3 | `curl -si 'http://127.0.0.1:9711/socket.io/?EIO=4&transport=polling' \| head -3` | `HTTP/1.1 200` + `set-cookie io=…` | socket.io 握手经 Traefik qlibws 入口穿透成功 |
| A4 | `python scripts/qlib_connectivity_smoke.py ws://localhost:9711` | 全部 check OK（含真 WS upgrade） | **R9 核心**：升级头 + 长连接不被超时掐断 |
| A5 | `curl -s http://127.0.0.1:8081/api/v1/health/live` | `status=live` | HTTP 前门 → backend 路由正确（`/api` 优先于 `/`） |
| A6 | 生产等效：worker 日志出现 `calendar_response`（§3.3） | 日志有该事件 | wss 经生产 Traefik 的最终收敛判据 |

#### 表 B · 双 Redis 拆分（R11）——本机演练**实测**（2026-10-19，阶段 8 · E 项）

> 方式：override 合并 dev 栈起 `app-redis`（带密码）+ `qlib-redis`（免密、零宿主端口），
> backend/worker/qlib-server 三容器改指各自实例；演练后去 override 重建回滚（B10 已验证）。
> 模式 B 等效：两地址换外部托管实例，键完全相同（`CACHE_URL` / `REDIS_HOST`）。

| # | 验证点（命令） | 预期 | 实测（2026-10-19） |
|---|---|---|---|
| B1 | `docker exec qqlab-app-redis-1 redis-cli ping` | `NOAUTH Authentication required.` | ✅ NOAUTH（未授权即拒） |
| B2 | `redis-cli -a rehearsal-app-redis-pass ping`（经 `127.0.0.1:16380`） | `PONG` | ✅ PONG |
| B3 | `docker port qqlab-qlib-redis-1` | 无输出（零宿主端口） | ✅ 空（免密实例不出内网） |
| B4 | `docker exec qqlab-backend-1 printenv CACHE_URL`（worker 同） | `redis://:…@app-redis:6379/5` | ✅ 两容器一致（override `environment:` 覆盖 env_file） |
| B5 | `docker exec qqlab-qlib-server-1 printenv REDIS_HOST` | `qlib-redis` | ✅ |
| B6 | `curl -s localhost:8000/api/v1/health/ready` | `cache=true`，全绿 | ✅ `database/cache/queue/storage/auth` 全 true |
| B7 | `redis-cli -a … -n 5 keys 'qqlab:*'`（app-redis） | 见 `qqlab:worker:heartbeat` | ✅ 心跳落 app-redis；`/api/v1/metrics` 读回 `qqlab_worker_up 1`、`heartbeat_age_seconds 4.9` |
| B8 | worker 日志 `qlib_server_probe` | `ok=true detail=ws://qlib-server:9710` | ✅ Qlib-Server 在**免密实例**上存活并完成 socket.io 握手 |
| B9 | `redis-cli -a … -n 0 dbsize`（app-redis） | 0（无 qlib-server 状态键） | ✅ 两实例互不串数据；宿主亦无端口可达 qlib-redis |
| B10 | 回滚：去 override `up -d backend worker qlib-server` | 恢复单实例且 probe ok | ✅ backend healthy + `qlib_server_probe ok=true` |

## 6. 附：Docker Hub 不可达环境的镜像获取

生产构建同样受镜像源约束，按阶段 6/7 两次实测的配方（详细命令与 digest 见
[`deploy/casdoor/README.md`](../../deploy/casdoor/README.md) 与 05 §3）：

1. 镜像源 token：`GET https://{mirror}/openapi/v1/auth/token?service={mirror}&scope=repository:<name>:pull`；
2. manifest（带 list Accept 头）读目标架构 digest；
3. `docker pull {mirror}/<name>@sha256:<digest>`（按 digest，不吃 `--platform` 的坑）；
4. `docker tag` 回规范名 —— BuildKit 本地 digest 匹配即不再出网解析。

已固化 digest：python:3.12-slim amd64、python:3.11-slim amd64（worker）、docker/dockerfile:1、node:22-alpine、
casbin/casdoor-all-in-one（amd64/arm64 双架构）。

**Python 轮子（uv）同理**：镜像层缓存未命中时 `uv sync` 要下 ~300MB（qlib extra），PyPI 直连劣化时
出现「10+ 分钟下不完 + 偶发轮子字节损坏（`deflate decompression error: repeated call with bad state`）」
（阶段 7 实测 ~37KB/s，见 04 §4）。注意两个反直觉事实：① `uv.lock` 锁定了每个轮子的下载 URL，
`uv sync --frozen` **不理会** `UV_DEFAULT_INDEX`（实测传镜像站 build-arg 仍走 pythonhosted 直连）；
② 镜像站索引页吞吐实测 23–48MB/s，但只对重新解析（`uv lock`）生效，救不了已锁定的同步。
真正的解法已固化进 `backend/Dockerfile`：四处 `uv sync` 均为
`RUN --mount=type=cache,target=/root/.cache/uv uv sync …` —— 已下载轮子留在 BuildKit 缓存挂载中，
失败重试**增量续传**，劣化网络下有限次重试必收敛（构建命令不变、无需任何参数）。
