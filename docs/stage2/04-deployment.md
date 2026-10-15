# 04 · 启动命令与部署（阶段 2 落盘的两套 Compose）

## 0. 前置要求

| 工具 | 版本 | 用途 |
|------|------|------|
| Docker + Compose | v2.20+（本机为 v2.40） | 模式 A / 模式 B |
| uv | 0.12.5（镜像内固定） | 后端依赖与命令 |
| Node + pnpm | Node 18+ / pnpm 12.9.1 | 前端（本机开发与测试） |
| make | 任意 | 命令入口（可选） |

> ⚠️ **实跑状态**：首次 `docker compose up -d --build` 暴露了两个环境问题并已修复 ——
> ① 宿主 5432 / 6379 被本机已有服务占用 → 所有宿主端口参数化为 `HOST_PORT_*`（默认 pg **5433**、redis **16379**，只绑回环）；
> ② `minio/minio` 镜像在当前环境拉不到 → 隔离到 `--profile minio`，默认 `STORAGE_BACKEND=local`（见 [06-risks §4](./06-risks.md) 恢复步骤）。
> 是否全绿仍以你复跑一次为准（验收项 A1）。

## 1. 模式 A · 一键起全套依赖（推荐开发用）

```bash
cp .env.example .env          # 只放开发默认值，真实密钥永不入库
docker compose up -d --build  # 7 个服务：frontend backend worker migrate postgres redis rabbitmq
docker compose ps             # 期望：backend=healthy, migrate=exited(0), 其余 healthy
docker compose logs -f backend
```

验证：

```bash
curl -s localhost:8000/api/v1/health/ready | jq     # db / cache / queue / storage / auth 全 true
curl -s localhost:3000/api/v1/health/live  | jq     # 经 Next rewrite 转发到后端
curl -si localhost:3000/api/v1/me | head -5         # 未登录 401 + Set-Cookie: qqlab_csrf=...
open http://localhost:3000/login                    # 一键进入 → 顶栏 dev-user @ dev-org
```

停止 / 清理 / 可选 profile：

```bash
docker compose down                 # 停（保留数据卷）
docker compose down -v              # 连数据卷一起清（重跑迁移）
docker compose --profile minio up -d minio   # 对象存储（需可用镜像源，见 06 §4）
docker compose --profile qlib up    # 阶段 3 起才会带 qlib-server / qlib-bootstrap
```

## 2. 本机零依赖开发（不走 Docker）

```bash
cd backend
cp .env.example .env        # sqlite + memory 适配器：起库、起队列、起缓存都不用装
uv sync --all-extras        # 安装依赖（含测试 extra）
uv run alembic upgrade head # 建 17 张表 + dev-org/dev-user 种子（生成 ./dev.db）
uv run uvicorn qqlab.main:app --reload --port 8000
# 另开终端
cd frontend && pnpm install && pnpm dev      # http://localhost:3000
```

> `Settings` 读取**当前工作目录**下的 `.env`（`env_file=".env"`），所以后端的 `.env` 放 `backend/`、compose 的 `.env` 放仓库根目录，互不干扰（根 `.env` 同时被两套 compose 读取）。

## 3. 模式 B · 复用已有基础设施（生产）

```bash
# 1) 改 .env：DATABASE_URL / CACHE_URL / MQ_URL / STORAGE_S3_* 指向外部实例
#    APP_ENV=production、SESSION_COOKIE_SECURE=true、APP_JWT_SECRET 换 32+ 随机值
#    CORS_ALLOW_ORIGINS 只留生产域名、TRAEFIK_HOST_* 填真实域名
# 2) 确认外部网络存在：docker network create traefik-net   （EXTERNAL_TRAEFIK_NETWORK）
# 3) 部署
docker compose -f docker-compose.prod.yml run --rm migrate   # 先跑迁移（一次性）
docker compose -f docker-compose.prod.yml up -d --build
```

模式 B 的 compose **不起任何基础设施服务**，只起 `frontend / backend / worker / migrate`，全部挂 `internal`（不出网）+ `traefik` 两个网络，暴露只经 Traefik labels（`Host()` + TLS + sec-headers + 限流）。Traefik 的**静态**配置（entrypoint 超时必须关掉才能过 WebSocket）见 `docs/stage1/07-deployment.md` §3.1，阶段 7 落 `deploy/traefik/traefik.yml`。

**生产启动校验**：`APP_ENV=production` 下若 `AUTH_PROVIDER=mock`、cookie 非 Secure、JWT 密钥过弱、缺 `QLIB_SERVER_REDIS_HOST`/`QLIB_SERVER_QUEUE_HOST`，进程启动直接抛错退出 —— 不合规就起不来，而不是带病运行。

## 4. Makefile

| 命令 | 作用 |
|------|------|
| `make help` | 列出全部命令（默认目标） |
| `make env` | `.env` 不存在则从模板生成 |
| `make install` | `uv sync --all-extras` + `pnpm install` |
| `make dev` | `env` + `docker compose up -d --build` |
| `make migrate` | 本机跑 `alembic upgrade head` |
| `make test` | `test-backend` + `test-frontend` |
| `make test-backend` | `ruff check` + `pytest -q` |
| `make test-frontend` | `pnpm lint` + `typecheck` + `build` |
| `make lint` / `make format` | 静态检查 / 自动格式化+修复 |
| `make smoke` | 打 `/health/ready`、`/health/live`、`/me` |
| `make dev-logs` / `make dev-down` / `make ps` / `make build` | 日志 / 停止 / 状态 / 只构建 |
| `make clean` | 清 `__pycache__`、`.pytest_cache`、`.next` |

## 5. compose 关键设计点（对照阶段 1 的 07 文档）

| # | 设计点 | 说明 |
|---|--------|------|
| 1 | **一个镜像两个进程** | `backend`/`worker`/`migrate` 共用 `target: dev`（开发，bind mount）或 `target: runtime`（生产），只有 `command` 不同：`uvicorn` / `qqlab-worker` / `alembic upgrade head` |
| 2 | **`migrate` 是一次性服务** | `backend`/`worker` 用 `depends_on: service_completed_successfully` 等它跑完再起，避免启动竞态 |
| 3 | **bind mount + venv 命名卷** | `./backend:/app` 覆盖源码后会盖掉镜像里的 `.venv`，所以再挂 `backend_venv:/app/.venv` 把依赖找回来（`frontend` 同理挂 `frontend_node_modules`） |
| 4 | **开发用 `target: dev`** | 生产才用 `runtime`（非 root uid 10001）；前端生产构建必须传 `build.args.BACKEND_INTERNAL_URL` |
| 5 | **Redis 免密** | Qlib-Server 官方实现不支持 Redis 密码（`redis.StrictRedis(host, port, db)` 无 password 参数），共用实例只能免密 + Docker 内网 + 宿主端口只绑 `127.0.0.1`；应用用 db5、Qlib-Server 用 db0 |
| 6 | **两套 vhost** | 应用 MQ 用 `/qqlab`（`MQ_URL`），Qlib-Server 用默认 `/`，队列不互串 |
| 7 | **`qlib` profile** | `qlib-server` / `qlib-bootstrap` 默认不启动（阶段 3 才有构建上下文与脚本）；`worker` 对 `qlib-server` 的 `depends_on` 也在阶段 3 补回 |
| 8 | **应用层零感知代理** | 两套 compose 里没有任何 `qqlab` 服务引用 Traefik 网络或标签（模式 B 的标签只写在 compose 层，应用代码不读） |
| 9 | **Apple Silicon** | `QLIB_SERVER_PLATFORM=linux/amd64`（阶段 3 的 Qlib-Server 镜像只有 amd64）；arm64 自建后置空 |
| 10 | **对象存储可插拔** | 默认 `STORAGE_BACKEND=local`（落 `objects_data` 命名卷）；MinIO 挂 `minio` profile（当前拉不到镜像），bucket 由 `S3StorageProvider.ping()` 惰性创建，**没有 `minio-init` 容器**（`minio/mc` 也已从 Docker Hub 移除） |
| 11 | **宿主端口全参数化** | 所有 published 端口写成 `${HOST_PORT_*:-默认}`（默认 pg **5433**、redis **16379**，只绑 `127.0.0.1`，避开本机常见占用）；容器内恒走服务名 + 内部端口，改这些变量不影响代码连接串 |

## 6. 端口占用

| 端口（变量） | 服务 | 模式 A | 模式 B |
|------|------|--------|--------|
| 3000（`HOST_PORT_WEB`） | 前端 | ✅ | 经 Traefik（`TRAEFIK_HOST_WEB`） |
| 8000（`HOST_PORT_API`） | 后端 API | ✅ | 经 Traefik（`TRAEFIK_HOST_API`） |
| 5433（`HOST_PORT_PG`）/ 16379（`HOST_PORT_REDIS`） | postgres / redis | ✅（均只绑 `127.0.0.1`） | 用外部实例 |
| 5672 / 15672（`HOST_PORT_AMQP[_MGMT]`） | rabbitmq / 管理台 | ✅ | 用外部实例 |
| 9000 / 9001（`HOST_PORT_S3[_CONSOLE]`） | minio / 控制台 | `--profile minio` | 用外部实例 |
| 9710（`HOST_PORT_QLIB`） | Qlib-Server | `--profile qlib` | 经 Traefik（`TRAEFIK_HOST_QLIB`） |

## 7. 常见问题

| 现象 | 处理 |
|------|------|
| `docker compose up` 时报某端口被占用 | 根 `.env` 里覆盖对应 `HOST_PORT_*`（如 `HOST_PORT_PG=15432`），或停掉冲突服务 |
| `health/ready` 里 `storage: false` | 当前 `STORAGE_BACKEND=minio` 但 MinIO 没起或端点不通（就绪检查把连接异常当红灯，不会 500）→ 确认 minio 服务已 `--profile minio` 起来，或改回 `STORAGE_BACKEND=local` |
| MinIO 镜像拉取失败 | 预期内：minio 在 `--profile minio` 且默认不启用，恢复步骤见 [06-risks §4](./06-risks.md) |
| `uvicorn --reload` 在 macOS + bind mount 下改文件不热重载 | 加 `WATCHFILES_FORCE_POLLING=true` 到 `backend.environment` |
| 后端启动 `pydantic ValidationError: DATABASE_URL Field required` | 没有 `.env`：`cp .env.example .env`；本机开发请用 `backend/.env.example` |
| 启动报 `AUTH_PROVIDER=casdoor 但尚未实现` | 阶段 1–6 请用 `AUTH_PROVIDER=mock`；这是**故意的快速失败**，不会降级 |
| `alembic` 报连接失败 | 模式 A 先 `docker compose up -d postgres` 等 healthy；本机开发先 `cd backend && cp .env.example .env` |
