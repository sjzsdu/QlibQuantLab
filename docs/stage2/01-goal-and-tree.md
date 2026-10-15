# 01 · 阶段 2 目标与文件树

## 1. 目标

### 1.1 阶段 1 承诺的目标（原文摘录）

> 后端骨架跑起来：FastAPI 工厂、`pydantic-settings` 配置、五个 Port 的接口 + 各自至少一个实现、`MockAuthProvider`、`CurrentUser` 上下文、RBAC、Alembic 首个迁移（含全部表 + `dev-org`/`dev-user` seed）、审计写入、健康检查、架构约束测试。前端搭出布局骨架 + `AuthContext` + `useCurrentUser` + 首页风险提示。

### 1.2 本阶段拆解后的 10 条可验收目标

| # | 目标 | 落点 |
|---|------|------|
| G1 | 应用工厂可启动，全部外部地址来自环境变量，缺配置启动即失败 | `main.py` `config.py` |
| G2 | 7 个 Port 都有实现，唯一装配点是 `container.py` | `ports/` `adapters/` `container.py` |
| G3 | `AUTH_PROVIDER=casdoor`（骨架未实现）→ 启动抛 `ConfigError`，绝不静默降级 mock | `container._build_auth` |
| G4 | Mock 一键进入拿到 `CurrentUser`（含 `org_id` / `roles`），未登录 `/me` 401 | `mock_provider` `auth_service` `api/v1/me.py` |
| G5 | 会话只认本平台签发的 JWT cookie；非安全方法强制双提交 CSRF | `core/security.py` `core/middleware.py` |
| G6 | RBAC：角色 → 权限矩阵，缺权限 403；`/me/permissions` 可查 | `core/rbac.py` |
| G7 | 17 张表一次迁移建全 + 开发种子；alembic 全程 async | `alembic/versions/0001_initial.py` |
| G8 | 所有业务表带 `org_id` 且被强制过滤，跨租户统一 404 | `core/tenant.py` `repositories/base.py` |
| G9 | 登录与 CRUD 全部落审计日志（含 `request_id`） | `adapters/audit/db_audit_writer.py` |
| G10 | 架构约束有自动化测试兜底（不碰 SDK / 不硬编码地址 / 租户列齐全） | `tests/architecture/` |

**同时交付**：前端骨架（布局 + 风险提示 + 登录态）、两套 compose、`.env.example`、`Makefile`、根 `README.md`。

## 2. 文件树（阶段 2 结束时的真实状态）

> 阶段 1 时仓库只有 `docs/`；下面是本阶段落盘的全部内容（已剔除 `node_modules` / `.venv` / `.next` / 缓存）。

```
QlibQuantLab/
├── README.md                     # 两种部署模式 + 快速开始 + 免责声明
├── .gitignore                    # .env / node_modules / .venv / .next / data / *.db
├── .env.example                  # 模式 A+B 全量变量（必填 6 项已标注）
├── Makefile                      # help/env/install/dev/migrate/test/lint/format/smoke/clean
├── docker-compose.yml            # 模式 A · 自包含
├── docker-compose.prod.yml       # 模式 B · 复用外部依赖 + Traefik labels
├── scripts/
│   └── README.md                 # 阶段 3 将落盘的脚本清单（qlib-bootstrap 依赖目录占位）
│
├── backend/
│   ├── pyproject.toml            # uv；入口 qqlab-api / qqlab-worker；ruff 配置
│   ├── uv.lock
│   ├── alembic.ini
│   ├── Dockerfile                # base → builder → dev → runtime（四阶段）
│   ├── .dockerignore
│   ├── .env.example              # 本机零依赖开发：sqlite + memory
│   ├── .python-version           # 3.12
│   ├── README.md
│   ├── alembic/
│   │   ├── env.py                # async engine，URL 来自 Settings
│   │   ├── script.py.mako
│   │   └── versions/0001_initial.py      # 17 表 + seed（幂等）
│   ├── src/qqlab/
│   │   ├── main.py               # create_app()：中间件 / 路由 / 异常 → 统一信封
│   │   ├── config.py             # 62 个字段，6 个必填；生产环境启动校验
│   │   ├── container.py          # ★ 唯一 import adapters 的地方
│   │   ├── ports/                # ★ 纯抽象，仅依赖标准库（TYPE_CHECKING 下的类型导入）
│   │   │   ├── database.py       # DatabaseProvider
│   │   │   ├── cache.py          # CacheProvider（含分布式锁）
│   │   │   ├── message_queue.py  # MessageQueueProvider
│   │   │   ├── storage.py        # StorageProvider + ObjectNotFoundError
│   │   │   ├── auth.py           # AuthProvider + CurrentUser + Role
│   │   │   ├── audit.py          # AuditWriter + AuditAction 枚举
│   │   │   └── compute.py        # ComputePort（阶段 3 落地，先给接口）
│   │   ├── adapters/             # ★ 具体实现，SDK 只在这里出现
│   │   │   ├── database/sqlalchemy_db.py   # asyncpg / aiosqlite 同一实现
│   │   │   ├── cache/{redis_cache,memory_cache}.py
│   │   │   ├── mq/{rabbitmq_mq,memory_mq}.py
│   │   │   ├── storage/{s3_storage,local_storage}.py
│   │   │   ├── auth/{mock_provider,casdoor_provider}.py   # casdoor: IMPLEMENTED=False
│   │   │   └── audit/db_audit_writer.py
│   │   ├── api/
│   │   │   ├── deps.py           # get_current_user / require_permission / get_org_scope / confirm
│   │   │   ├── cookies.py        # 会话与 CSRF cookie 的签发/清除
│   │   │   ├── router.py         # /api/v1 汇总
│   │   │   └── v1/{health,auth,me,orgs,legal,projects,admin,audit}.py
│   │   ├── services/             # 用例层：auth / project / admin / audit / legal
│   │   ├── repositories/         # base(强制 org_id) + project + identity + audit
│   │   ├── models/               # 17 表；TENANT_MODELS / NON_TENANT_MODELS
│   │   ├── schemas/common.py     # 统一分页 / 信封 / 确认参数
│   │   ├── core/                 # errors · rbac · tenant · security · ratelimit · logging · middleware · ids
│   │   ├── legal/{terms,risk,disclaimer}.md   # 打进 wheel 的包数据
│   │   └── worker/{main.py,qlib_env.py}       # 骨架：分发器 + qlib 环境封装（阶段 3 接）
│   └── tests/                    # 14 个测试文件，138 用例
│       ├── conftest.py           # env 注入、session 级 app、login/csrf_headers/other_org_client
│       ├── architecture/         # import 边界 · 租户列 · 硬编码地址
│       ├── unit/                 # config · rbac · security · ratelimit
│       ├── contract/             # cache · mq · storage（真实后端用环境变量门控）
│       └── api/                  # health/legal · auth 流程 · projects 隔离 · admin/audit
│
├── frontend/
│   ├── Dockerfile                # deps → dev → builder → runner（四阶段）
│   ├── next.config.ts            # /api/:path* → BACKEND_INTERNAL_URL（浏览器只见相对路径）
│   ├── package.json              # next 15.5 · react 19.3 · antd 5.29 · @tanstack/react-query 5
│   ├── pnpm-lock.yaml · tsconfig.json · eslint.config.mjs · .dockerignore
│   └── src/
│       ├── app/layout.tsx        # 风险提示条（全站常驻）
│       ├── app/page.tsx          # 首页：风险提示 + 免责声明 + 模块入口
│       ├── app/login/page.tsx    # Mock 一键进入
│       ├── app/projects/page.tsx # 项目列表（阶段 4 起扩展）
│       ├── app/audit/page.tsx    # 审计日志
│       ├── app/legal/[code]/page.tsx   # 协议 / 风险 / 免责（markdown 渲染）
│       ├── components/{AppShell,RequireAuth,RiskBanner,EmptyState}.tsx
│       ├── contexts/AuthContext.tsx     # ★ 前端唯一认证入口
│       ├── hooks/{useCurrentUser,useApi}.ts(x)  # ★ 业务代码只用 useCurrentUser
│       └── lib/{api,cookies,types,markdown}.ts  # 信封解析 + CSRF 双提交
│
└── docs/
    ├── stage1/                   # 9 个设计文档（已确认；本阶段修正了 DATABASE_URL_SYNC）
    └── stage2/                   # 本阶段交付文档（本文件所在目录）
```

## 3. 与阶段 1 文件树的差异说明

| 阶段 1 计划 | 实际 | 偏差编号 |
|-------------|------|----------|
| `adapters/database/{postgres,sqlite}.py` | `adapters/database/sqlalchemy_db.py` | D2 |
| `repositories/{org,user,project,audit}.py` | `repositories/{identity,project,audit,base}.py` | D3 |
| `api/v1/system.py` | `api/v1/health.py`（同路径 `/system/info`） | D4 |
| `alembic/versions/0001_init.py` | `0001_initial.py` | D1 |
| `tests/e2e/`（Playwright） | 阶段 6 交付 | D6 |
| `qlib-server/` `scripts/*.sh` `deploy/` | 阶段 3 / 阶段 7 交付（本阶段只留 `scripts/README.md` 占位） | 按计划 |
| `docker-compose.dev-auth.yml` | 阶段 7（本地起 Casdoor 验证） | 按计划 |

新增（阶段 1 未列、但骨架必需）：`core/middleware.py`（request_id + 结构化访问日志 + CSRF cookie 播种）、`core/ids.py`（`stable_uuid`，把 `dev-user` 这类外部 ID 映射成合法 UUID 主键）、`api/cookies.py`、`lib/cookies.ts`、`backend/.env.example`（本机零依赖开发）。
