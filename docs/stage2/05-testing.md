# 05 · 测试方法（阶段 2 · 141 个用例全绿）

## 1. 测试分层

| 层 | 目录 | 文件数 | 用例 | 验证什么 |
|----|------|--------|------|----------|
| L1 架构约束 | `tests/architecture/` | 3 | **36** | import 边界、租户列与索引、硬编码地址/环境变量读取、必填配置 |
| L2 单元 | `tests/unit/` | 4 | **48** | RBAC 矩阵、会话签发校验、CSRF/开放重定向、限流令牌桶、配置校验 |
| L3 契约 | `tests/contract/` | 3 | **9** | 同一组用例跑多套实现：cache（memory ∥ redis）、mq（memory ∥ rabbitmq）、storage（local ∥ s3） |
| L4 API | `tests/api/` | 4 | **45** | 端到端 HTTP：信封、认证流、CSRF、租户隔离、权限、审计 |
| L5 集成 | `tests/integration/` | 1 | **3** | 真跑 `alembic upgrade head` 子进程：17 表 + 种子 + 幂等 |
| 合计 | | **15** | **141** | |

## 2. 跑法

```bash
cd backend
uv run pytest -q                      # 全部（<3s，无外部依赖）
uv run pytest tests/architecture -q   # 只跑架构约束
uv run ruff check . && uv run ruff format --check .
# 或者从仓库根：
make test-backend
```

**真实后端契约用例默认跳过**，给环境变量才跑（避免 CI 强依赖服务）：

```bash
# 端口按模式 A 默认映射（redis 走 HOST_PORT_REDIS=16379；用外部实例就改成实际地址）
TEST_REDIS_URL=redis://localhost:16379/9      uv run pytest tests/contract/test_cache_contract.py -q
TEST_MQ_URL=amqp://guest:guest@localhost:5672/%2F  uv run pytest tests/contract/test_mq_contract.py -q
# storage 契约需先起 MinIO（当前镜像源不可用，见 06-risks §4）
TEST_S3_ENDPOINT=http://localhost:9000 TEST_S3_ACCESS_KEY=... TEST_S3_SECRET_KEY=... \
  uv run pytest tests/contract/test_storage_contract.py -q
```

## 3. 测试夹具设计（`tests/conftest.py`）

1. **先设环境变量再 import qqlab**：`qqlab.main` 在模块导入期就 `create_app()`，所以 `os.environ.update(...)` 必须在文件顶部执行（`# noqa: E402` 注释即为此）。
2. **零外部依赖**：sqlite 文件库（临时目录）+ `memory` 缓存 + `memory` 队列 + `local` 存储 + `AUTH_PROVIDER=mock`，`APP_ENV=test` 时自动关闭限流。
3. **session 级 `app`**：一个库、一个引擎，测试顺序执行（HTTP 层测试天然串行）。
4. **函数级 `client`**：每个用例新的 `TestClient`（cookie 隔离）。
5. **`other_org_client`**：同库、不同 `MOCK_ORG_ID/MOCK_USER_ID` 的第二套 app —— 这是「两个组织」的最小可信复现，跨租户断言靠它。
6. **`make_settings(**overrides)`**：构造任意 `Settings`，用于负向用例（生产校验、casdoor 快速失败等）。
7. 两个纯函数夹具：`login(client, profile)` 走 POST `/auth/mock/enter`，`csrf_headers(client)` 读 `qqlab_csrf` 造 `X-CSRF-Token`。

## 4. 关键断言（与验收项一一对应）

| 验收点 | 测试 |
|--------|------|
| 业务层不碰 SDK | `architecture/test_import_boundaries.py::test_business_does_not_import_adapters`、`::test_business_does_not_import_sdk`、`::test_forbidden_sdks_only_in_adapters`、`::test_api_does_not_import_qlib` |
| 地址全部来自环境变量 | `architecture/test_no_hardcoded_hosts.py::test_no_hardcoded_host_or_ip`、`::test_only_config_reads_environment` |
| 必填配置缺了就启动失败 | `architecture/test_no_hardcoded_hosts.py::test_settings_required_fields_have_no_defaults`、`unit/test_config.py` |
| 15 张业务表都有 `org_id` 且有索引 | `architecture/test_tenant_columns.py::test_business_table_has_org_id[projects…]` |
| `casdoor` 未实现 → 启动失败 | `unit/test_config.py::test_casdoor_not_implemented_fails_fast` |
| 生产禁止 mock / 弱密钥 / 非 Secure cookie | `unit/test_config.py` |
| 未登录 `/me` → 401 | `api/test_auth_flow.py::test_me_requires_auth` |
| 一键进入 302 + 种 cookie | `api/test_auth_flow.py::test_mock_enter_is_redirect_and_sets_cookies` |
| 登录后返回 `dev-user` / `dev-org` / 角色 | `api/test_auth_flow.py::test_login_then_me` |
| `viewer` 没有写权限 → 403 | `api/test_projects_and_isolation.py::test_viewer_cannot_write` |
| `researcher` 能建不能删 | `::test_researcher_can_create_but_not_delete` |
| 缺 CSRF 头的写请求 → 403 | `api/test_auth_flow.py::test_write_without_csrf_rejected` |
| 跨租户读/删统一 404 且原数据仍在 | `api/test_projects_and_isolation.py::test_cross_tenant_is_isolated` |
| 删除必须 `?confirm=true` | `::test_delete_requires_confirmation`、`api/test_admin_and_audit.py::test_remove_member_needs_confirmation` |
| 审计按 org 隔离、含 `request_id` | `api/test_admin_and_audit.py::test_audit_log_records_project_create`、`::test_audit_is_tenant_scoped` |
| 登出清会话、开放重定向被清洗 | `api/test_auth_flow.py::test_logout_clears_session`、`::test_open_redirect_is_neutralized` |
| 首个响应种 CSRF cookie（前端契约） | `api/test_health_and_legal.py::test_first_response_seeds_csrf_cookie` |
| 法务三件套含核心警示语 | `::test_legal_content_public_and_compliant`（`投资有风险` / `不构成`） |
| 迁移 17 表 + 种子 + 幂等 | `integration/test_alembic_migration.py` |

## 5. 阶段 2 实测结果

| 检查 | 命令 | 结果 |
|------|------|------|
| 后端测试 | `uv run pytest -q` | **141 passed**（2.0s） |
| 后端 lint | `uv run ruff check .` | **All checks passed!** |
| 后端格式 | `uv run ruff format --check .` | **93 files left unchanged** |
| 前端 lint | `pnpm lint` | ✅ |
| 前端类型 | `pnpm typecheck` | ✅ |
| 前端构建 | `pnpm build` | ✅ 7/7 静态页 |
| 模式 A compose | `docker compose config -q` | ✅ |
| 模式 B compose | `docker compose -f docker-compose.prod.yml config -q` | ✅ |
| 服务清单 | `docker compose config --services` | 默认 7 个服务；`--profile minio` +1、`--profile qlib` +2 |
| API 冒烟（TestClient） | 22 条路径全部可解析，`/health/ready` 全绿、`/me` 401、`/legal/*` 200 | ✅ |
| `docker compose up` 实跑 | — | ⏳ 本机 Docker daemon 未启动，留给你验收 |
| Playwright e2e | — | ⏳ 按计划推迟到阶段 6（偏差 D6） |

## 6. 已知测试盲区（阶段 3–6 补）

1. **真实 Postgres 差异**：JSONB、索引、唯一约束在 SQLite 上只是近似；契约层已把可切换的三组实现做了门控，但「跑在 Postgres 上的全量 API 测试」要等阶段 3 有 compose 环境后补。
2. **Qlib-Server 通路**：`ComputePort` 尚无实现，`worker` 只测了分发器逻辑（未知类型 nack、异常不终止消费者）。
3. **前端无 e2e**：`pnpm build` 只保证能编译；登录态、跨页跳转、CSRF 实际生效要靠阶段 6 的 Playwright。
4. **限流**：测试环境关闭（`APP_ENV=test`），只在 `unit/test_ratelimit.py` 单测令牌桶本身。
5. **并发与性能**：未做压测；`RateLimitMiddleware` 的固定窗口在跨窗口边界可瞬时放行两倍请求（已知取舍）。
