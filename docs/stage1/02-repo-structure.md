# 02 · Monorepo 目录树

阶段 2 开始按此落盘。**阶段 1 只有 `docs/`**。

```
QlibQuantLab/
├── README.md                          # 两种部署模式的使用说明（阶段 7 完成度最高）
├── LICENSE                            # MIT（推荐，阶段 7 前定稿）
├── .env.example                       # 分 # --- dev --- / # --- prod --- 两段
├── .gitignore                         # .env / *.pem / /qlib_data / node_modules / .venv
├── Makefile                           # make up / down / migrate / test / lint / e2e
├── docker-compose.yml                 # 模式 A：自包含
├── docker-compose.prod.yml            # 模式 B：复用外部依赖 + Traefik labels
├── docker-compose.dev-auth.yml        # 可选：阶段 7 本地起 Casdoor 验证用
│
├── backend/
│   ├── pyproject.toml                 # uv 管理；包名 qqlib-backend，含 app + worker 两个入口脚本
│   ├── uv.lock                        # 锁定（含 pyqlib、python-socketio、python-engineio）
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py                     # 读 Settings 拼 DATABASE_URL
│   │   └── versions/
│   ├── Dockerfile                     # python:3.12-slim + uv，一个镜像两个 CMD
│   ├── .python-version                # 3.12
│   ├── src/
│   │   └── qqlab/
│   │       ├── __init__.py
│   │       ├── main.py                # create_app()：CORS/限流/路由/异常处理
│   │       ├── config.py              # pydantic-settings，全部外部地址集中于此
│   │       ├── container.py           # ★ 唯一允许 import adapters 的地方
│   │       │
│   │       ├── ports/                 # ★ 抽象接口（Port），无任何实现
│   │       │   ├── __init__.py
│   │       │   ├── database.py        # DatabaseProvider
│   │       │   ├── cache.py           # CacheProvider（含分布式锁）
│   │       │   ├── message_queue.py   # MessageQueueProvider
│   │       │   ├── storage.py         # StorageProvider
│   │       │   ├── auth.py            # AuthProvider + CurrentUser
│   │       │   ├── audit.py           # AuditWriter
│   │       │   └── compute.py         # ComputePort（worker 侧训练/回测能力）
│   │       │
│   │       ├── adapters/              # ★ 具体实现（Adapter）
│   │       │   ├── database/
│   │       │   │   ├── postgres.py    # asyncpg + SQLAlchemy 2.0
│   │       │   │   └── sqlite.py      # 仅单测/本地兜底
│   │       │   ├── cache/
│   │       │   │   ├── redis_cache.py # CACHE_BACKEND=redis|valkey|dragonfly（同一协议，配置不同）
│   │       │   │   └── memory_cache.py# 单测
│   │       │   ├── mq/
│   │       │   │   ├── rabbitmq_mq.py # MQ_BACKEND=rabbitmq（aio-pika 只在此文件出现）
│   │       │   │   └── memory_mq.py   # 单测
│   │       │   ├── storage/
│   │       │   │   ├── s3_storage.py  # STORAGE_BACKEND=s3|minio（aioboto3/minio SDK 只在此文件）
│   │       │   │   └── local_storage.py
│   │       │   ├── auth/
│   │       │   │   ├── mock_provider.py    # AUTH_PROVIDER=mock
│   │       │   │   └── casdoor_provider.py # AUTH_PROVIDER=casdoor（阶段 7 实现，阶段 1 留骨架+TODO）
│   │       │   ├── audit/
│   │       │   │   └── db_audit_writer.py
│   │       │   └── compute/
│   │       │       └── qlib_compute.py     # 仅 worker 进程 import
│   │       │
│   │       ├── api/                   # 表现层
│   │       │   ├── deps.py            # get_current_user / require_roles / get_org_scope / confirm
│   │       │   ├── router.py          # 汇总 /api/v1
│   │       │   └── v1/
│   │       │       ├── auth.py        # login / callback / logout
│   │       │       ├── me.py          # 当前用户、权限
│   │       │       ├── projects.py
│   │       │       ├── data_sources.py
│   │       │       ├── datasets.py
│   │       │       ├── factors.py
│   │       │       ├── models.py
│   │       │       ├── strategies.py
│   │       │       ├── backtests.py
│   │       │       ├── jobs.py
│   │       │       ├── audit.py
│   │       │       ├── admin.py       # 组织/成员/系统配置
│   │       │       ├── legal.py       # 用户协议、风险提示、免责声明
│   │       │       └── system.py      # health/ready/info
│   │       │
│   │       ├── services/              # 业务用例（只依赖 ports + models + schemas）
│   │       │   ├── project_service.py
│   │       │   ├── data_service.py
│   │       │   ├── factor_service.py
│   │       │   ├── training_service.py
│   │       │   ├── backtest_service.py
│   │       │   ├── job_service.py
│   │       │   ├── audit_service.py
│   │       │   └── export_service.py
│   │       │
│   │       ├── repositories/          # org_id 强制过滤的唯一入口
│   │       │   ├── base.py            # BaseRepo[T]：所有查询自动带 scope.org_id
│   │       │   └── *.py
│   │       ├── models/                # SQLAlchemy 2.0 Declarative ORM
│   │       ├── schemas/               # Pydantic v2 请求/响应模型
│   │       ├── core/
│   │       │   ├── errors.py          # 业务异常 + 统一响应
│   │       │   ├── rbac.py            # 角色→权限矩阵
│   │       │   ├── tenant.py          # OrgScope、缓存 key 前缀、存储 key 前缀
│   │       │   ├── logging.py         # 结构化日志 + request_id
│   │       │   ├── security.py        # 签发/校验会话、CSRF
│   │       │   └── ratelimit.py       # 基于 CacheProvider 的令牌桶
│   │       └── worker/
│   │           ├── main.py            # qqlab-worker 入口：消费 → 派发
│   │           ├── qlib_env.py        # ★ 全仓唯一 import qlib 的文件
│   │           ├── handlers/
│   │           │   ├── train.py
│   │           │   ├── backtest.py
│   │           │   ├── factor_compute.py
│   │           │   └── dataset_import.py
│   │           └── progress.py        # 心跳、日志落盘、取消检测
│   └── tests/
│       ├── architecture/test_import_boundaries.py   # L1 架构约束
│       ├── unit/
│       ├── contract/                                  # Adapter 一致性契约测试
│       ├── integration/
│       └── e2e/                                       # Playwright（放 frontend 亦可）
│
├── frontend/
│   ├── package.json                   # pnpm；next@15 react@19 antd@5 echarts @tanstack/react-query
│   ├── pnpm-lock.yaml
│   ├── next.config.ts                 # rewrites: /api/:path* → http://backend:8000/api/:path*
│   ├── tsconfig.json
│   ├── Dockerfile                     # node:22-alpine，dev 模式 + bind mount
│   ├── playwright.config.ts
│   └── src/
│       ├── app/
│       │   ├── layout.tsx             # 含全站风险提示条
│       │   ├── page.tsx               # 首页 + 风险提示 + 免责声明
│       │   ├── login/page.tsx         # MockAuthProvider 一键进入
│       │   ├── legal/{terms,risk,disclaimer}/page.tsx
│       │   ├── projects/...
│       │   ├── data/...
│       │   ├── factors/...
│       │   ├── training/...
│       │   ├── backtests/...
│       │   ├── jobs/...
│       │   ├── audit/...
│       │   └── admin/...
│       ├── components/                # 布局、表格、ECharts 封装、任务状态、二次确认弹窗
│       ├── contexts/AuthContext.tsx   # ★ 前端唯一认证入口
│       ├── hooks/useCurrentUser.ts    # ★ 业务代码只用这个 hook
│       ├── hooks/useApi.ts            # TanStack Query 封装，统一 baseURL = "/api"
│       ├── lib/{api.ts,auth.ts,types.ts}
│       └── styles/
│
├── qlib-server/
│   ├── Dockerfile                     # 自建：多架构、锁定 pyqlib + socketio/engineio
│   ├── config_template.yaml           # 模板，compose 环境变量注入替换
│   ├── docker-compose.qlib.env.example
│   └── README.md                      # 为什么自建、与官方镜像的差异、Redis/RabbitMQ 硬依赖说明
│
├── scripts/
│   ├── bootstrap_qlib_data.sh         # 官方脚本下载 Yahoo 数据 → dump_bin（阶段 3 落盘）
│   ├── dev_up.sh                      # 一键：cp env → up → migrate → 状态检查
│   ├── smoke_api.sh                   # curl 冒烟
│   └── pin_versions.sh                # 导出 pip freeze / pnpm list 到锁文件
│
├── deploy/
│   ├── traefik/traefik.yml            # 模式 B 参考配置（仅 prod compose 引用）
│   └── casdoor/README.md              # 阶段 7：Application/Organization/角色映射配置说明
│
└── docs/
    ├── stage1/                        # 本阶段（9 个文件）
    ├── stage2..7/                     # 各阶段交付：目标 / 文件树 / 代码 / 启动 / 测试 / 风险
    ├── architecture/                  # 阶段 7 汇总成正式架构文档
    └── operations/                    # 部署清单、切换清单、故障排查
```

## 分层规则（会被 L1 架构测试强制）

| 目录 | 允许 import | 禁止 import |
|------|-------------|-------------|
| `qqlab/ports` | 标准库、`typing` | 任何第三方 SDK、`qqlab.adapters` |
| `qqlab/api` `qqlab/services` `qqlab/repositories` `qqlab/models` `qqlab/core` | `qqlab.ports` `qqlab.schemas` `qqlab.models` `qqlab.core` | `redis` `pika` `aio_pika` `boto3` `minio` `socketio` `qlib` `casdoor` `httpx`(对外部 IdP) |
| `qqlab/adapters/**` | 各自 SDK | `qqlab.api` `qqlab.services` |
| `qqlab/container.py` | `qqlab.adapters.*` + `qqlab.ports.*` | — |
| `qqlab/worker/qlib_env.py` | `qlib` `pyqlib` | — |
| `qqlab/worker/handlers/*` | `qqlab.ports` + `qlib_env` 之外的业务模块 | 直接 `import qlib` |
| `frontend/**` | 相对路径 `/api` | 硬编码 `http://localhost`、Casdoor SDK |

## 关键命名约定

- 环境变量统一 `QQLAB_` 前缀？**不**——按题目要求保持无前缀的领域前缀：`DATABASE_BACKEND`、`CACHE_BACKEND`、`MQ_BACKEND`、`STORAGE_BACKEND`、`AUTH_PROVIDER`，避免与用户既有基础设施变量冲突。
- 所有 ID 用 UUID v7/字符串，表主键统一 `id UUID PRIMARY KEY`。
- 时间统一 `TIMESTAMPTZ`，存储 UTC。
- 任务状态枚举统一：`queued | running | succeeded | failed | canceled`。
