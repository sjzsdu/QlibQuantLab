# 阶段 2 · 后端骨架 + Mock 认证 + 用户上下文 + 前端骨架 + 双套 Compose

> 一句话：**把阶段 1 的设计落成可运行的骨架** —— 后端分层跑通、17 张表一次迁移建全、Mock 一键登录拿到 `CurrentUser`、跨租户一律 404、架构约束有测试兜底；前端跑出布局与登录态骨架；两套 compose 落到仓库根目录。

## 交付物速览

| 项 | 状态 | 说明 |
|----|------|------|
| 后端包 `qqlab`（71 个 .py） | ✅ | ports / adapters / api / services / repositories / models / core / worker |
| Alembic `0001_initial` | ✅ | 一次建全 17 张表 + `dev-org` / `dev-user` / 成员关系 / 2 条 system_configs 种子 |
| MockAuthProvider + 会话 + CSRF | ✅ | 4 个 profile，`/me` 未登录 401，双提交 CSRF 强制 |
| 租户隔离 | ✅ | `org_id` 强制过滤，跨租户统一 404，架构测试断言 |
| 审计写入 | ✅ | 登录、CRUD、管理操作全部落 `audit_logs` |
| 前端骨架（7 路由） | ✅ | 风险提示条 + `AuthContext` + `useCurrentUser` + 4 个业务页 |
| `docker-compose.yml` / `docker-compose.prod.yml` | ✅ | `docker compose config -q` 双双通过 |
| 测试 | ✅ | **138 passed**（architecture 36 / unit 48 / contract 9 / api 45） |
| `ruff check` | ✅ | All checks passed（`ruff format` 已统一） |
| 前端 `lint` / `typecheck` / `build` | ✅ | 全绿 |
| `docker compose up` 实跑 | ⏳ | 本机 Docker daemon 未启动，**留给你本机验收**（见 [06-risks](./06-risks.md)） |
| Playwright 冒烟 | ⏳ | 按计划推迟到阶段 6，阶段 2 用 `pnpm build` + API 冒烟替代（偏差 D6） |

## 文档导航（按阅读顺序）

| 文件 | 内容 | 对应阶段 2 固定格式 |
|------|------|---------------------|
| [01-goal-and-tree.md](./01-goal-and-tree.md) | 目标 + 实际文件树 | 目标 / 文件树 |
| [02-backend.md](./02-backend.md) | 后端代码要点：分层、配置、容器、信封、认证、租户、API 清单、迁移 | 代码 |
| [03-frontend.md](./03-frontend.md) | 前端骨架代码要点：API 客户端、登录态、页面、风险提示 | 代码 |
| [04-deployment.md](./04-deployment.md) | 两套 compose、`.env`、Makefile、本机与容器启动命令 | 启动命令 |
| [05-testing.md](./05-testing.md) | 测试分层、跑法、实测结果、真实后端契约门控 | 测试方法 |
| [06-risks.md](./06-risks.md) | 已知风险 + 验收清单（逐条勾选）+ 与阶段 1 的偏差 | 已知风险 / 验收清单 |

## 与阶段 1 设计文档的偏差（9 条）

| # | 偏差 | 原因 | 影响 |
|---|------|------|------|
| D1 | 迁移文件名 `0001_initial.py`（阶段 1 写的是 `0001_init.py`） | 命名更自解释 | 无 |
| D2 | `adapters/database/{postgres,sqlite}.py` 合并为 `sqlalchemy_db.py` | 两者共用 SQLAlchemy 2.0 async 引擎，只是驱动与方言不同，拆两个文件会重复 90% 代码 | 无；`backend` 字段仍区分 `postgres`/`sqlite` |
| D3 | `repositories/{org,user}.py` 合并为 `identity.py` | 组织/用户/成员三张表总是一起读写 | 无 |
| D4 | `api/v1/system.py` 命名为 `health.py`（承载 `/health/live` `/health/ready` `/system/info`） | 三个端点都是运行状态，放一个文件 | 路径不变 |
| D5 | 角色用 JSON 列而非 Postgres 数组 | SQLite 测试要与 Postgres 同构；`JSONType` 在 Postgres 落 `jsonb` | 查询角色用 JSONB 包含操作，数据量级不需要 GIN |
| D6 | Playwright 冒烟推迟到阶段 6 | 阶段 2 前端无后端真值可断言，先用 `pnpm build` + API 冒烟 | 验收项「一键进入」阶段 2 只做代码级验证 |
| D7 | `GET /api/v1/auth/mock/enter` 设 `include_in_schema=False`，POST 版本进 OpenAPI | 避免 mock 端点污染对外接口文档 | 前端用的 GET 版本仍可用（阶段 1 契约不变） |
| D8 | `qlib-server` / `qlib-bootstrap` 挂在 `qlib` profile，默认不启动 | 阶段 3 才交付 `./qlib-server` 构建上下文与 `scripts/bootstrap_qlib_data.sh`，否则 `docker compose up --build` 必失败 | 阶段 3 删掉 `profiles` 即可；worker 对 `qlib-server` 的 `depends_on` 同期补回 |
| D9 | 模式 A 的 `minio` 改挂 `minio` profile、删 `minio-init`、默认 `STORAGE_BACKEND=local`；宿主端口参数化为 `HOST_PORT_*` | 当前环境拉不到 minio 镜像（Docker Hub 已移除、镜像源代理均失败）；宿主 5432/6379 被本机已有服务占用 | bucket 改由后端惰性创建；恢复步骤见 [06-risks §4](./06-risks.md) |

> 另有两处阶段 1 文档的自我修正（非偏差）：删除已废弃的 `DATABASE_URL_SYNC`（alembic 走 async engine），已同步更新 `05-ports-adapters.md` 与 `07-deployment.md`。

## 合规提示

本平台是**研究与教学工具**，所有输出（回测、指标、曲线）**不构成投资建议**；`GET /api/v1/legal/{terms,risk,disclaimer}` 提供协议、风险提示与免责声明正文，前端首屏常驻风险提示条，全部敏感操作写入审计日志。
