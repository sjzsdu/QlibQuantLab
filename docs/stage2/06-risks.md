# 06 · 已知风险、验收清单与偏差说明

## 1. 已知风险（阶段 2 视角）

| # | 风险 | 影响 | 本阶段的处置 | 状态 |
|---|------|------|--------------|------|
| S2-1 | **`docker compose up -d --build` 未实跑**：交付时本机 Docker daemon 未运行 | 依赖安装顺序、健康检查时长、bind mount 行为需实机确认 | 两套 compose 已过 `config -q`；服务清单与依赖关系已核对 | ⏳ 待你本机验收 |
| S2-2 | **前端无 e2e**：Playwright 推迟到阶段 6（偏差 D6） | 登录跳转、CSRF 实际生效、跨页状态无自动化断言 | 阶段 2 用 `pnpm build` + 后端 45 条 API 测试覆盖同一契约 | ⏳ 阶段 6 |
| S2-3 | **SQLite ≠ Postgres**（JSONB、数组、部分索引） | 测试通过不等于生产库通过 | 角色改 JSON 列（D5）规避数组差异；`JSONType` 双方言；真实后端契约用例可用 `TEST_*` 环境变量门控 | ⚠️ 已知取舍 |
| S2-4 | **macOS + bind mount 下 `uvicorn --reload` 文件事件**（阶段 1 R8/R 风险） | 改代码不热重载 | compose 预留 `WATCHFILES_FORCE_POLLING=true` 的处理办法（04 文档 §7）；必要时关 `--reload` | ⚠️ 需实机确认 |
| S2-5 | **Apple Silicon 跑 amd64 的 Qlib-Server**（阶段 1 R1） | 阶段 3 Qlib-Server 启动慢/起不来 | compose 已设 `QLIB_SERVER_PLATFORM=linux/amd64`，阶段 3 实测 | ⏳ 阶段 3 |
| S2-6 | **`AuditWriter` 独立会话**：审计在自己的事务里提交 | 主事务回滚时审计仍会留下（登录失败、越权尝试因此不会丢）；极端情况下「有审计无数据」 | 有意为之：审计要记录**尝试**，不只是成功结果 | ✅ 设计如此 |
| S2-7 | **`/api/v1/auth*` 豁免 CSRF** | 登录相关写请求不受双提交保护（此时也还没有会话） | 由限流（登录 5 次/分）+ 会话 cookie `SameSite=Lax` + 状态参数兜底 | ⚠️ 已知取舍 |
| S2-8 | **限流是固定窗口** | 窗口边界可瞬时放行两倍请求 | 单实例够用；多副本/精确限流留到阶段 6 评估 | ⚠️ 已知取舍 |
| S2-9 | **MinIO 镜像在当前环境完全拉不到**：`minio/minio` 已从 Docker Hub 移除，quay 与国内代理（daocloud / 1ms / dockerproxy）均失败；`minio/mc` 同样不可用 | 模式 A 无法起对象存储服务 | minio 隔离到 `--profile minio`，默认 `STORAGE_BACKEND=local`（`objects_data` 卷持久化）；bucket 改由 `S3StorageProvider.ping()` 惰性创建，去掉 `minio-init` 容器；`ping()` 已加固为「任何异常 → False」，`/health/ready` 变红灯而非 500 | ⏳ **待镜像源**（恢复步骤见 §4） |
| S2-9b | `minio/minio:latest` 浮动标签 | 拿到可用源后仍可能某天行为变化 | 恢复后阶段 6 收敛到固定 digest | ⏳ 阶段 6 |
| S2-10 | **`qlib-server` 挂 profile 默认不启动**（偏差 D8） | 阶段 3 若忘记去掉 profile，worker 连不上 Qlib 且 `depends_on` 也缺失 | 04 文档与 compose 注释都标了「阶段 3 补回」 | ⏳ 阶段 3 |
| S2-11 | **`system_configs.org_id` 靠 `(org_id, config_key)` 唯一约束首列覆盖索引** | 与其它表的单列索引形态不一致 | 架构测试明确接受「唯一约束首列」这一形态 | ✅ 已覆盖 |
| S2-12 | **阶段 1–6 固定 `AUTH_PROVIDER=mock`** | 生产误配会被启动校验拦下（不会静默上线） | `APP_ENV=production` 下 `mock` 直接 `ConfigError` 退出 | ✅ 有测试 |

> 阶段 1 风险登记册（R1–R10）中，阶段 2 触发的条目只有 R8（前端版本）与 R1 的预留位，其余在阶段 3+ 才进入影响面，详见 `docs/stage1/08-risks-and-roadmap.md`。

## 2. 验收清单（阶段 2）

> 对应 `docs/stage1/08-risks-and-roadmap.md` §3。✅ = 本阶段已用测试/命令验证；⏳ = 需要 Docker/浏览器的实机验收。

| # | 验收项（阶段 1 原文） | 状态 | 验证方式 |
|---|------------------------|------|----------|
| A1 | `docker compose up -d --build` 一键全绿（qlib 相关服务不计入） | ⏳ | 已过 `config -q`；首次实跑暴露两个问题并已修复（宿主端口冲突 → `HOST_PORT_*` 参数化；minio 镜像拉不到 → `--profile minio` + `STORAGE_BACKEND=local`）。仍需你复跑一次确认全绿 |
| A2 | 首页显示风险提示；`/login` 一键进入，顶栏显示 `dev-user @ dev-org` | ⏳ | 代码级已核对：`layout.tsx` 全站挂 `RiskBanner`；`AppShell` 顶栏渲染「显示名 + `user_id @ org_id`」；待浏览器验收 |
| A3 | `GET /api/v1/me` 返回正确用户与角色；换 `profile=viewer` 后权限被拒 | ✅ | `test_login_then_me`、`test_profile_switch_changes_identity`、`test_viewer_cannot_write`（403 / code 1002） |
| A4 | 双 org 隔离测试通过；L1 架构测试通过 | ✅ | `test_cross_tenant_is_isolated`（列表不可见 / 详情 404 / 删除 404 且原数据仍在）+ `tests/architecture/` 36 项全绿 |
| A5 | `AUTH_PROVIDER` 切到 `casdoor` 时启动失败并给出清晰提示 | ✅ | `test_casdoor_not_implemented_fails_fast` → `ConfigError`：「AUTH_PROVIDER=casdoor 但 CasdoorAuthProvider 尚未实现（阶段 7 交付）…」 |
| A6 | 所有外部地址来自环境变量，代码里 grep 不到 `localhost:` / IP | ✅ | `test_no_hardcoded_host_or_ip` + `test_only_config_reads_environment`（AST 级扫描，`0.0.0.0` 绑定地址豁免） |
| A7 | `docker-compose.yml` 与 `docker-compose.prod.yml` 落到根目录 | ✅ | 两文件已落盘并 `config -q` 通过 |

**补充验收（阶段 2 实际做到的）**

| # | 项 | 状态 | 证据 |
|---|----|------|------|
| B1 | 全量测试与静态检查 | ✅ | `pytest` **141 passed**；`ruff check` **All checks passed**；`ruff format --check` 93 files unchanged |
| B2 | 前端质量门 | ✅ | `pnpm lint` / `typecheck` / `build` 全绿（7/7 静态页） |
| B3 | 17 张表一次迁移建全 + `dev-org`/`dev-user` 种子 + 幂等 | ✅ | `tests/integration/test_alembic_migration.py`（真跑 alembic 子进程） |
| B4 | 未登录 401、CSRF 强制、登出清会话 | ✅ | `tests/api/test_auth_flow.py` |
| B5 | 删除类操作需 `confirm=true` | ✅ | 项目删除、成员移除两处（code 1007 / HTTP 400） |
| B6 | 审计按 org 隔离且可按 action 检索 | ✅ | `test_audit_log_records_project_create`、`test_audit_is_tenant_scoped` |
| B7 | 法务三件套可读且含核心警示语 | ✅ | `test_legal_content_public_and_compliant`（`投资有风险` / `不构成`） |
| B8 | 无任何密钥泄漏到 `/system/info` | ✅ | `test_system_info_has_no_secrets` |

## 3. 与阶段 1 的偏差（详细说明）

| # | 阶段 1 计划 | 阶段 2 实际 | 理由与影响 |
|---|-------------|-------------|------------|
| **D1** | `alembic/versions/0001_init.py` | `0001_initial.py` | 仅文件名；迁移内容与「一次建全 + seed」一致 |
| **D2** | `adapters/database/postgres.py` + `sqlite.py` | `adapters/database/sqlalchemy_db.py` | 两者共用 SQLAlchemy 2.0 async 引擎，差异只有驱动与方言（`backend` 字段区分）；拆开会产生 90% 重复代码。契约测试仍分别覆盖两种 backend |
| **D3** | `repositories/{org,user,project,audit}.py` | `repositories/{identity,project,audit,base}.py` | 组织/用户/成员三表读写路径一致，合并为 `identity.py`；阶段 4 加业务表时再按聚合拆 |
| **D4** | `api/v1/system.py` | `api/v1/health.py` | `/health/live`、`/health/ready`、`/system/info` 同属运行状态；**对外路径不变** |
| **D5** | 角色用 Postgres 数组 | 角色用 `JSONType`（Postgres→jsonb，SQLite→json） | 单测要与生产同构；数组类型在 SQLite 无法表达。查询按 JSON 包含即可，暂不需要 GIN（角色仅 4 种取值） |
| **D6** | 阶段 2 跑 Playwright 冒烟 | 推迟到阶段 6 | 阶段 2 前端仅骨架，断言价值低；先用 `pnpm build` + 45 条 API 测试锁契约，阶段 6 补 e2e（阶段 1 路线图本就把 e2e 列在阶段 6） |
| **D7** | 未约定 mock 进入端点的 OpenAPI 可见性 | `GET /auth/mock/enter` 设 `include_in_schema=False`，`POST` 版本进文档 | 前端使用 GET（302）；避免 mock 端点出现在对外接口文档里。**契约本身未变** |
| **D8** | compose 里 `qlib-server` 为常驻服务、`qlib-bootstrap` 挂 `bootstrap` profile | 两者都挂 `qlib` profile；`qlib-bootstrap` 改名沿用；worker 暂不 `depends_on qlib-server` | `./qlib-server` 构建上下文与 `scripts/bootstrap_qlib_data.sh` 要到阶段 3 才存在，否则 `up --build` 必失败。阶段 3 删除 `profiles:` 并补 `worker.depends_on` 即可 |
| **D9** | 模式 A 常驻 `minio` + `minio-init`（mc 建桶），`STORAGE_BACKEND=minio` | `minio` 挂 `minio` profile（默认不启动），删除 `minio-init`，默认 `STORAGE_BACKEND=local` + `objects_data` 卷 | 当前环境拉不到 minio 镜像（见 §4 恢复步骤）；bucket 改由后端惰性创建，反而少一个外部镜像依赖。宿主端口同时参数化为 `HOST_PORT_*`（默认 pg 5433 / redis 16379，避开本机占用） |

**两处阶段 1 文档的自我修正（非偏差）**：删除 `DATABASE_URL_SYNC` —— `alembic/env.py` 走 async engine，从 `Settings` 直接取 `DATABASE_URL`，无需同步驱动；`docs/stage1/05-ports-adapters.md` 与 `07-deployment.md` 已同步更新。

## 4. 遗留事项：MinIO 恢复步骤（待镜像源）

**现状**：`minio/minio` 服务端镜像在 Docker Hub 已不存在，quay 与国内代理（daocloud / 1ms / dockerproxy）全部拉取失败；`minio/mc` 同样不可用。因此：

- compose 里 `minio` 已隔离到 `profiles: ["minio"]`，默认 `docker compose up` 不会碰它；
- `minio-init` 容器已删除 —— bucket 改由后端 `S3StorageProvider.ping()` 惰性创建（`head_bucket` 失败 → `create_bucket`），少一个外部镜像依赖；
- 默认 `.env` 用 `STORAGE_BACKEND=local` 兜底（对象落 `objects_data` 命名卷，重建容器不丢）。

**拿到可用镜像源后的恢复方法**：

```bash
# 1) .env 改回
#    STORAGE_BACKEND=minio
# 2) 确认 minio 镜像源（可给 daemon 配 registry mirror，或改用内网/自建镜像，或固定 digest）
# 3) 起服务
docker compose --profile minio up -d minio
# 4) 验证
curl -sf http://localhost:9000/minio/health/live && echo ok   # 宿主机探活
curl -s  localhost:8000/api/v1/health/ready | jq .data.checks  # storage 应变 true
```

> 恢复时不需要再加任何初始化容器；`STORAGE_S3_*` 五个变量已在 `.env.example` 里备好，只改 `STORAGE_BACKEND` 一个开关。

## 5. 阶段 3 进入前的建议动作

1. 你本机执行 `make dev`（或 `cp .env.example .env && docker compose up -d --build`），确认 A1/A2 两项 ⏳。
2. 跑一次 `make test`，确认 141 用例在你机器上同样全绿。
3. 确认无异议后进入**阶段 3：打通 Qlib-Server + 最小回测**（自建 qlib-server 镜像、版本矩阵实测、`qlib_env.py`、Yahoo 数据导入、`ComputePort` 实现）。
