---
title: 部署（模式 A / B）
sidebar_label: 部署（模式 A / B）
description: 两种部署形态的差异、模式 B 的必填环境变量、生产环境的启动校验、Traefik 暴露方式、迁移与备份。
---

# 部署

平台有两种部署形态，差别不在代码，而在「谁提供基础设施」。

| 维度 | 模式 A · 自包含 | 模式 B · 复用基础设施 |
| --- | --- | --- |
| 适用场景 | 本机开发、评估、单机演示 | 已有 PG / Redis / MQ / 对象存储的机房 |
| Compose 文件 | `docker-compose.yml` | `docker-compose.prod.yml` |
| 启动的基础设施 | pg / redis / rabbitmq /（可选 minio） | **一个都不起** |
| 暴露方式 | 宿主端口 `HOST_PORT_*` | 容器挂 Traefik 网络，由 Traefik labels 暴露 |
| 出网 | 默认可用 | 业务容器在 `internal` 网络（不出网） |
| 认证 | Mock（4 profile） | 必须 Casdoor（`AUTH_PROVIDER=casdoor`） |

## 模式 A（已在「5 分钟跑起来」详述）

```bash
cp .env.example .env
docker compose up -d --build
```

端口全部由 `.env` 的 `HOST_PORT_*` 控制：

| 变量 | 默认 | 服务 |
| --- | --- | --- |
| `HOST_PORT_WEB` | 3000 | 前端 |
| `HOST_PORT_API` | 8000 | 后端 API |
| `HOST_PORT_PG` | 5433 | Postgres（127.0.0.1 回环） |
| `HOST_PORT_REDIS` | 16379 | Redis（127.0.0.1 回环） |
| `HOST_PORT_AMQP` | 5672 | RabbitMQ |
| `HOST_PORT_AMQP_MGMT` | 15672 | RabbitMQ 管理台 |
| `HOST_PORT_QLIB` | 9710 | Qlib-Server（`--profile qlib`） |

## 模式 B（生产）

```bash
# 1. 改 .env（见下面的必填清单）
# 2. 先跑迁移，确认 exited(0)
docker compose -f docker-compose.prod.yml run --rm migrate
# 3. 起业务容器
docker compose -f docker-compose.prod.yml up -d --build
```

模式 B **不启动任何基础设施**：`DATABASE_URL` / `CACHE_URL` / `MQ_URL` / `STORAGE_S3_*` 全部指向你已有的实例。业务容器挂在两个网络：

- `internal` —— 与外部实例通信，不出网；
- `traefik`（`EXTERNAL_TRAEFIK_NETWORK` 指向你已有的 Traefik 网络）—— 只用于被暴露。

:::note 应用不感知反向代理
暴露完全由 compose 层的 Traefik labels 决定，应用代码里没有任何关于 Traefik、域名或路径的假设。换个入口（Nginx / ALB）只需要改 labels。
:::

### 必填 / 必改环境变量

| 变量 | 要求 | 不满足会怎样 |
| --- | --- | --- |
| `APP_ENV` | `production` | 保持 `development` 就还是开发模式行为 |
| `APP_JWT_SECRET` | ≥ 32 字节随机值，且不能是 `.env.example` 里的开发占位 | **拒绝启动** |
| `SESSION_COOKIE_SECURE` | `true`（HTTPS） | **拒绝启动** |
| `AUTH_PROVIDER` | `casdoor`（配 `CASDOOR_*`） | **拒绝启动**（生产禁止 mock） |
| `CORS_ALLOW_ORIGINS` | 逗号分隔，只留生产域名 | 前端跨域被拦 |
| `TRAEFIK_HOST_WEB` / `TRAEFIK_HOST_API` | 真实域名 | 路由不生效 |
| `TRAEFIK_CERT_RESOLVER` | 与你的 Traefik 证书解析器同名 | TLS 不签发 |

生产环境的三条启动校验是刻意的：

```text
APP_ENV=production 且 AUTH_PROVIDER=mock            → ValueError: 生产环境禁止使用 AUTH_PROVIDER=mock
APP_ENV=production 且 SESSION_COOKIE_SECURE=false   → ValueError: 生产环境必须设置 SESSION_COOKIE_SECURE=true
APP_ENV=production 且 APP_JWT_SECRET 为占位/短于 32 → ValueError: 生产环境 APP_JWT_SECRET 必须是 >=32 字节的随机值
```

也就是说：把开发 `.env` 直接拿去上生产，容器**起不来**，而不是悄悄以不安全配置跑起来。

## 数据库迁移

```bash
# 模式 A
docker compose run --rm migrate

# 模式 B
docker compose -f docker-compose.prod.yml run --rm migrate

# 本机（不走容器）
cd backend && uv run alembic upgrade head
```

迁移是幂等的，可以重复执行。升级前先备份数据库 —— 迁移只向前，没有自动回滚。

## 对象存储

默认 `STORAGE_BACKEND=local`（数据落 `objects_data` 卷），适合单机与评估。要多副本或对象存储托管时切 S3：

```bash
STORAGE_BACKEND=s3
STORAGE_S3_ENDPOINT=http://your-s3:9000
STORAGE_S3_BUCKET=qqlab
STORAGE_S3_ACCESS_KEY=...
STORAGE_S3_SECRET_KEY=...
STORAGE_S3_PATH_STYLE=true
```

模式 A 里的 MinIO 挂在 `--profile minio`，需要时显式起。

## 计算链路（qlib）的资源约束

| 变量 | 含义 | 注意 |
| --- | --- | --- |
| `COMPUTE_BACKEND` | `stub` / `qlib` | 生产要真实数据就设 `qlib` |
| `QLIB_WORKER_CONCURRENCY` | worker 并发 | **必须为 1**：qlib 是进程单例且硬依赖 Redis + RabbitMQ |
| `QLIB_SERVER_PLATFORM` | qlib-server 镜像平台 | Apple Silicon 保持 `linux/amd64`（Rosetta/QEMU） |
| `QLIB_INIT_TIMEOUT_SECONDS` | 初始化超时 | 数据量大时应调大 |

并发为 1 意味着任务会排队：给 worker 足够的 CPU 与内存，而不是加副本。

## 上线前清单

- [ ] `APP_ENV=production`，且三条启动校验都通过（能起来说明过了）
- [ ] `APP_JWT_SECRET` 是 ≥32 字节随机值，且**不与其他环境复用**
- [ ] `SESSION_COOKIE_SECURE=true`，站点走 HTTPS
- [ ] `CORS_ALLOW_ORIGINS` 只包含生产域名
- [ ] 数据库已备份，`migrate` 以 `exited(0)` 结束
- [ ] `/api/v1/health/ready` 返回 `ready`（生产环境建议由外部监控探活）
- [ ] 已评估是否要暴露 OpenAPI（`/api/docs`、`/api/openapi.json` 仅非生产环境暴露）
- [ ] 法务页面可访问，且文案与后端 `/api/v1/legal/*` 一致

## 相关

- [5 分钟跑起来](/docs/quickstart)
- [架构与边界](/architecture)
- [回测](/docs/guides/backtests)
