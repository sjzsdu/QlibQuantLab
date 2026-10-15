# 01 · 架构设计

## 1. 设计原则（硬约束的落地方式）

| 原则 | 落地方式 |
|------|----------|
| 端口与适配器（六边形架构） | `qqlab/ports/` 只放 Protocol/ABC，`qqlab/adapters/` 放实现，`qqlab/container.py` 按 `*_BACKEND` 环境变量装配 |
| 业务代码不碰基础设施 SDK | L1 架构约束测试（AST 扫描）强制执行，违规即测试失败 |
| Qlib 不进 Web 进程 | backend 镜像同一份代码两个入口：`uvicorn`（API）与 `qqlab-worker`（消费 RabbitMQ、`qlib.init` online 模式） |
| Qlib 硬依赖 Redis + RabbitMQ | 由 compose 提供；模式 B 指向用户已有实例；应用可与之共用，也可用 vhost/db 分离 |
| 认证先抽象后实现 | 阶段 1 就定 `AuthProvider` Port，Mock 与 Casdoor 两个 Adapter；`AUTH_PROVIDER` 切换 |
| 无硬编码地址 | 所有地址走 `pydantic-settings` 读环境变量；前端只用相对路径 `/api` |
| 应用层不感知反向代理 | 开发 compose 无 Traefik；Traefik labels 只在 `docker-compose.prod.yml` |

## 2. 服务拓扑（模式 A · 开发环境自包含）

```mermaid
flowchart TB
    subgraph Host["开发机 macOS Apple Silicon"]
        subgraph FE["frontend · Next.js 15 (node:22-alpine, :3000)"]
            UI["App Router 页面<br/>AntD + ECharts + TanStack Query"]
            RW["next.config.ts rewrites<br/>/api/* → http://backend:8000/api/*"]
        end

        subgraph APP["backend 镜像 · 两个入口"]
            API["backend (uvicorn :8000)<br/>FastAPI + SQLAlchemy async + Alembic"]
            AUTH["AuthProvider 实现<br/>mock（阶段1-6） / casdoor（阶段7）"]
            WORKER["worker<br/>pyqlib online 模式<br/>训练 / 回测 / 因子计算"]
        end

        subgraph QL["qlib-server · :9710 (amd64 / Rosetta)"]
            QS["Flask-SocketIO 数据服务<br/>calendar / instruments / features"]
        end

        subgraph INFRA["基础设施"]
            PG[("PostgreSQL 16 :5432<br/>业务数据 / 实验 / 审计")]
            RD[("Redis 7 :6379<br/>应用: db5 缓存+锁<br/>qlib-server: db0 任务会话")]
            RMQ[("RabbitMQ 3.13 :5672<br/>vhost /qqlab 应用任务<br/>vhost /  qlib task_queue+message_queue")]
            MIO[("MinIO :9000/:9001<br/>报告 / 模型产物")]
            DATA[("qlib_data 卷<br/>Yahoo → dump_bin 生成")]
        end
    end

    Browser["浏览器"] --> UI
    UI --> RW --> API
    API -->|Port: DatabaseProvider| PG
    API -->|Port: CacheProvider| RD
    API -->|Port: MessageQueueProvider| RMQ
    API -->|Port: StorageProvider| MIO
    API -->|Port: AuthProvider| AUTH

    RMQ -->|consume| WORKER
    WORKER -->|Port: DatabaseProvider| PG
    WORKER -->|Port: StorageProvider| MIO
    WORKER -->|"qlib.init(online) → WebSocket ws://qlib-server:9710"| QS
    QS --> RD
    QS --> RMQ
    QS --> DATA
    DATA -.->|同一数据卷挂载| WORKER
```

### 服务清单

| 服务 | 镜像/构建 | 端口 | 说明 |
|------|-----------|------|------|
| `frontend` | 本地 `frontend/Dockerfile`（node:22-alpine） | 3000 | Next.js dev server，bind mount 源码热更新 |
| `backend` | 本地 `backend/Dockerfile`（python:3.12-slim + uv） | 8000 | FastAPI；`uvicorn qqlab.main:app` |
| `worker` | 同 `backend` 镜像 | — | `qqlab-worker` 入口；import qlib |
| `migrate` | 同 `backend` 镜像 | — | 一次性：`alembic upgrade head` |
| `qlib-server` | 本地 `qlib-server/Dockerfile` | 9710 | **硬依赖** Redis + RabbitMQ |
| `qlib-bootstrap` | 同 `qlib-server` 镜像 | — | 一次性：Yahoo 下载 + `dump_bin` |
| `postgres` | `postgres:16-alpine` | 5432 | |
| `redis` | `redis:7-alpine` | 6379 | 应用与 qlib-server 共用实例、分 db |
| `rabbitmq` | `rabbitmq:3.13-management-alpine` | 5672 / 15672 | 共用 broker、分 vhost |
| `minio` | `minio/minio` | 9000 / 9001 | |

> 开发环境不需要 Casdoor 容器，`AUTH_PROVIDER=mock`。

## 3. 模式 B · 复用现有基础设施

```mermaid
flowchart LR
    subgraph Edge["用户已有 Traefik"]
        T[Traefik<br/>HTTPS + 中间件]
    end

    subgraph App["仅部署应用服务"]
        FE2[frontend]
        BE2[backend]
        WK2[worker]
        QS2[qlib-server]
    end

    subgraph Existing["用户已有基础设施（只改环境变量）"]
        PG2[("PostgreSQL")]
        RD2[("Redis")]
        RMQ2[("RabbitMQ")]
        S3[("S3 兼容存储")]
        CD["Casdoor OIDC<br/>（阶段 7）"]
    end

    Browser2[浏览器] -->|HTTPS| T
    T -->|Host 路由| FE2
    T -->|/api| BE2
    T -->|WebSocket 升级头 + passHostHeader| QS2
    BE2 --> PG2
    BE2 --> RD2
    BE2 --> RMQ2
    BE2 --> S3
    BE2 <-->|OIDC Authorization Code + PKCE| CD
    WK2 --> PG2
    WK2 --> RMQ2
    WK2 -->|ws://| QS2
    QS2 --> RD2
    QS2 --> RMQ2
```

**两种模式的唯一差别**：`docker-compose.yml` 起全部依赖；`docker-compose.prod.yml` 用 `external: true` 网络 + 环境变量指向已有服务，应用镜像与代码完全一致。

**Qlib-Server 的硬依赖不可消除**：它内部用 Redis 维护客户端 session-id、用 `python-redis-lock` 防 IO 冲突、用 RabbitMQ 的 `task_queue`/`message_queue` 做数据任务分发。模式 B 下这两个地址仍然必填（`QLIB_SERVER_REDIS_HOST` / `QLIB_SERVER_QUEUE_HOST`），可以指向用户已有的 Redis/RabbitMQ，但**不能留空**。文档与 `/api/v1/system/info` 里都会显式提示这一点。

## 4. 关键时序：提交一次回测

```mermaid
sequenceDiagram
    autonumber
    participant U as 浏览器
    participant FE as frontend (/api)
    participant BE as backend
    participant PG as PostgreSQL
    participant MQ as RabbitMQ (vhost /qqlab)
    participant WK as worker
    participant QS as qlib-server
    participant RD as Redis

    U->>FE: POST /api/v1/backtests（携带会话 token）
    FE->>BE: rewrite /api/* 转发
    BE->>BE: AuthProvider.verify_token → CurrentUser
    BE->>BE: 校验 org_id 租户范围 + rbac(require_roles)
    BE->>PG: INSERT backtests(status=queued) + jobs(kind=backtest)
    BE->>MQ: publish("jobs.backtest", payload)
    BE->>PG: audit_logs(action=backtest.submit)
    BE-->>U: 201 {job_id, backtest_id}

    MQ->>WK: consume jobs.backtest
    WK->>PG: UPDATE jobs(status=running, locked_by)
    WK->>WK: qlib.init(online) — flask_server=qlib-server:9710
    WK->>QS: WebSocket emit("calendar_request" / "feature_request")
    QS->>RD: Redis Lock + session-id 去重
    QS->>MQ: vhost / 的 task_queue
    MQ->>QS: DataProcessor 计算 calendar/instruments/features
    QS->>RD: 写入缓存
    QS-->>WK: *_response（数据/uri）
    WK->>WK: 回测（自定义滑点/手续费/冲击成本）
    WK->>PG: UPDATE backtests(metrics, curve_uri) / jobs(succeeded)
    WK->>WK: 曲线与指标写对象存储（STORAGE_BACKEND）
    U->>FE: GET /api/v1/backtests/{id}/curve（轮询或 SSE）
    FE->>BE: 读 PG + Storage
    BE-->>U: 收益曲线 / 回撤 / 换手率 / 数据区间 / 费用假设
```

## 5. 分层与依赖方向

```mermaid
flowchart TB
    subgraph L1["表现层"]
        A1["api/ （FastAPI router、依赖注入、schema 校验）"]
        A2["worker/ （任务消费入口）"]
    end
    subgraph L2["业务层"]
        B1["services/ （用例编排、事务边界、审计埋点）"]
        B2["core/ （rbac、tenant、errors、logging）"]
    end
    subgraph L3["领域与持久化契约"]
        C1["models/ （SQLAlchemy ORM）"]
        C2["schemas/ （Pydantic v2）"]
        C3["ports/ （Protocol 抽象）  ← 唯一允许被上下层共同依赖的东西"]
    end
    subgraph L4["基础设施实现"]
        D1["adapters/redis、adapters/rabbitmq、adapters/s3 …"]
    end
    L1 --> L2 --> L3
    L4 -.->|仅被 container.py 装配| L3
```

依赖方向：`api → services → ports ← adapters`。`adapters` 反向实现 `ports`，由 `container.py` 在启动时装配 —— 这就是「业务代码只依赖抽象接口」的结构保证。

## 6. 数据流与隔离

| 资源 | 隔离方式 |
|------|----------|
| 业务数据（Postgres） | 每表 `org_id` 非空 + 仓库层强制 WHERE + 复合索引 `(org_id, id)`；L2 测试保证 |
| Qlib 数据目录 | `qlib_data/{org_id}/…` 卷内子目录；worker `qlib.init` 的 `provider_uri` 按 org 拼接 |
| 实验/模型目录 | 同上，`experiments/{org_id}/{project_id}/…` |
| 缓存 key | `qqlab:{org_id}:…` 前缀，避免跨租户缓存污染 |
| RabbitMQ | 应用任务走 vhost `/qqlab`，路由键带 `org_id` 头；qlib-server 独占 vhost `/` |
| 对象存储 | key 前缀 `{org_id}/…` |
| 策略可见性 | 默认 `private`；改 `public` 需二次确认接口（`POST /strategies/{id}/publish` + `confirm=true`） |

## 7. 安全与合规在架构上的位置

```mermaid
flowchart LR
    R["请求"] --> M1["HTTPS(生产)/HTTP(dev)"]
    M1 --> M2["速率限制（Redis 令牌桶，CacheProvider 实现）"]
    M2 --> M3["CORS 白名单 + CSRF 双提交 cookie"]
    M3 --> M4["AuthProvider → CurrentUser"]
    M4 --> M5["RBAC require_roles"]
    M5 --> M6["租户 org_id 强制过滤"]
    M6 --> H["处理器"]
    H --> Z["audit_logs 落库（登录/提交/策略变更/导出）"]
```

- 密钥全部来自环境变量（`.env` 已在 `.gitignore`），`.env.example` 只给占位符。
- 敏感操作（删除项目、策略公开、批量导出、修改系统配置）需 `confirm=true` 二次确认参数。
- 首页、注册页、报告页常驻风险提示；所有报告导出自动附加「数据区间 / 参数 / 费用假设 / 局限性 / 不构成投资建议」页脚。
