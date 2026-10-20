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
      # 阶段 9 实测修正（v3.7.15）：早前的 `transportingTimeouts`（responseHeaderTimeout/
      # idleTimeout）为不存在字段（启动即拒）—— 上游侧超时改在全局
      # serversTransport.forwardingTimeouts（见 §3.2 末），入口 respondingTimeouts 与之配合。
serversTransport:
  insecureSkipVerify: true    # 后端为 http 时
  forwardingTimeouts:         # v3.7.15 实测唯一正确位置（阶段 9 修正，实例见 deploy/rehearsal/）
    responseHeaderTimeout: 0
    dialTimeout: 30s
```

### 3.3 验证（进 §5 清单第 4 项）

socketio 事件 `calendar_request → calendar_response` 经 Traefik 往返成功 = 入口穿透收敛；
再跑一个真实回测收敛确认。

> **阶段 9 判据修正**：原判据「worker 日志出现 `calendar_response`」双层不可达成——
> ① worker 的 qlib provider 全为 `Local*`（数据走本地共享卷，见 stage1/06 §8.6 定性），
> 从不向 server 发 `calendar_request`；② 即便发出，stock pyqlib 0.9.7 的请求体为 pickle、
> 而 qlib-server `@0ad527d3` 是 `json.loads`（阶段 9 实测 server 侧 UnicodeDecodeError，无响应）。
> 现行判据 = **事件往返脚本（JSON body）+ worker 启动 `qlib_server_probe ok=true` + 真实回测
> succeeded**，三者已在阶段 9 演练栈实测通过（§5.4 表 A A6；证据链见 `docs/stage9/03`）。

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
4. 提交真实回测 → 成功 → 曲线可看；**socketio `calendar_request→calendar_response` 经 Traefik
   往返 + worker 启动 `qlib_server_probe ok=true`**（穿透 Traefik，R9 验证；原「worker 日志
   `calendar_response`」判据不可达成，见 §3.3 修正注记）。
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

#### 表 A · Traefik WS 穿透（R9）——阶段 9 演练栈**实测**（2026-10-19）

> **入口**：阶段 8 的 dev 栈 override 入口（上文代码块第一条，`docker-compose.rehearsal-traefik.yml`）
> 在阶段 9 被**生产等效演练栈**取代：`./scripts/rehearsal_up.sh` 起 infra-sim + prod-rehearsal 双 compose
> （`traefik:v3.7.15`，labels/静态超时与 §3.1+§3.2 生产定稿 1:1，入口 `:9711 = qlibws`）。
> 旧 override 保留供表 B 历史用，**勿与 rehearsal_up.sh 并跑**（同占 9711 端口会冲突）。
> 完整证据链与命令记录见 [`docs/stage9/03`](../stage9/03-rehearsal-validation.md)。

| # | 步骤（命令） | 预期 | 实测（2026-10-19） |
|---|---|---|---|
| A1 | `./scripts/rehearsal_up.sh`（或 `docker compose --env-file deploy/rehearsal/env.rehearsal -f docker-compose.prod.yml -f deploy/rehearsal/docker-compose.prod-rehearsal.yml --profile qlib --profile monitor up -d`） | 栈起、traefik `v3.7.15` | ✅ `qqlab-prod-rehearsal-traefik-1` Up（宿主 127.0.0.1 的 80/443/9711/8082）；qlibws 入口静态超时全 0 |
| A2 | `curl -s http://127.0.0.1:8082/api/overview` | 返回 JSON（dashboard API 活） | ✅ `routers 7 / services 7 / middlewares 6`，**errors=0 warnings=0**（docker provider 正常读 labels） |
| A3 | `curl -si 'http://127.0.0.1:9711/socket.io/?EIO=3&transport=polling' \| head -3` | `HTTP/1.1 200` + sid | ✅ 200，body `{"sid":…,"upgrades":[],"pingTimeout":60000,…}`（`EIO=4` 同 200；引擎代际实为 EIO3，握手穿透 qlibws 入口成功） |
| A4 | `docker cp scripts/qlib_connectivity_smoke.py <worker>:/tmp/ && docker exec <worker> python3 /tmp/qlib_connectivity_smoke.py` | L1/L2/L3 全 OK | ✅ exit=0：L1 握手 `ok=true detail=ws://qlib.rehearsal.test:9711`、L2 3875 标的、L3 `$close` 抽样（SH600000…）。**判据语义**：L2/L3 读**本地共享卷**（LocalProvider，非 server 路径），L1 才经 Traefik 到 server；传输为 EIO3 长轮询——server `upgrades:[]` 无 WS 升级、裸 `Upgrade` 400（直连同然，非 Traefik 问题） |
| A5 | `curl -sk --resolve api.rehearsal.test:443:127.0.0.1 https://api.rehearsal.test/api/v1/health/{live,ready}` | 200 全绿 | ✅ live `status=alive`；ready 200 且 `database/cache/queue/storage/auth` 全 true + `ready=true`（自签证书需 `-k`）；`APP_ENV=production` |
| A6 | **事件往返**：socketio `calendar_request → calendar_response`（经 worker 容器 `ws://qlib.rehearsal.test:9711` 别名→Traefik）+ worker 启动 `qlib_server_probe ok=true` + 真实回测 | `status=0` + probe ok + job succeeded | ✅ 往返 1.9s 返回 180 个交易日 `status=0`（server 日志七步链全证：Connection→Received→Publish task→DataProcessor→Publish message→Send response→Disconnect）；probe `ok=false×2 → ok=true`（traefik 网络别名修复后，日志 13:05:02）；回测 job `3f61d623` **succeeded/100**（3875 标的，progress 10→50→65→100） |

> **A6 判据定性（阶段 9）**：原判据「worker 日志出现 `calendar_response`」双层不可达成——
> ① `build_qlib_config` 不设 `*_provider`/`provider` 键（自 stage3 初版 `8bf5836` 即如此），全部走
> Local 默认（`remote=False`），数据经共享卷本地读取，**qlib-server 不在取数路径上**（证伪实验：
> flask_server 指向不可达 `192.0.2.1:1` 仍取到 instruments=3875 / feature rows=16231；回测窗口
> server 日志零连接）；② stock pyqlib 0.9.7 请求体为 pickle、server 为 `json.loads` →
> UnicodeDecodeError（实测）。R9 影响面随之收敛为：**探测告警（不退出）+ smoke L1**，任务执行
> 不受影响；`/ready` 检查项不含 qlib-server。数据路径与 ClientProvider 前提详见
> [`docs/stage1/06-qlib-integration.md`](../stage1/06-qlib-integration.md) §8.6。

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
