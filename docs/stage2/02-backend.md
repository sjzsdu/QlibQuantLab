# 02 · 后端代码要点（阶段 2 交付的 `qqlab` 包）

> 完整代码见 `backend/src/qqlab/`（71 个 `.py`）。本文件只讲**设计落点与关键代码**，用来对照阶段 1 的 `04/05` 号文档。

## 1. 分层与依赖方向（被架构测试强制）

| 目录 | 允许 import | 禁止 |
|------|-------------|------|
| `ports/` | 标准库（第三方类型只能在 `if TYPE_CHECKING:` 下） | 任何 SDK、`qqlab.adapters` |
| `api/ services/ repositories/ models/ core/ schemas/` | `qqlab.ports` + 同层业务模块 | `redis` `pika` `aio_pika` `boto3` `socketio` `qlib` `casdoor` `qqlab.adapters` |
| `adapters/**` | 各自 SDK | `qqlab.api` `qqlab.services` |
| `container.py` | `adapters.*` + `ports.*` | — |
| `worker/qlib_env.py` | `qlib` / `pyqlib`（阶段 3） | — |

```python
# tests/architecture/test_import_boundaries.py —— 用 AST 扫描，跳过 TYPE_CHECKING 块
def test_ports_are_dependency_free() -> None:
    stdlib = set(sys.stdlib_module_names)
    offenders = [f"{_rel(p)} -> {m}" for p in _py_files(PORTS_PKG) for m in _imported_modules(p)
                 if m.split(".")[0] not in stdlib and m.split(".")[0] != "qqlab"]
    assert not offenders, "ports 只允许 import 标准库与 qqlab.ports:*\n" + "\n".join(offenders)
```

三个同族测试：`test_no_hardcoded_host_or_ip`（地址必须来自环境变量）、`test_only_config_reads_environment`（只有 `config.py` 能读 `os.environ`）、`test_business_table_has_org_id`（15 张业务表都要有 `org_id` 且被索引覆盖）。

## 2. 配置 `config.py`（62 个字段，6 个必填）

连接串类字段**没有默认值**，缺了就在启动时 `ValidationError`：

```python
required = {n for n, f in Settings.model_fields.items() if f.is_required()}
# {'DATABASE_URL', 'CACHE_URL', 'MQ_URL', 'APP_JWT_SECRET', 'CORS_ALLOW_ORIGINS', 'QLIB_SERVER_WS_URL'}
```

三档启动校验：

| 时机 | 规则 |
|------|------|
| 字段校验 | `APP_JWT_SECRET ≥ 16 字符`；`CORS_ALLOW_ORIGINS` 非空 |
| `APP_ENV=production` | 禁止 `AUTH_PROVIDER=mock`；`SESSION_COOKIE_SECURE=true`；`APP_JWT_SECRET` ≥32 且非占位符；`QLIB_SERVER_REDIS_HOST`/`QLIB_SERVER_QUEUE_HOST` 必填（Qlib-Server 硬依赖）；`STORAGE_BACKEND=s3|minio` 时 `STORAGE_S3_*` 必填 |
| 装配期 | `AUTH_PROVIDER=casdoor` 而 `CasdoorAuthProvider.IMPLEMENTED=False` → `ConfigError`（1008），**绝不静默降级成 mock** |

监听地址也走环境变量：`SERVER_HOST`（默认 `0.0.0.0`）/ `SERVER_PORT`（默认 8000），`qqlab-api` 入口读取后交给 uvicorn。

## 3. 装配根 `container.py`

```python
@classmethod
def build(cls, settings: Settings) -> Container:
    database = SQLAlchemyDatabaseProvider(settings.DATABASE_URL, backend=settings.DATABASE_BACKEND, ...)
    cache    = MemoryCacheProvider() if settings.CACHE_BACKEND == "memory" else RedisCacheProvider(settings.CACHE_URL, ...)
    queue    = MemoryMessageQueueProvider() if settings.MQ_BACKEND == "memory" else RabbitMQProvider(settings.MQ_URL, ...)
    storage  = LocalStorageProvider(...) if settings.STORAGE_BACKEND == "local" else S3StorageProvider(...)
    auth     = cls._build_auth(settings)      # casdoor 未实现 → ConfigError
    audit    = DbAuditWriter(database)
    return cls(settings, database=..., cache=..., queue=..., storage=..., auth=..., audit=...)
```

开关全部来自 `*_BACKEND` 与 `*_URL`，业务层看不到任何具体类。`Container.healthcheck()` 聚合 5 项 ping → `/health/ready`；`dispose()` 优雅关闭时释放 MQ/Cache/DB 连接（关闭异常用 `contextlib.suppress` 吞掉，不影响退出）。

## 4. 应用工厂、中间件与统一信封

```python
# 外 → 内
app.add_middleware(CSRFMiddleware, ...)          # 非安全方法校验 X-CSRF-Token
app.add_middleware(CsrfCookieMiddleware, ...)    # 每个响应播种 qqlab_csrf（非 HttpOnly）
app.add_middleware(RateLimitMiddleware, ...)     # 固定窗口，缓存故障时放行（可用性优先）
app.add_middleware(RequestContextMiddleware)     # request_id + 结构化访问日志
app.add_middleware(CORSMiddleware, ...)          # 白名单来自 CORS_ALLOW_ORIGINS
```

**响应信封**（成功与失败形状一致，前端只判断 `code === 0`）：

```json
{ "code": 0, "message": "ok", "data": { "user_id": "dev-user", "org_id": "dev-org", "roles": ["admin", "researcher"] },
  "request_id": "8dca3954f4d94550bf3978329f1c7dcb" }
```

`request_id` 同时进响应头 `X-Request-ID`、结构化日志与 `audit_logs.request_id`，三方可串联。

**错误码**（`core/errors.py`，全部由 `main.py` 的异常处理器转成信封）：

| code | 异常 | HTTP | 场景 |
|------|------|------|------|
| 0 | — | 2xx | 成功 |
| 1001 | `UnauthorizedError` | 401 | 未登录 / 会话过期（`/me` 未登录即此码） |
| 1002 | `ForbiddenError` | 403 | 权限不足、CSRF 校验失败 |
| 1003 | `NotFoundError` | 404 | 资源不存在 **或跨租户**（统一响应，防探测） |
| 1004 | `ConflictError` | 409 | 重名、重复成员 |
| 1005 | `ValidationAppError` | 400 | 业务校验失败（如非法角色） |
| 1006 | `RateLimitedError` | 429 | 触发限流 |
| 1007 | `ConfirmationRequiredError` | 400 | 高危操作缺 `confirm=true` |
| 1008 | `ConfigError` | 500 | 启动期配置错误 |
| 1009 | `DependencyUnavailableError` | 503 | 外部依赖不可用 |
| 1010 | `NotImplementedYetError` | 501 | 阶段未到的占位能力 |
| 1422 / 1500 | — | 422 / 500 | 请求体校验失败 / 未捕获异常 |

**CSRF 双提交**：有会话 cookie 的非安全方法必须带 `X-CSRF-Token`，值等于 `qqlab_csrf` cookie；`/api/v1/auth*`、`/api/v1/health*` 豁免（登录请求本身还没有会话）。`CsrfCookieMiddleware` 保证**每个响应**都种 cookie，前端首个写请求即可读到。

## 5. 认证与用户上下文

### 5.1 会话只认自己签发的 JWT

```python
# core/security.py
@dataclass(frozen=True, slots=True)
class SessionClaims:
    user_id: str; username: str; display_name: str | None; email: str | None
    org_id: str; org_name: str | None; roles: tuple[Role, ...]; provider: str; jti: str
```

- 签发/校验都在平台侧（HS256 + `APP_JWT_SECRET`），IdP 令牌只在后端留存 → 阶段 7 换 Casdoor 时**前端零改动**。
- `decode_session_token` 任何异常都返回 `None`（fail-closed）；**出现未知角色字符串 → 整个令牌作废**，避免旧会话静默丢权限后继续用。
- 独立测试覆盖：过期、错签名、未知角色、坏 roles 类型。

### 5.2 `MockAuthProvider`（阶段 1–6）

| profile | user_id | roles | 用途 |
|---------|---------|-------|------|
| `admin`（默认） | `dev-user` | admin + researcher | 一键进入的默认身份 |
| `researcher` | `dev-user-researcher` | researcher | 写权限但不能删/发布 |
| `viewer` | `dev-user-viewer` | viewer | 只读，验证 403 |
| `auditor` | `dev-user-auditor` | auditor | 审计只读 |

不同 profile 邮箱不同（`users.email` 唯一约束），外部 ID → UUID 主键走 `qqlab.core.ids.stable_uuid`，所以 `dev-user` 这类 mock 主键也能满足 `UUID` 外键。

登录入口（前端契约）：

| 方法 | 路径 | 行为 |
|------|------|------|
| GET | `/api/v1/auth/login?redirect_to=` | 返回 `{url, state}`，`url` 指向 mock 进入地址；开放重定向经 `safe_redirect` 清洗（外域一律回落 `/`） |
| GET | `/api/v1/auth/mock/enter?profile=&redirect_to=` | **302** 回 `redirect_to`，种下会话 cookie（前端一键进入用；`include_in_schema=False`） |
| POST | `/api/v1/auth/mock/enter` | 同上，JSON 返回（脚本/测试用，进 OpenAPI） |
| GET | `/api/v1/auth/logout` | 清 cookie，返回 `{redirect_to: "/login"}` |
| GET | `/api/v1/me` | 未登录 **401**；登录后返回 `CurrentUserOut` |
| GET | `/api/v1/me/permissions` | 当前角色展开的权限点列表 |

### 5.3 用户只能通过 DI 拿到

```python
async def get_current_user(user: CurrentUser | None = Depends(get_optional_user)) -> CurrentUser:
    """**唯一的用户入口**：控制器不得直接读 cookie。未登录 → 401。"""
    if user is None or not user.is_authenticated:
        raise UnauthorizedError("未登录或会话已过期，请重新登录")
    return user

def require_permission(permission: str):      # 路由上写权限点，不写角色
    async def _guard(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not has_permission(user.roles, permission):
            raise ForbiddenError(f"权限不足：需要 {permission}")
        return user
    return _guard
```

**权限矩阵**（`core/rbac.py`，35 个权限点）：读类全员；`project.write`/`train.submit`/`backtest.submit` 等给 admin+researcher；`project.delete`/`strategy.publish`/`admin.member`/`admin.config` 仅 admin；`audit.read`/`audit.export` 给 admin+auditor；`backtest.export` 给 admin+researcher+auditor。路由示例：`user=Depends(require_permission("admin.member"))`。

## 6. 租户隔离

1. `OrgScope(org_id, user_id, roles)` 由 `get_scope` 依赖生成，**唯一来源是会话**，前端传什么都没用。
2. `repositories/base.py` 的 `BaseRepo[T]` 所有查询强制拼 `where(org_id == scope.org_id)`，服务层无法绕过。
3. 读/改/删他租户资源 → `NotFoundError`（1003 / 404），与「确实不存在」同响应，避免探测存在性。
4. 架构测试逐表断言：15 张 `TENANT_MODELS` 都有非空 `org_id` 且被索引覆盖（`system_configs` 走 `(org_id, config_key)` 唯一约束首列，同样算覆盖）。
5. 审计与缓存 key 也带 org 前缀（`core/tenant.py`）。

## 7. API 清单（22 条路径，前缀 `/api/v1`）

| 方法 | 路径 | 依赖 |
|------|------|------|
| GET | `/health/live` `/health/ready` | 公开（`/ready` 聚合 5 项 ping） |
| GET | `/system/info` | 公开，返回 env/各 backend/`qlib_server_ws_url`/uptime（不含任何密钥） |
| GET | `/legal/meta` `/legal/{code}` | 公开，markdown 包数据 |
| GET | `/auth/login` `/auth/logout` `/auth/callback` | 公开 |
| GET/POST | `/auth/mock/enter` | 公开（开发用） |
| GET | `/me` `/me/permissions` | 登录 |
| GET | `/orgs/current` | 登录 |
| GET/POST | `/projects` | `project.read` / `project.write` |
| GET/PATCH/DELETE | `/projects/{project_id}` | `project.read` / `project.write` / `project.delete` + `?confirm=true` |
| GET | `/admin/members` POST `/admin/members` DELETE `/admin/members/{user_id}` PUT `.../roles` | `admin.member` |
| GET/PUT | `/admin/config` `/admin/config/{config_key}` | `admin.config` |
| GET | `/audit-logs` `/audit-logs/actions` | `audit.read` |

分页统一 `?page=&page_size=&keyword=` → `{items, total, page, page_size}`。

## 8. 数据模型与迁移

- **17 张表**：15 张业务表（`projects`、`project_members`、`data_sources`、`data_licenses`、`datasets`、`factors`、`models`、`training_runs`、`strategies`、`backtests`、`jobs`、`job_logs`、`audit_logs`、`system_configs`、`org_members`）+ 2 张身份表（`organizations`、`users`）。
- **`JSONType`（TypeDecorator）**：Postgres 落 `jsonb(none_as_null)`，其他方言落 `json` → 测试用 SQLite 与生产 Postgres 同一份模型（偏差 D5：角色用 JSON 列而非数组）。
- **`0001_initial.py`**：`Base.metadata.create_all` 一次建全，随后幂等写入种子（重复执行安全）：
  - `organizations`：`dev-org` / slug `dev` / Dev Organization
  - `users`：`dev-user` / username `dev`
  - `org_members`：dev → `["admin","researcher"]`
  - `system_configs`：`compliance.notice_shown`、`backtest.default_benchmark=SH000300`
- **alembic 全程 async**：`alembic/env.py` 从 `Settings` 拿 `DATABASE_URL` 起 async engine，**不再需要 `DATABASE_URL_SYNC`**（阶段 1 文档已同步修正）。
- 时间列统一 `TIMESTAMPTZ`（存 UTC），主键 `UUID`，命名约定集中在一个 `MetaData` 上，便于 autogenerate 稳定识别。

## 9. 审计

`AuditWriter` 是端口，实现是 `DbAuditWriter`（独立会话写入，主事务回滚不影响审计留痕）。`AuditAction` 枚举覆盖登录/登出/登录失败、项目 CRUD 与可见性变更、数据源与授权、因子/模型/策略发布、训练与回测提交导出、任务取消重试、管理配置与成员变更。

写入字段：`org_id`、`actor_user_id`、`actor_username`、`action`、`resource_type`、`resource_id`、`outcome`、`detail(jsonb)`、`ip`、`user_agent`、`request_id`、`created_at`。`GET /audit-logs` 支持按 action/资源/时间分页，**强制 org 过滤**；`GET /audit-logs/actions` 返回本组织实际出现过的 action（阶段 6 扩展导出）。

## 10. worker 骨架（阶段 3 接 qlib）

```python
DEFAULT_QUEUE = "qqlab_jobs"       # 应用自己的 vhost，不是 Qlib-Server 的 task_queue

class Worker:
    async def dispatch(self, message: Message) -> None:
        kind = json.loads(message.body)["kind"]
        handler = self._handlers.get(kind) or await message.nack(requeue=False) ...
        try:
            result = await handler(payload)
        except ValidationAppError:      # 任务参数不合法 → 不重投
            await message.nack(requeue=False)
        except Exception:               # 单条任务失败不终止消费者
            logger.exception("job_failed", ...); await message.nack(requeue=False)
        else:
            await message.ack()
```

`build_worker()` 目前只装配容器、不注册 handler；阶段 3 起在 `main()` 里 `worker.register(JobKind.DATASET_IMPORT, ...)`。`worker/qlib_env.py` 是**全仓唯一允许 import qlib 的文件**（阶段 3 补齐），API 进程永远不碰 qlib —— 训练/回测跑在独立 worker 容器里，通过 WebSocket 客户端连 Qlib-Server。
