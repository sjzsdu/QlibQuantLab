# 阶段 1：架构设计与方案确认

> 状态：**待确认**。本阶段只产出设计文档，不写业务代码（根目录的 `docker-compose.yml` 也只在文档里给出草稿，阶段 2 才落盘）。
> 确认本阶段后进入阶段 2：后端骨架 + MockAuthProvider + 用户上下文 + 基础 API。

## 1. 本阶段目标

| # | 交付物 | 文件 |
|---|--------|------|
| 1 | 开发环境架构设计 + Mermaid 架构图（含时序图、部署模式 A/B） | [01-architecture.md](./01-architecture.md) |
| 2 | Monorepo 目录树 | [02-repo-structure.md](./02-repo-structure.md) |
| 3 | 数据库 ER 图 + 多租户隔离策略 | [03-data-model.md](./03-data-model.md) |
| 4 | API 列表 + 认证抽象层设计 + 权限矩阵 | [04-api-and-auth.md](./04-api-and-auth.md) |
| 5 | 可插拔接口（Ports & Adapters）设计 + 环境变量矩阵 | [05-ports-adapters.md](./05-ports-adapters.md) |
| 6 | Qlib-Server 集成设计 + 版本兼容矩阵 + worker 设计 | [06-qlib-integration.md](./06-qlib-integration.md) |
| 7 | `docker-compose.yml` / `docker-compose.prod.yml` 草稿 + `.env.example` + Traefik/Casdoor 清单 | [07-deployment.md](./07-deployment.md) |
| 8 | 已知风险 + 七阶段路线图 | [08-risks-and-roadmap.md](./08-risks-and-roadmap.md) |

## 2. 已确认的关键决策（来自你的 8 个回答）

| 决策项 | 结论 | 对设计的影响 |
|--------|------|--------------|
| 开发机 | **macOS Apple Silicon (M 系列)** | qlib-server 官方基础镜像 `continuumio/miniconda3:4.8.2` **只有 amd64**（已核对 Docker Hub），必须走 `platform: linux/amd64`（Rosetta 2）或自建 arm64 镜像 → 见风险 R1 |
| Qlib 数据来源 | **官方脚本从 Yahoo 下载 + `dump_bin`** | 提供 `scripts/bootstrap_qlib_data.sh` 一次性导入容器；数据登记进 `data_sources` + `data_licenses`（授权台账） |
| 缓存实现 | **Redis** | `CACHE_BACKEND=redis`，docker-compose 默认起 `redis:7-alpine`；`valkey`/`dragonfly` 作为可选适配器保留 |
| 对象存储 | **包含 MinIO** | compose 里有 minio；`STORAGE_BACKEND=s3|minio|local` 三个实现都能被真实验证 |
| 任务执行位置 | **独立 worker 容器**（与 backend 同镜像、不同启动命令） | 遵守「Qlib 不得嵌入 Web 进程」；backend 不 import qlib，只有 worker import |
| Casdoor | **已有生产实例** | 阶段 7 直接指向它，只需 `AUTH_PROVIDER=casdoor` + issuer/client_id/secret；本文档给出字段清单与验证步骤 |
| 前端 | **容器内 dev server + bind mount 热更新** | `docker compose up` 一键全起，`next.config.ts` rewrites 把 `/api` 转给 backend |
| 文档输出 | **写入 `docs/` + 聊天摘要** | 即本次交付形式 |

## 3. 阶段边界

**本阶段做**：设计、图、接口契约、compose 草稿、风险清单。
**本阶段不做**：任何 `src/` 业务代码、数据库迁移、容器镜像实际构建。

**后续阶段**
- 阶段 2：后端骨架 + MockAuthProvider + 用户上下文 + 基础 API（`/me`、`/auth/*`、健康检查、Alembic 首个迁移、架构约束测试）
- 阶段 3：打通 Qlib-Server，跑通最小回测任务
- 阶段 4：项目管理、数据管理、因子管理
- 阶段 5：模型训练、回测、结果可视化、任务中心
- 阶段 6：审计日志、权限校验、合规页面、测试与文档完善
- 阶段 7：接入 Casdoor（替换 MockAuthProvider）+ 生产部署方案

## 4. 启动命令（目标形态，阶段 3 起可用）

```bash
# 1. 准备环境变量
cp .env.example .env

# 2. 一键起全套（模式 A，不含 Casdoor）
docker compose up -d --build

# 3. 首次导入 Qlib 数据（一次性）
docker compose run --rm qlib-bootstrap      # Yahoo 下载 + dump_bin

# 4. 数据库迁移
docker compose run --rm migrate             # alembic upgrade head

# 5. 打开
open http://localhost:3000                  # 前端（MockAuthProvider 一键进入）
open http://localhost:15672                 # RabbitMQ 管理台
open http://localhost:9001                  # MinIO 控制台
```

阶段 1/2 期间只保证第 1、2、4、5 步可用（qlib 相关服务在阶段 3 才验证）。

## 5. 测试方法（贯穿全程的四层）

| 层 | 工具 | 验什么 |
|----|------|--------|
| L1 架构约束测试 | pytest，扫描 AST | 业务代码（`qqlab/api`、`qqlab/services`、`qqlab/models`）不得 import `redis`/`pika`/`boto3`/`socketio`/`qlib`/`casdoor`；只能依赖 `qqlab.ports` |
| L2 租户隔离测试 | pytest + 内存/SQLite 适配器 | 建两个 org，跨 org 读写必须 404/403；所有 ORM 模型必须有 `org_id` 且非空 |
| L3 集成测试 | pytest 对着 compose 起的依赖 | 真实 Postgres/Redis/RabbitMQ/MinIO 下各 Port 的 Adapter 契约一致 |
| L4 端到端 | Playwright | 登录 → 建项目 → 提交回测 → 看到曲线与指标 → 导出报告 |

契约测试（Adapter conformance test）是可插拔的关键：同一组测试用例同时跑 `InMemoryCache` 和 `RedisCache`，保证换后端不改业务代码。

## 6. 阶段 1 验收清单

- [ ] 架构图覆盖：模式 A（自包含）与模式 B（复用现有基础设施）两张图
- [ ] 目录树完整，能看出 ports / adapters / api / services / worker 的分层
- [ ] ER 图覆盖全部业务表，每张业务表都有 `org_id` 与 `created_by`
- [ ] API 列表覆盖 10 个核心功能模块，并标注权限
- [ ] 认证抽象层：`CurrentUser` + `AuthProvider` 五个方法 + Mock/Casdoor 两个实现的分工明确，第二阶段只改环境变量
- [ ] 五个 Port（Database/Cache/MessageQueue/Storage/Auth）有明确的方法签名与环境变量开关
- [ ] 明确 Qlib-Server 硬依赖 Redis + RabbitMQ 的说明，且文档写清「不能完全去掉」
- [ ] `docker-compose.yml` 草稿含 7 个服务；`docker-compose.prod.yml` 草稿含 Traefik labels 与 WS 升级头
- [ ] `.env.example` 区分 `# --- dev ---` 与 `# --- prod ---` 字段，无任何硬编码地址
- [ ] 风险清单 R1–R11 落盘，每条有缓解方案
- [ ] 你确认本阶段 → 进入阶段 2

## 7. 索引

```
docs/stage1/
├── README.md                 ← 本文件：目标、决策、验收清单
├── 01-architecture.md        ← 架构 + Mermaid 图 + 数据流
├── 02-repo-structure.md      ← 目录树
├── 03-data-model.md          ← ER 图 + 租户隔离
├── 04-api-and-auth.md        ← API 列表 + 认证抽象层 + RBAC
├── 05-ports-adapters.md      ← 可插拔接口 + 环境变量矩阵
├── 06-qlib-integration.md    ← Qlib-Server 集成 + 版本矩阵 + worker
├── 07-deployment.md          ← compose 草稿 + .env.example + Traefik/Casdoor
└── 08-risks-and-roadmap.md   ← 风险 + 路线图
```
