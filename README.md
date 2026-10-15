# QlibQuantLab

基于 [Qlib](https://github.com/china-ai-team/qlib) 的**开源多用户量化研究平台**：多组织数据与策略隔离、可插拔认证（Mock → Casdoor 只换环境变量）、训练与回测跑在独立 worker 容器里，Web 进程永不 `import qlib`。

> ⚠️ **免责声明**：本平台仅供研究、教学与技术验证使用，**不构成任何投资建议**。所有回测结果、指标与曲线均为历史数据的统计呈现，不代表未来收益；使用者的投资决策与由此产生的任何后果由使用者自行承担。详见 `GET /api/v1/legal/disclaimer` 与页面底部法务入口。

## 当前进度

| 阶段 | 内容 | 状态 |
|------|------|------|
| 1 | 架构设计（9 份文档） | ✅ 已确认 → `docs/stage1/` |
| 2 | 后端骨架 + Mock 认证 + 用户上下文 + 前端骨架 + 双套 Compose | ✅ 已交付，**141 个测试全绿**；`docker compose up` 待实机验收 → `docs/stage2/` |
| 3 | 打通 Qlib-Server + 最小回测 | ⏳ 待阶段 2 确认 |
| 4 | 项目 / 数据 / 因子 | — |
| 5 | 训练 → 回测 → 可视化 → 任务中心 | — |
| 6 | 审计 / 权限 / 合规 / e2e / README 定稿 | — |
| 7 | 接入 Casdoor + 生产部署文档 | — |

每阶段固定交付：**目标 → 文件树 → 代码 → 启动命令 → 测试方法 → 已知风险 → 验收清单**，你确认后才进入下一阶段。

## 快速开始

### 模式 A · 自包含（开发推荐）

前置：Docker + Compose v2。

```bash
cp .env.example .env
docker compose up -d --build     # 7 个服务：前端 / 后端 / worker / 迁移 / pg / redis / rabbitmq
docker compose ps                # backend=healthy，migrate=exited(0)
curl -s localhost:8000/api/v1/health/ready
open http://localhost:3000/login # Mock 一键进入
```

> - 对象存储默认 `STORAGE_BACKEND=local`（数据落 `objects_data` 卷）。MinIO 挂在 `--profile minio`：当前镜像源不可用，拿到可用源后按 `.env.example` 注释三步恢复。
> - Qlib 相关服务挂在 `--profile qlib`（阶段 3 交付后才启用）：`docker compose --profile qlib up -d`。
> - 宿主端口在 `.env` 里用 `HOST_PORT_*` 覆盖（默认 pg 5433 / redis 16379，避开本机常见占用）。

### 本机零依赖开发（不起 Docker）

```bash
cd backend && cp .env.example .env     # sqlite + memory 适配器
uv sync --all-extras
uv run alembic upgrade head            # 建 17 张表 + dev-org/dev-user 种子
uv run uvicorn qqlab.main:app --reload
# 另开终端
cd frontend && pnpm install && pnpm dev
```

### 模式 B · 复用已有基础设施（生产）

```bash
# 改 .env：APP_ENV=production、DATABASE_URL/CACHE_URL/MQ_URL/STORAGE_S3_* 指向外部实例、
#          APP_JWT_SECRET ≥32 随机值、SESSION_COOKIE_SECURE=true、CORS_ALLOW_ORIGINS 只留生产域名、
#          TRAEFIK_HOST_* 填真实域名、EXTERNAL_TRAEFIK_NETWORK 指向已有 Traefik 网络
docker compose -f docker-compose.prod.yml run --rm migrate
docker compose -f docker-compose.prod.yml up -d --build
```

模式 B **不启动任何基础设施服务**，业务容器挂在 `internal`（不出网）+ `traefik` 网络，暴露只经 compose 层的 Traefik labels —— **应用代码完全不感知反向代理**。

## 常用命令

```bash
make help          # 全部命令
make test          # 后端 ruff+pytest，前端 lint+typecheck+build
make dev           # 模式 A 一键启动（make dev-down 停止、make ps 状态、make dev-logs 日志）
make migrate       # 本机跑 alembic
make lint / format / smoke / clean
```

## 项目结构

```
QlibQuantLab/
├── backend/          FastAPI + SQLAlchemy 2.0(async) + Alembic + Pydantic v2（Python 3.12 / uv）
│   ├── src/qqlab/
│   │   ├── ports/        ★ 抽象接口：只依赖标准库
│   │   ├── adapters/     ★ 具体实现：SDK 只出现在这里（redis/aio_pika/boto3/…）
│   │   ├── container.py  ★ 唯一装配点（唯一 import adapters 的地方）
│   │   ├── api/ services/ repositories/ models/ core/ schemas/
│   │   └── worker/       独立任务进程（qlib 只允许在 worker/qlib_env.py）
│   ├── alembic/          0001：一次建全 17 张表 + 种子
│   └── tests/            architecture · unit · contract · api · integration（141 用例）
├── frontend/         Next.js 15 + TS + AntD 5 + TanStack Query（pnpm）
├── docs/stage1/      架构设计（9 份，阶段基准）
├── docs/stage2/      本阶段交付文档（目标/文件树/代码/启动/测试/风险/验收）
├── docker-compose.yml       模式 A · 自包含
├── docker-compose.prod.yml  模式 B · 复用外部依赖 + Traefik
├── .env.example · Makefile · scripts/
└── qlib-server/ · deploy/ · LICENSE   # 阶段 3 / 阶段 7 交付
```

## 架构速览

**Ports & Adapters**：业务代码只依赖 `qqlab.ports`（数据库 / 缓存 / 消息队列 / 对象存储 / 认证 / 审计 / 计算七个端口），`container.py` 是唯一把端口换成实现的地方。`tests/architecture/` 用 AST 扫描强制执行：

- 业务层出现 `redis` / `pika` / `aio_pika` / `boto3` / `socketio` / `qlib` / `casdoor` → 测试失败；
- 出现硬编码主机名或 IP、或在 `config.py` 之外读 `os.environ` → 测试失败；
- 15 张业务表必须有非空 `org_id` 且被索引覆盖。

**多租户**：`OrgScope` 只来自会话，`BaseRepo` 强制拼 `org_id` 过滤，跨组织读/改/删统一返回 404（不泄露存在性）。策略与项目默认 `private`，删除类操作必须 `?confirm=true`。

**认证**：阶段 1–6 用 `MockAuthProvider`（`/login` 一键进入，4 个 profile 可切角色）；会话是平台自己签发的 JWT cookie，IdP 令牌只在后端留存 —— 阶段 7 换 Casdoor 时**只改环境变量，前后端代码零改动**；生产环境若 `AUTH_PROVIDER=mock` 会拒绝启动。

**统一响应信封**：`{ code, message, data, request_id }`，`request_id` 同时出现在响应头 `X-Request-ID`、结构化日志与 `audit_logs`，可三方串联。非安全方法强制双提交 CSRF（`qqlab_csrf` cookie + `X-CSRF-Token` 头）。

**Qlib 边界**：`qlib` 是进程单例且依赖 Redis + RabbitMQ（Qlib-Server 硬依赖、Redis 无密码），因此 Web 进程只作为 **WebSocket 客户端**连 Qlib-Server，训练/回测在独立 `worker` 容器执行（`QLIB_WORKER_CONCURRENCY=1`）。

## 测试

```bash
cd backend && uv run pytest -q        # 141 passed，<3s，零外部依赖
uv run ruff check .                   # All checks passed
# 真实后端契约（可选，需本地服务；redis 端口按默认 HOST_PORT_REDIS=16379，用外部实例就改成实际值）
TEST_REDIS_URL=redis://localhost:16379/9 uv run pytest tests/contract -q
```

前端：`pnpm lint && pnpm typecheck && pnpm build`（阶段 6 引入 Playwright e2e）。

## 文档

- `docs/stage1/` — 架构、目录、数据模型、API 与认证、端口与适配器、Qlib 集成、部署、风险与路线图
- `docs/stage2/` — 本阶段：目标 / 文件树 / 代码 / 启动命令 / 测试方法 / 已知风险 / 验收清单
- 阶段 1 风险登记册与七阶段路线图见 `docs/stage1/08-risks-and-roadmap.md`

## License

MIT（阶段 7 前定稿，见 `docs/stage1/02-repo-structure.md`）。
