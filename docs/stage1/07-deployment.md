# 07 · 部署：两套 Compose、环境变量、Traefik 与 Casdoor 清单

> 本文件里的 compose 是**草稿**，阶段 2 才落盘到仓库根目录。所有地址一律来自 `.env`，文件内不出现硬编码主机名以外的敏感值；密码等仅在 `.env.example` 里以占位符出现。

## 1. `.env.example` 草稿

```bash
# ============================================================================
# QlibQuantLab 环境变量模板
# 用法：cp .env.example .env  然后按段落修改
# 规则：本文件只放占位符与开发默认值，真实密钥永不提交到仓库
# ============================================================================

# ----------------------------------------------------------------------------
# --- dev --- 本地开发默认值（docker-compose.yml 读取）
# ----------------------------------------------------------------------------
APP_ENV=development
LOG_LEVEL=INFO

# 数据库
DATABASE_BACKEND=postgres
POSTGRES_USER=qqlab
POSTGRES_PASSWORD=qqlab-dev-secret
POSTGRES_DB=qqlab
DATABASE_URL=postgresql+asyncpg://qqlab:qqlab-dev-secret@postgres:5432/qqlab
# alembic 用同一个 async URL（alembic/env.py 走 async engine），不再需要 DATABASE_URL_SYNC

# 缓存（应用）
# 注意：开发环境这台 Redis 不设密码 —— Qlib-Server 官方实现不支持 Redis 密码
# （qlib_server/utils.py: redis.StrictRedis(host, port, db) 无 password 参数），
# 共用实例时只能免密，靠 Docker 内网隔离；生产建议给应用与 Qlib-Server 各用一个实例。
CACHE_BACKEND=redis
CACHE_URL=redis://redis:6379/5

# 消息队列（应用）
MQ_BACKEND=rabbitmq
RABBITMQ_DEFAULT_USER=qqlab
RABBITMQ_DEFAULT_PASS=qqlab-dev-secret
MQ_URL=amqp://qqlab:qqlab-dev-secret@rabbitmq:5672/%2Fqqlab

# 对象存储
STORAGE_BACKEND=minio
STORAGE_S3_ENDPOINT=http://minio:9000
STORAGE_S3_BUCKET=qqlab
STORAGE_S3_ACCESS_KEY=qqlab
STORAGE_S3_SECRET_KEY=qqlab-dev-secret
STORAGE_S3_PATH_STYLE=true
STORAGE_LOCAL_ROOT=/data/objects
MINIO_ROOT_USER=qqlab
MINIO_ROOT_PASSWORD=qqlab-dev-secret

# 认证（开发用 Mock）
AUTH_PROVIDER=mock
APP_JWT_SECRET=dev-only-not-secret-change-me-0123456789abcdef
APP_JWT_TTL_SECONDS=28800
SESSION_COOKIE_NAME=qqlab_session
SESSION_COOKIE_SECURE=false
CORS_ALLOW_ORIGINS=http://localhost:3000
MOCK_USER_ID=dev-user
MOCK_ORG_ID=dev-org
MOCK_USER_ROLES=admin,researcher

# Qlib 计算
QLIB_SERVER_WS_URL=ws://qlib-server:9710
QLIB_DATA_ROOT=/qlib_data
QLIB_EXPERIMENT_ROOT=/experiments
QLIB_REGION=cn
QLIB_WORKER_CONCURRENCY=1
QLIB_INIT_TIMEOUT_SECONDS=60

# Qlib-Server 自身的硬依赖（Redis + RabbitMQ 必填，不可省略）
QLIB_SERVER_REDIS_HOST=redis
QLIB_SERVER_REDIS_PORT=6379
QLIB_SERVER_REDIS_DB=0
QLIB_SERVER_QUEUE_HOST=rabbitmq
QLIB_SERVER_QUEUE_PORT=5672
QLIB_SERVER_QUEUE_USER=qqlab
QLIB_SERVER_QUEUE_PASS=qqlab-dev-secret
QLIB_SERVER_TASK_QUEUE=task_queue
QLIB_SERVER_MESSAGE_QUEUE=message_queue

# 限流 / 审计
RATE_LIMIT_LOGIN_PER_MIN=5
RATE_LIMIT_WRITE_PER_MIN=120
RATE_LIMIT_READ_PER_MIN=600
AUDIT_RETENTION_DAYS=365

# ----------------------------------------------------------------------------
# --- prod --- 生产/模式 B 字段（docker-compose.prod.yml 读取；开发阶段留空）
# ----------------------------------------------------------------------------
# 反向代理（应用层不感知，仅 compose 使用）
TRAEFIK_HOST_WEB=
TRAEFIK_HOST_API=
TRAEFIK_HOST_QLIB=
TRAEFIK_CERT_RESOLVER=letsencrypt
EXTERNAL_TRAEFIK_NETWORK=traefik-net
EXTERNAL_FRONTEND_NETWORK=

# 生产安全（必改）
APP_JWT_SECRET=
SESSION_COOKIE_SECURE=true
CORS_ALLOW_ORIGINS=
TRUSTED_HOSTS=

# 复用外部基础设施（模式 B 只改这些）
DATABASE_URL=
CACHE_URL=
MQ_URL=
STORAGE_BACKEND=s3
STORAGE_S3_ENDPOINT=
STORAGE_S3_BUCKET=
STORAGE_S3_ACCESS_KEY=
STORAGE_S3_SECRET_KEY=
STORAGE_S3_PATH_STYLE=false

# Casdoor（阶段 7 —— 草案；实测定稿值见 docs/stage7/03 §5.1 与根 .env.example：
#   ORG_ID_CLAIM 定为 owner、新增 INTERNAL_URL（dev 双地址）与 ORG_MAP、ROLE_MAP 默认 {} 直通 fail-closed）
AUTH_PROVIDER=casdoor
CASDOOR_ISSUER=
CASDOOR_CLIENT_ID=
CASDOOR_CLIENT_SECRET=
CASDOOR_REDIRECT_URI=
CASDOOR_SCOPES=openid profile email
CASDOOR_ROLE_CLAIM=roles
CASDOOR_ORG_ID_CLAIM=x-org-id
CASDOOR_ROLE_MAP={"admin":"admin","researcher":"researcher"}

# Qlib-Server 指向外部 Redis / RabbitMQ（模式 B）
QLIB_SERVER_WS_URL=
QLIB_SERVER_REDIS_HOST=
QLIB_SERVER_QUEUE_HOST=
```

## 2. `docker-compose.yml` 草稿（模式 A · 自包含）

```yaml
# docker-compose.yml —— 模式 A：一键起全套依赖（不含 Casdoor）
name: qqlab

x-backend: &backend
  build:
    context: ./backend
    target: ${DOCKER_TARGET:-builder}
  env_file: [.env]
  networks: [qqlab]
  restart: unless-stopped

services:
  # ---------------------------------------------------------------- 前端
  frontend:
    build:
      context: ./frontend
      target: dev
    command: pnpm dev --hostname 0.0.0.0 --port 3000
    working_dir: /app
    volumes:
      - ./frontend:/app
      - frontend_node_modules:/app/node_modules
    ports: ["3000:3000"]
    environment:
      NEXT_PUBLIC_API_BASE: /api
      BACKEND_INTERNAL_URL: http://backend:8000
    depends_on:
      backend: {condition: service_healthy}
    networks: [qqlab]
    restart: unless-stopped

  # ---------------------------------------------------------------- 后端
  backend:
    <<: *backend
    command: uvicorn qqlab.main:app --host 0.0.0.0 --port 8000 --reload
    volumes:
      - ./backend:/app
      - backend_venv:/app/.venv
    ports: ["8000:8000"]
    environment:
      IS_WORKER: "false"
    depends_on:
      postgres: {condition: service_healthy}
      redis:    {condition: service_healthy}
      rabbitmq: {condition: service_healthy}
      migrate:  {condition: service_completed_successfully}
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/v1/health/live')"]
      interval: 10s
      timeout: 5s
      retries: 12

  # ---------------------------------------------------------------- 任务 worker（唯一 import qlib 的进程）
  worker:
    <<: *backend
    command: qqlab-worker
    environment:
      IS_WORKER: "true"
      QLIB_WORKER_CONCURRENCY: "1"
    volumes:
      - ./backend:/app
      - backend_venv:/app/.venv
      - qlib_data:/qlib_data
      - experiments:/experiments
    depends_on:
      postgres:    {condition: service_healthy}
      redis:       {condition: service_healthy}
      rabbitmq:    {condition: service_healthy}
      qlib-server: {condition: service_healthy}
      migrate:     {condition: service_completed_successfully}
    restart: unless-stopped

  # ---------------------------------------------------------------- 一次性迁移
  migrate:
    <<: *backend
    command: alembic upgrade head
    restart: "no"
    depends_on:
      postgres: {condition: service_healthy}

  # ---------------------------------------------------------------- Qlib 在线服务（硬依赖 Redis + RabbitMQ）
  qlib-server:
    build:
      context: ./qlib-server
    platform: ${QLIB_SERVER_PLATFORM:-linux/amd64}   # Apple Silicon 走 Rosetta；arm64 自建镜像时置空
    environment:
      QUEUE_HOST: ${QLIB_SERVER_QUEUE_HOST:-rabbitmq}
      QUEUE_USER: ${RABBITMQ_DEFAULT_USER}
      QUEUE_PASS: ${RABBITMQ_DEFAULT_PASS}
      REDIS_HOST: ${QLIB_SERVER_REDIS_HOST:-redis}
      REDIS_PORT: ${QLIB_SERVER_REDIS_PORT:-6379}
      REDIS_DB:   ${QLIB_SERVER_REDIS_DB:-0}
      MESSAGE_QUEUE: ${QLIB_SERVER_MESSAGE_QUEUE:-message_queue}
      TASK_QUEUE:     ${QLIB_SERVER_TASK_QUEUE:-task_queue}
      FLASK_SERVER_HOST: 0.0.0.0
      QLIB_DATA: /qlib_data/${MOCK_ORG_ID:-dev-org}
    volumes:
      - qlib_data:/qlib_data
    ports: ["9710:9710"]
    depends_on:
      rabbitmq: {condition: service_healthy}
      redis:    {condition: service_healthy}
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import socket;socket.create_connection(('127.0.0.1',9710),3)\""]
      interval: 15s
      timeout: 5s
      retries: 20
      start_period: 60s
    restart: unless-stopped

  # ---------------------------------------------------------------- 一次性数据导入（Yahoo → dump_bin）
  qlib-bootstrap:
    build: {context: ./qlib-server}
    profiles: ["bootstrap"]        # docker compose --profile bootstrap run --rm qlib-bootstrap
    command: ["/scripts/bootstrap_qlib_data.sh"]
    volumes:
      - qlib_data:/qlib_data
      - ./scripts:/scripts:ro
    restart: "no"

  # ---------------------------------------------------------------- 基础设施
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes: [pg_data:/var/lib/postgresql/data]
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 20
    restart: unless-stopped

  # 应用缓存 + Qlib-Server 硬依赖共用一个实例（分 db 隔离：应用 db5 / qlib-server db0）。
  # 刻意不设密码：Qlib-Server 官方实现不支持 Redis 密码（见 06 文档 §1 与风险 R11），
  # 靠 Docker 内网 + 仅回环暴露宿主端口保护。模式 B 建议两者分开实例。
  redis:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes"]
    volumes: [redis_data:/data]
    ports: ["127.0.0.1:6379:6379"]
    healthcheck:
      test: ["CMD-SHELL", "redis-cli ping | grep PONG"]
      interval: 5s
      timeout: 3s
      retries: 20
    restart: unless-stopped

  rabbitmq:
    image: rabbitmq:3.13-management-alpine
    environment:
      RABBITMQ_DEFAULT_USER: ${RABBITMQ_DEFAULT_USER}
      RABBITMQ_DEFAULT_PASS: ${RABBITMQ_DEFAULT_PASS}
    volumes: [rabbit_data:/var/lib/rabbitmq]
    ports: ["5672:5672", "15672:15672"]
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "-q", "ping"]
      interval: 10s
      timeout: 10s
      retries: 20
    restart: unless-stopped

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
    volumes: [minio_data:/data]
    ports: ["9000:9000", "9001:9001"]
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 10s
      timeout: 5s
      retries: 20
    restart: unless-stopped

  minio-init:
    image: minio/mc:latest
    depends_on: [minio]
    entrypoint: >
      /bin/sh -c "mc alias set local http://minio:9000 $${MINIO_ROOT_USER} $${MINIO_ROOT_PASSWORD} &&
                  mc mb -p local/$${STORAGE_S3_BUCKET} || true"
    restart: "no"

networks:
  qqlab: {driver: bridge}

volumes:
  pg_data:
  redis_data:
  rabbit_data:
  minio_data:
  qlib_data:
  experiments:
  backend_venv:
  frontend_node_modules:
```

**关键点说明**

1. `QLIB_SERVER_PLATFORM=linux/amd64`：Apple Silicon 默认走 Rosetta/QEMU（风险 R1）；arm64 自建镜像成功后置空即可。
2. `qlib_data` 命名卷同时挂给 `qlib-server` 与 `worker`，**替代官方方案里的 NFS**（见 [06](./06-qlib-integration.md) §3）。
3. 应用 Redis 用 db5（`CACHE_URL`），qlib-server 用 db0（`QLIB_SERVER_REDIS_DB`），共用实例不互相污染。**该实例必须免密**：Qlib-Server 官方 `get_redis_connection()` 只接受 host/port/db，不支持密码（风险 R11）。
4. 应用 RabbitMQ 用 vhost `/qqlab`（`MQ_URL`），qlib-server 用默认 `/`。
5. `migrate` 是一次性服务，`backend`/`worker` 用 `service_completed_successfully` 等它完成。
6. `qlib-bootstrap` 挂在 `bootstrap` profile，常规 `up` 不会触发。
7. **没有 Traefik、没有外部网络标签** —— 应用层完全不感知反向代理。

**启动与验证**

```bash
cp .env.example .env
docker compose up -d --build                 # 全部起来
docker compose ps                             # 全部 healthy/completed
docker compose --profile bootstrap run --rm qlib-bootstrap   # 一次性导数据（阶段 3）
curl -s localhost:8000/api/v1/health/ready | jq               # 应含 db/cache/mq 三项
curl -s localhost:3000/api/v1/me | jq                          # Mock 用户上下文
```

## 3. `docker-compose.prod.yml` 草稿（模式 B · 复用现有基础设施）

```yaml
# docker-compose.prod.yml —— 模式 B：只部署应用，基础设施与 Traefik/Casdoor 复用用户已有的
name: qqlab-prod

x-prod: &prod
  env_file: [.env]
  restart: always
  networks: [traefik, internal]
  deploy:
    replicas: 1

services:
  frontend:
    build: {context: ./frontend, target: prod}
    <<: *prod
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.qqlab-web.rule=Host(`${TRAEFIK_HOST_WEB}`)"
      - "traefik.http.routers.qqlab-web.entrypoints=websecure"
      - "traefik.http.routers.qqlab-web.tls.certresolver=${TRAEFIK_CERT_RESOLVER}"
      - "traefik.http.services.qqlab-web.loadbalancer.server.port=3000"

  backend:
    build: {context: ./backend, target: runtime}
    <<: *prod
    command: uvicorn qqlab.main:app --host 0.0.0.0 --port 8000 --workers ${BACKEND_WORKERS:-4}
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.qqlab-api.rule=Host(`${TRAEFIK_HOST_API}`)"
      - "traefik.http.routers.qqlab-api.entrypoints=websecure"
      - "traefik.http.routers.qqlab-api.tls.certresolver=${TRAEFIK_CERT_RESOLVER}"
      - "traefik.http.services.qqlab-api.loadbalancer.server.port=8000"
      - "traefik.http.routers.qqlab-api.middlewares=sec-headers"
      - "traefik.http.middlewares.sec-headers.headers.stsSeconds=31536000"
      - "traefik.http.middlewares.sec-headers.headers.contentTypeNosniff=true"
      - "traefik.http.middlewares.sec-headers.headers.frameDeny=true"
      - "traefik.http.middlewares.ratelimit.ratelimit.average=100"
      - "traefik.http.middlewares.ratelimit.ratelimit.burst=50"

  worker:
    build: {context: ./backend, target: runtime}
    <<: *prod
    command: qqlab-worker
    environment: {IS_WORKER: "true"}
    deploy: {replicas: ${WORKER_REPLICAS:-2}}

  qlib-server:
    build: {context: ./qlib-server}
    <<: *prod
    # WebSocket 需要长连接：升级头 + passHostHeader + 无响应超时 + sticky（socket.io 轮询回退）
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.qqlib.rule=Host(`${TRAEFIK_HOST_QLIB}`)"
      - "traefik.http.routers.qqlib.entrypoints=websecure"
      - "traefik.http.routers.qqlib.tls.certresolver=${TRAEFIK_CERT_RESOLVER}"
      - "traefik.http.services.qqlib.loadbalancer.server.port=9710"
      - "traefik.http.services.qqlib.loadbalancer.passHostHeader=true"
      - "traefik.http.services.qqlib.loadbalancer.responseForwarding.flushInterval=1ms"
      - "traefik.http.services.qqlib.loadbalancer.sticky.cookie=true"
      - "traefik.http.middlewares.qqlib-ws.headers.customRequestHeaders.Connection=upgrade"
      - "traefik.http.middlewares.qqlib-ws.headers.customRequestHeaders.Upgrade=websocket"
      - "traefik.http.routers.qqlib.middlewares=qqlib-ws"

networks:
  traefik:
    external: true
    name: ${EXTERNAL_TRAEFIK_NETWORK}
  internal:
    internal: true      # 业务容器不出网，只经 Traefik 暴露
```

### 3.1 Traefik 侧必须额外配置的**静态**项（不在 compose 里）

```yaml
# traefik.yml（用户已有实例的参考配置）
entryPoints:
  websecure:
    address: ":443"
    transport:
      respondingTimeouts:
        readTimeout: 0        # WebSocket 长连接不能被读超时掐断
        writeTimeout: 0
      transportingTimeouts:   # Traefik v3
        responseHeaderTimeout: 0
        idleTimeout: 0
serversTransport:
  insecureSkipVerify: true    # 后端为 http 时
```
> Traefik v2 用 `entryPoints.*.transport.respondingTimeouts`，`transportingTimeouts` 为 v3 字段，按版本取用。**长连接超时是 Qlib WebSocket 在生产上最常见的故障点**，必须显式关闭。

### 3.2 两种模式差异对照

| 项 | 模式 A（dev） | 模式 B（prod） |
|----|---------------|----------------|
| 依赖服务 | compose 内起 pg/redis/rabbit/minio | `external` 网络 + 环境变量指向已有实例 |
| Casdoor | 不部署，`AUTH_PROVIDER=mock` | `AUTH_PROVIDER=casdoor` 指向已有实例 |
| 反向代理 | 无 | Traefik labels + 静态配置 |
| 密钥 | 开发占位符 | 全部注入，`.env` 不入库 |
| HTTPS | HTTP（localhost） | 必须 HTTPS |
| 前端 | dev server + 热更新 | `next build` + standalone |

## 4. 生产环境切换清单（阶段 7 交付，先列在此）

> ✅ **阶段 7 已定稿**（实测校准版：labels 已进 `docker-compose.prod.yml`、ORG_ID_CLAIM 定为 `owner`、补
> `WORKER_STALE_JOB_MINUTES` 与 Redis 拆分方案）：[`docs/stage7/03-production-deployment.md`](../stage7/03-production-deployment.md) §5。

### 4.1 必改环境变量

| 变量 | 改成 | 校验方式 |
|------|------|----------|
| `APP_ENV` | `production` | `/api/v1/system/info` 返回 env=production |
| `APP_JWT_SECRET` | ≥32 字节随机值 | 登录后 8h 内不失效；换值立即全体登出 |
| `SESSION_COOKIE_SECURE` | `true` | 浏览器 Cookie 带 `Secure` |
| `CORS_ALLOW_ORIGINS` | 仅生产域名 | 非白名单 Origin 被拒 |
| `DATABASE_URL` / `CACHE_URL` / `MQ_URL` | 外部实例 | `/ready` 三绿 |
| `STORAGE_BACKEND`/`STORAGE_S3_*` | 外部 S3 | `PUT`+`GET` 往返一致 |
| `AUTH_PROVIDER` | `casdoor` | `/api/v1/auth/login` 返回 Casdoor authorize URL |
| `CASDOOR_ISSUER/CLIENT_ID/CLIENT_SECRET/REDIRECT_URI` | 真实值 | OIDC 登录成功 |
| `QLIB_SERVER_WS_URL` | Traefik 暴露的 wss 地址 | worker 启动探测通过 |
| `QLIB_SERVER_REDIS_*` / `QLIB_SERVER_QUEUE_*` | 外部 Redis/RabbitMQ（**Redis 必须免密**，见风险 R11；RabbitMQ 要给 qlib-server 建独立账号） | qlib-server healthcheck 通过 |
| `TRAEFIK_HOST_*` | 真实域名 | `curl -I https://…` 200 |

### 4.2 必加的 Traefik labels
见 §3 草稿：`websecure` entrypoint、`certresolver`、`passHostHeader=true`、`Connection/Upgrade` 升级头、`sticky.cookie`（socket.io 轮询回退需要）、sec-headers 中间件、速率限制中间件。

### 4.3 切换后的验证清单
1. `curl https://api.…/api/v1/health/ready` → `db/cache/mq/storage/auth` 全绿。
2. 浏览器访问 `https://app.…` → 跳转 Casdoor → 回跳成功 → 顶栏显示真实用户名/组织。
3. 提交一个回测任务 → 任务成功 → 曲线可看。
4. WebSocket：worker 日志出现 `calendar_response`（证明 wss 穿透 Traefik 成功）。
5. 审计：`GET /api/v1/audit-logs?action=auth.login` 能查到本次登录。
6. 负向：直接用 Bearer 访问受保护接口 → 401；跨 org id 访问 → 404。
7. 断网演练：停掉外部 Redis → `/ready` 变红并给出「Qlib-Server 依赖 Redis」的明确提示。

## 5. Casdoor 侧配置说明（阶段 7 落 `deploy/casdoor/README.md`）

> ✅ **已落**：[`deploy/casdoor/README.md`](../../deploy/casdoor/README.md)（dev 种子语义 / 镜像 digest / manifest 探测）
> 与 [`docs/stage7/05-casdoor-deployment.md`](../stage7/05-casdoor-deployment.md)（生产指南 / R7-2 实测回写）。
> 实测修正：登出落点须注册进应用 RedirectUrls（`/login` 落地）；组织 claim 用 `owner` 即可，无需 Casdoor 侧额外字段。

1. **Organization**：建组织 `qqlab`；把研究用户加入该组织。
2. **Application**：
   - `Name = qqlab`
   - `Redirect URLs = https://app.example.com/api/v1/auth/callback`（**必须完全一致**，含协议与路径）
   - `Sign method = RSA256`，记下 `Client ID` / `Client Secret`
   - 允许的 scope：`openid profile email`
3. **角色映射**：
   - 在 Casdoor 用户上设 `roles = ["admin"|"researcher"|"viewer"|"auditor"]`（可用 Casdoor 的 Role 功能同步到 claim）
   - 应用侧 `CASDOOR_ROLE_CLAIM=roles`，`CASDOOR_ROLE_MAP` 做别名映射
   - 组织 claim：`CASDOOR_ORG_ID_CLAIM` 指向 Casdoor 的 org 字段；**若 Casdoor 侧 org slug 与我们的 `org_id` 不一致，用 `CASDOOR_ORG_MAP` 做映射**
4. **登出**：配置 `post_logout_redirect_uri = https://app.example.com/`，`get_logout_url` 才能正确跳回。
5. **回退**：保留 `AUTH_PROVIDER=mock` 的能力（仅限 `APP_ENV!=production`，生产环境启动时若 `AUTH_PROVIDER=mock` 则**拒绝启动**并报错）。
