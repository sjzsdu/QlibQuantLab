# QlibQuantLab

基于 [Qlib](https://github.com/microsoft/qlib) 的**开源多用户量化研究平台**：多组织数据与策略隔离、可插拔认证（Mock → Casdoor 只换环境变量）、训练与回测跑在独立 worker 容器里，Web 进程永不 `import qlib`。

> ⚠️ **免责声明**：本平台仅供研究、教学与技术验证使用，**不构成任何投资建议**。所有回测结果、指标与曲线均为历史数据的统计呈现，不代表未来收益；使用者的投资决策与由此产生的任何后果由使用者自行承担。详见 `GET /api/v1/legal/disclaimer` 与页面底部法务入口。

## 当前进度

| 阶段 | 内容 | 状态 |
|------|------|------|
| 1 | 架构设计（9 份文档） | ✅ 已确认 → `docs/stage1/` |
| 2 | 后端骨架 + Mock 认证 + 用户上下文 + 前端骨架 + 双套 Compose | ✅ 已确认 → `docs/stage2/` |
| 3 | 打通 Qlib-Server + 最小回测 | ✅ 已交付并实机验收（2026-10-15，A3-1…A3-10 全过）→ `docs/stage3/` |
| 4 | 项目 / 数据 / 因子 | ✅ 已交付，**247 个测试全绿** + live smoke 29/29 → `docs/stage4/` |
| 5 | 训练 → 回测 → 可视化 → 任务中心 | ✅ 已交付，**304 个测试全绿** + live smoke 43/43 + 浏览器冒烟 7 页 → `docs/stage5/` |
| 6 | 审计 / 权限 / 合规 / e2e / README 定稿 | ✅ 已交付，**401 个测试全绿** + live smoke 34/34 + Playwright e2e 11/11 → `docs/stage6/` |
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
> - Qlib 链路挂在 `--profile qlib`（阶段 3 起可用，默认不启动）：`docker compose --profile qlib up -d`。
> - 宿主端口在 `.env` 里用 `HOST_PORT_*` 覆盖（默认 pg 5433 / redis 16379，避开本机常见占用）。

### Qlib 链路（阶段 3，opt-in）

```bash
# .env：COMPUTE_BACKEND=qlib（默认 stub；首次 smoke 可设 QLIB_DATA_SYMBOLS=50 只取前 50 个标的）
make qlib-up              # Qlib-Server + rabbitmq-init（vhost 授权）+ 应用栈
make qlib-data            # 官方 zip 两段式导入（幂等；失败给连通性结论，不换源）
make qlib-smoke           # L1 WS 握手 → L2 instruments → L3 features 三级连通
make dataset-import-smoke # 入队数据导入（校验目录 + 登记 data_sources/data_licenses/datasets 台账）
make backtest-smoke       # 入队最小回测（动量 topk 纯规则；费用三件套 100% 透传）
docker compose logs -f worker
```

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
│   │   │   └── compute/  计算适配器（worker 专用；stub 合成 / qlib 取数 + 自研模拟器）
│   │   ├── container.py  ★ 唯一装配点（唯一 import adapters 的地方）
│   │   ├── api/ services/ repositories/ models/ core/ schemas/
│   │   └── worker/       独立任务进程（qlib 只允许在 worker/qlib_env.py + adapters/compute/qlib_compute.py）
│   ├── alembic/          0001：一次建全 17 张表 + 种子；0004：factor_compute_runs（阶段 6）
│   └── tests/            architecture · unit · contract · api · integration（401 用例 + 1 skip）
├── frontend/         Next.js 15 + TS + AntD 5 + TanStack Query（pnpm）+ Playwright e2e
├── docs/stage1/      架构设计（9 份，阶段基准）
├── docs/stage2/      阶段 2 交付文档
├── docs/stage3/      阶段 3 交付文档（Qlib-Server + 最小回测）
├── docs/stage4/      阶段 4 交付文档（项目 / 数据 / 因子）
├── docs/stage5/      阶段 5 交付文档（训练 / 回测 / 可视化 / 任务中心）
├── docs/stage6/      阶段 6 交付文档（合规与可验证性补齐）
├── docker-compose.yml       模式 A · 自包含（qlib 链路挂 --profile qlib）
├── docker-compose.prod.yml  模式 B · 复用外部依赖 + Traefik
├── .env.example · Makefile · scripts/
└── qlib-server/      Qlib-Server 自建镜像（vendored 源码 + 依赖锁定 + 启动时配置渲染）
```

## 架构速览

**Ports & Adapters**：业务代码只依赖 `qqlab.ports`（数据库 / 缓存 / 消息队列 / 对象存储 / 认证 / 审计 / 计算七个端口），`container.py` 是唯一把端口换成实现的地方。`tests/architecture/` 用 AST 扫描强制执行：

- 业务层出现 `redis` / `pika` / `aio_pika` / `boto3` / `socketio` / `qlib` / `casdoor` → 测试失败；
- 出现硬编码主机名或 IP、或在 `config.py` 之外读 `os.environ` → 测试失败；
- 15 张业务表必须有非空 `org_id` 且被索引覆盖。

**多租户**：`OrgScope` 只来自会话，`BaseRepo` 强制拼 `org_id` 过滤，跨组织读/改/删统一返回 404（不泄露存在性）。策略与项目默认 `private`，删除类操作必须 `?confirm=true`。

**认证**：阶段 1–6 用 `MockAuthProvider`（`/login` 一键进入，4 个 profile 可切角色）；会话是平台自己签发的 JWT cookie，IdP 令牌只在后端留存 —— 阶段 7 换 Casdoor 时**只改环境变量，前后端代码零改动**；生产环境若 `AUTH_PROVIDER=mock` 会拒绝启动。

**统一响应信封**：`{ code, message, data, request_id }`，`request_id` 同时出现在响应头 `X-Request-ID`、结构化日志与 `audit_logs`，可三方串联。非安全方法强制双提交 CSRF（`qqlab_csrf` cookie + `X-CSRF-Token` 头）。

**Qlib 边界**：`qlib` 是进程单例且依赖 Redis + RabbitMQ（Qlib-Server 硬依赖、Redis 无密码），因此 Web 进程只作为 **WebSocket 客户端**连 Qlib-Server，训练/回测在独立 `worker` 容器执行（`QLIB_WORKER_CONCURRENCY=1`）。API 镜像（Python 3.12）**物理不含 qlib**；worker 镜像（Python 3.11 + `--extra qlib`）是全仓唯一 import qlib 的进程，架构测试 + 单测双重断言。计算口径由自研最小模拟器统一（qlib 只取数），`COMPUTE_BACKEND=qlib|stub` 切换不影响费用模型。

## 测试

```bash
cd backend && uv run pytest -q        # 401 passed + 1 skipped，<15s，零外部依赖
uv run ruff check .                   # All checks passed
# 真实后端契约（可选，需本地服务；redis 端口按默认 HOST_PORT_REDIS=16379，用外部实例就改成实际值）
TEST_REDIS_URL=redis://localhost:16379/9 uv run pytest tests/contract -q
```

前端：`pnpm lint && pnpm typecheck && pnpm build`；e2e：`pnpm e2e`（Playwright 11 用例 / 8 条关键旅程，冒烟对象是在跑的部署栈）。

实机冒烟：`python3 scripts/stage6_smoke.py`（34 项断言，真实 qlib 全链路：因子计算 → csi300 回测 → 复用训练 → 导出/审计留痕；与 e2e 各占 4 次登录限流额度，建议错峰）。

## 文档

- `docs/stage1/` — 架构、目录、数据模型、API 与认证、端口与适配器、Qlib 集成、部署、风险与路线图
- `docs/stage2/` — 阶段 2：目标 / 文件树 / 代码 / 启动命令 / 测试方法 / 已知风险 / 验收清单
- `docs/stage3/` — 阶段 3：Qlib-Server 自建镜像、worker 计算链、部署与 smoke、验收清单
- `docs/stage4/` — 阶段 4：项目 / 数据（合规台账 + 导入校验）/ 因子库
- `docs/stage5/` — 阶段 5：因子快照 → 训练 → 双信号回测 → 四标注 → 任务中心
- `docs/stage6/` — 阶段 6：审计导出、RBAC 扫描、universe、导出/持仓/打印、因子计算/IC、训练复用、合规页、Playwright e2e
- 阶段 1 风险登记册与七阶段路线图见 `docs/stage1/08-risks-and-roadmap.md`

## License

MIT（阶段 7 前定稿，见 `docs/stage1/02-repo-structure.md`）。
