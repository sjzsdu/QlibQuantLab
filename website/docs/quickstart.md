---
title: 5 分钟跑起来
sidebar_label: 5 分钟跑起来
description: 用模式 A 自包含栈在本机启动 QlibQuantLab：前置检查、五步启动、成功判据与常见报错排查。
---

# 5 分钟跑起来

这一页只做一件事：在你的机器上把 QlibQuantLab 完整跑起来（模式 A 自包含栈），并确认你真的跑成功了。

## 前置条件

| 依赖 | 要求 | 自查命令 |
| --- | --- | --- |
| Docker | 20.10+ | `docker version` |
| Docker Compose | v2（`docker compose` 子命令，不是 `docker-compose`） | `docker compose version` |
| 磁盘 | ≥ 8 GB 可用（镜像 + 数据卷） | `df -h` |
| 端口 | 3000 / 8000 / 5433 / 16379 / 5672 / 15672 未被占用 | `lsof -i :3000 -i :8000` |

不需要在本机装 Python、Node 或 Qlib —— 全部在容器里。

## 五步启动

```bash
# 1. 取代码
git clone https://github.com/sjzsdu/QlibQuantLab.git
cd QlibQuantLab

# 2. 生成 .env（已存在则不会覆盖）
cp .env.example .env

# 3. 起栈：前端 / 后端 / worker / 迁移 / pg / redis / rabbitmq
docker compose up -d --build

# 4. 看状态：backend=healthy，migrate=exited (0)
docker compose ps

# 5. 就绪探针 + 打开登录页
curl -s localhost:8000/api/v1/health/ready
open http://localhost:3000/login
```

首次构建要拉基础镜像并编译，取决于网络通常 3–10 分钟。之后的启动是秒级。

## 怎么算跑成功了

三条都满足才算成功：

1. `docker compose ps` 里 **`migrate` 是 `exited (0)`** —— 它建了 17 张表并写入 `dev-org` / `dev-user` 种子数据；
2. `curl -s localhost:8000/api/v1/health/ready` 返回 `"status":"ready"`，且 `checks` 里 database / cache / queue / storage / auth 全部 `true`；
3. 打开 `http://localhost:3000/login` 能一键进入，落到工作台而不是白屏或 500。

登录后的界面就长这样（截图用演示数据拍摄）：

![登录后的工作台](/img/screens/home.webp)

## 认证：Mock 与四个 profile

阶段 1–6 用 `MockAuthProvider`，登录页可以一键切换角色。四个 profile 预置的角色是：

| profile | 会话角色 | 能做什么 |
| --- | --- | --- |
| `admin`（默认） | admin + researcher | 全部能力，含删除、发布、可见性切换、授权台账 |
| `researcher` | researcher | 研究写入：项目 / 数据 / 因子 / 训练 / 回测 |
| `viewer` | viewer | 只读 |
| `auditor` | auditor | 只读 + 审计查看与导出 |

也可以直接指定 profile 进入，便于脚本与联调：

```bash
open "http://localhost:8000/api/v1/auth/mock/enter?profile=viewer&redirect_to=/"
```

:::caution 不要把这个栈暴露到公网
Mock 认证意味着任何访客都能切到 `admin`。生产环境（`APP_ENV=production`）里 `AUTH_PROVIDER=mock` 会直接拒绝启动，这是刻意设计的。
:::

## 可选：接入 Qlib 数据链路

默认 `COMPUTE_BACKEND=stub`（合成数据，零外部依赖，够你走通界面与流程）。要跑真实数据与回测，再起 qlib 这一组：

```bash
make qlib-up        # qlib-server + rabbitmq-init（vhost 授权）+ 应用栈
make qlib-data      # 导入官方 zip（幂等；首次可用 QLIB_DATA_SYMBOLS=50 只导前 50 个标的）
make qlib-smoke     # L1 WS 握手 → L2 instruments → L3 features 三级连通
```

跑通之后就能提交数据集导入、因子计算与回测任务：

```bash
make dataset-import-smoke   # 入队数据导入任务
make backtest-smoke         # 入队最小回测（动量 topk）
docker compose logs -f worker
```

并发度 `QLIB_WORKER_CONCURRENCY=1` 是硬约束（qlib 是进程单例），所以任务会排队 —— 这是预期行为，不是卡住。

## 排错表

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `bind: address already in use` | 本机端口被占（常见 5432 / 6379 / 3000） | 改 `.env` 里的 `HOST_PORT_WEB` / `HOST_PORT_API` / `HOST_PORT_PG` / `HOST_PORT_REDIS`，再 `docker compose up -d` |
| `migrate` 是 `exited (1)` 或一直在跑 | 迁移脚本报错，通常是数据库没起来就抢跑 | `docker compose logs migrate`，修完 `docker compose up -d` |
| `backend` 一直 `unhealthy` | 某个依赖不可用 | `curl -s localhost:8000/api/v1/health/ready` 看哪个 `checks` 是 `false`，再 `docker compose logs backend` |
| 登录页报 429 | 登录限流默认 5 次/分钟（`RATE_LIMIT_LOGIN_PER_MIN`） | 等一分钟；本地反复联调可临时调大该值 |
| `qlib-server` 镜像拉不动 / 起不来（Apple Silicon） | 该镜像按 `linux/amd64` 构建 | 保持 `QLIB_SERVER_PLATFORM=linux/amd64`（走 Rosetta/QEMU），或跳过 qlib profile 只用 `stub` |
| 想从干净状态重来 | 数据卷里留着旧 schema | `docker compose down -v`（**会删掉数据卷**），再重新 `up -d --build` |
| 前端起来了但接口 500 | `CORS_ALLOW_ORIGINS` 与实际访问地址不一致 | 让 `.env` 里的 `CORS_ALLOW_ORIGINS` 与浏览器地址栏的 origin 完全一致 |

## 本机零依赖开发（不起 Docker）

只想改代码、不想等容器时，后端可以跑在 sqlite + 内存适配器上：

```bash
cd backend
cp .env.example .env          # DATABASE_BACKEND=sqlite、CACHE/MQ 走内存实现
uv sync --all-extras
uv run alembic upgrade head   # 建表 + dev-org/dev-user 种子
uv run uvicorn qqlab.main:app --reload
```

另开一个终端跑前端：

```bash
cd frontend
pnpm install && pnpm dev
```

## 下一步

- [核心概念](/docs/concepts) —— 先统一术语，后面的指南才看得懂；
- [项目指南](/docs/guides/projects) / [因子指南](/docs/guides/factors) / [回测指南](/docs/guides/backtests) —— 按模块上手；
- [部署（模式 A / B）](/docs/deployment) —— 上生产前必须看的环境变量清单。
