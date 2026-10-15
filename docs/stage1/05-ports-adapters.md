# 05 · 可插拔接口设计（Ports & Adapters）

## 1. 三条铁律

1. `qqlab/ports/` 里只有 `Protocol` / 抽象类 / 纯数据类型，**不 import 任何第三方 SDK**。
2. `qqlab/adapters/` 是**唯一**允许出现 `redis`、`aio_pika`、`boto3`、`minio`、`sqlalchemy` 驱动、`casdoor` SDK 的地方。
3. `qqlab/container.py` 是**唯一**允许同时 import `ports` 和 `adapters` 的地方，按环境变量装配 —— 业务代码拿到的永远是 Port。

违例由 L1 架构测试（`tests/architecture/test_import_boundaries.py`）在 CI 拦截。

## 2. 五个 Port 的接口签名

### 2.1 DatabaseProvider

```python
# qqlab/ports/database.py
from typing import AsyncIterator, Protocol
from contextlib import asynccontextmanager

class DatabaseProvider(Protocol):
    name: str  # "postgres" | "sqlite"

    @asynccontextmanager
    async def session(self) -> AsyncIterator["AsyncSession"]:
        """带事务的会话：正常退出 commit，异常回滚。"""

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """嵌套/批量写场景的显式事务边界。"""

    async def ping(self) -> bool: ...
    async def dispose(self) -> None: ...
```

- 实现：`adapters/database/postgres.py`（`create_async_engine` + `asyncpg` + SQLAlchemy 2.0 `AsyncSession`）。
- `DATABASE_BACKEND=postgres|sqlite`：sqlite 只用于单测与本地兜底，**正式支持只有 postgres**。

### 2.2 CacheProvider（含分布式锁）

```python
# qqlab/ports/cache.py
from contextlib import asynccontextmanager
from typing import AsyncIterator, Protocol

class Lock(Protocol):
    async def reentrant_acquire(self) -> None: ...   # 续租
    async def release(self) -> None: ...

class CacheProvider(Protocol):
    name: str  # "redis" | "valkey" | "dragonfly" | "memory"

    async def get(self, key: str) -> bytes | None: ...
    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def incr(self, key: str, ttl: int | None = None) -> int: ...

    @asynccontextmanager
    async def lock(self, key: str, *, ttl: int, blocking_timeout: float = 0.0
                   ) -> AsyncIterator[Lock]:
        """分布式锁：拿不到锁抛 LockNotAcquired。"""
```

- `CACHE_BACKEND=redis|valkey|dragonfly`：三者协议兼容，**同一个 adapter 文件**，只是连接串与 `name` 不同（按题目要求保留三个取值）。
- `memory` 实现用于单测（进程内 dict + asyncio.Lock）。
- 用途：限流令牌桶、PKCE state、JWT 吊销表、任务锁、**数据请求去重**、结果缓存。

### 2.3 MessageQueueProvider

```python
# qqlab/ports/message_queue.py
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol

@dataclass(frozen=True, slots=True)
class Message:
    body: bytes
    routing_key: str
    headers: dict[str, str]
    redelivered: bool
    def ack(self) -> Awaitable[None]: ...
    def nack(self, requeue: bool = False) -> Awaitable[None]: ...

class MessageQueueProvider(Protocol):
    name: str  # "rabbitmq" | "memory"

    async def publish(self, routing_key: str, body: bytes,
                      *, headers: dict[str, str] | None = None,
                      persistent: bool = True) -> None: ...

    async def consume(
        self,
        queue: str,
        handler: Callable[[Message], Awaitable[None]],
        *,
        prefetch: int = 1,
        concurrency: int = 1,
    ) -> None:
        """阻塞式消费循环；handler 抛异常则 nack(requeue=False) 并计数。"""

    async def declare(self, queue: str, *, durable: bool = True) -> None: ...
    async def ping(self) -> bool: ...
```

- `MQ_BACKEND=rabbitmq|memory`（memory 用于单测；未来可加 `nats`/`redis-streams` 而不动业务代码）。
- 应用队列：vhost `/qqlab`，`jobs.{kind}` 三条工作队列（`jobs.import`、`jobs.compute`、`jobs.heavy`），`x-dead-letter` 死信队列。
- **注意**：qlib-server 自己的 `task_queue`/`message_queue` 走 vhost `/`，由它自己管理，**不经过本 Port**（它有自己的 pika 实现，属于「Qlib 硬依赖例外」）。

### 2.4 StorageProvider

```python
# qqlab/ports/storage.py
from dataclasses import dataclass
from typing import BinaryIO, Protocol

@dataclass(frozen=True, slots=True)
class ObjectStat:
    size: int
    content_type: str | None
    etag: str | None

class StorageProvider(Protocol):
    name: str  # "s3" | "minio" | "local"

    async def put(self, key: str, data: bytes | BinaryIO, *,
                  content_type: str | None = None) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def stat(self, key: str) -> ObjectStat: ...
    async def list(self, prefix: str) -> list[str]: ...
    async def delete(self, key: str) -> None: ...
    async def presign_get(self, key: str, expires: int = 600) -> str: ...
```

- `STORAGE_BACKEND=s3|minio|local`：`s3` 与 `minio` 共用 S3 协议实现（`endpoint`/`path_style` 不同），`local` 落 `./data/objects`。
- 所有 key 由 `core/tenant.py` 加 `{org_id}/` 前缀，业务代码只传相对 key。

### 2.5 AuthProvider

见 [04-api-and-auth.md §2](./04-api-and-auth.md)。额外强调：**后端不直接读 Casdoor/JWT 库**，全部经 `AuthProvider.verify_token`。

### 2.6 AuditWriter（第 6 个 Port，合规必需）

```python
# qqlab/ports/audit.py
from typing import Protocol

class AuditWriter(Protocol):
    async def record(
        self, *,
        action: str,                 # backtest.submit 等枚举
        resource_type: str,
        resource_id: str | None,
        outcome: str = "success",    # success | failure | denied
        detail: dict | None = None,
        user: "CurrentUser",
        request_id: str | None = None,
        ip: str | None = None,
    ) -> None: ...
```

- 实现 `adapters/audit/db_audit_writer.py` 写 `audit_logs`；失败**不能影响主流程**，但要打 ERROR 日志。
- 路由层用 FastAPI 依赖 + 中间件自动记录 `auth.*` 与写操作，业务服务在关键分支显式记录。

### 2.7 ComputePort（worker 侧，阶段 3 落地）

```python
# qqlab/ports/compute.py
from typing import Protocol

class ComputePort(Protocol):
    """训练/回测/因子计算的能力抽象。backend 进程只通过 jobs 间接使用它。"""
    async def run_backtest(self, spec: "BacktestSpec", progress: "ProgressSink") -> "BacktestResult": ...
    async def run_training(self, spec: "TrainingSpec", progress: "ProgressSink") -> "TrainingResult": ...
    async def compute_factor(self, spec: "FactorSpec", progress: "ProgressSink") -> "FactorResult": ...
```

- 实现 `adapters/compute/qlib_compute.py`：**只有 worker 进程**会实例化它，`import qlib` 只出现在 `worker/qlib_env.py`。
- 第二实现（阶段 3 备选）：`local_stub_compute.py`，用合成数据跑通任务状态机，用于在 qlib-server 未就绪时先验收阶段 5 前端。

## 3. 装配：`container.py`（唯一接线处）

```python
# 伪代码，展示装配逻辑
class Container:
    def __init__(self, settings: Settings):
        self.cache: CacheProvider      = build_cache(settings)         # CACHE_BACKEND
        self.db: DatabaseProvider      = build_database(settings)      # DATABASE_BACKEND
        self.mq: MessageQueueProvider  = build_mq(settings)            # MQ_BACKEND
        self.storage: StorageProvider  = build_storage(settings)       # STORAGE_BACKEND
        self.auth: AuthProvider        = build_auth(settings)          # AUTH_PROVIDER
        self.audit: AuditWriter        = build_audit(settings)
        self.compute: ComputePort | None = build_compute(settings) if settings.is_worker else None
```

- FastAPI 用 `app.state.container` 提供依赖；worker 进程自己 new 一个 `Container`。
- **未知取值直接启动失败**（`ValueError`），避免静默降级到错误实现。

## 4. 环境变量矩阵

### 4.1 后端/应用层（全部由 `.env` 注入，代码零硬编码）

```bash
# ---------- 运行模式 ----------
APP_ENV=development                 # development | production | test
LOG_LEVEL=INFO

# ---------- 数据库 ----------
DATABASE_BACKEND=postgres           # postgres | sqlite(仅测试)
DATABASE_URL=postgresql+asyncpg://qqlab:qqlab-dev@postgres:5432/qqlab   # alembic 与应用共用（async engine，无需同步 URL）
DATABASE_POOL_SIZE=10
DATABASE_ECHO=false

# ---------- 缓存 ----------
CACHE_BACKEND=redis                 # redis | valkey | dragonfly | memory
CACHE_URL=redis://:qqlab-dev@redis:6379/5

# ---------- 消息队列 ----------
MQ_BACKEND=rabbitmq                 # rabbitmq | memory
MQ_URL=amqp://qqlab:qqlab-dev@rabbitmq:5672/%2Fqqlab
MQ_PREFETCH=1

# ---------- 对象存储 ----------
STORAGE_BACKEND=minio               # s3 | minio | local
STORAGE_S3_ENDPOINT=http://minio:9000
STORAGE_S3_BUCKET=qqlab
STORAGE_S3_ACCESS_KEY=qqlab
STORAGE_S3_SECRET_KEY=qqlab-dev-secret
STORAGE_S3_PATH_STYLE=true
STORAGE_LOCAL_ROOT=/data/objects

# ---------- 认证 ----------
AUTH_PROVIDER=mock                  # mock | casdoor
APP_JWT_SECRET=change-me-in-prod
APP_JWT_TTL_SECONDS=28800
SESSION_COOKIE_NAME=qqlab_session
SESSION_COOKIE_SECURE=false         # 生产 true
CORS_ALLOW_ORIGINS=http://localhost:3000
MOCK_USER_ROLES=admin,researcher
MOCK_USER_ID=dev-user
MOCK_ORG_ID=dev-org

# ---------- Casdoor（阶段 7 才填；阶段 1-6 留空） ----------
CASDOOR_ISSUER=
CASDOOR_CLIENT_ID=
CASDOOR_CLIENT_SECRET=
CASDOOR_REDIRECT_URI=http://localhost:3000/api/v1/auth/callback
CASDOOR_SCOPES=openid profile email
CASDOOR_ROLE_CLAIM=roles
CASDOOR_ORG_ID_CLAIM=x-org-id
CASDOOR_ROLE_MAP={"admin":"admin","researcher":"researcher"}

# ---------- Qlib 计算（worker） ----------
QLIB_SERVER_WS_URL=ws://qlib-server:9710      # WebSocket 地址，环境变量注入
QLIB_DATA_ROOT=/qlib_data
QLIB_EXPERIMENT_ROOT=/experiments
QLIB_WORKER_CONCURRENCY=2
QLIB_INIT_TIMEOUT_SECONDS=60

# ---------- Qlib-Server 自身的硬依赖（模式 B 指向用户已有实例） ----------
QLIB_SERVER_REDIS_HOST=redis
QLIB_SERVER_REDIS_PORT=6379
QLIB_SERVER_REDIS_DB=0
QLIB_SERVER_QUEUE_HOST=rabbitmq
QLIB_SERVER_QUEUE_PORT=5672        # 注意：qlib-server 源码里 pika 不传 port，实际固定 5672
QLIB_SERVER_QUEUE_USER=qqlab
QLIB_SERVER_QUEUE_PASS=qqlab-dev-secret
QLIB_SERVER_TASK_QUEUE=task_queue
QLIB_SERVER_MESSAGE_QUEUE=message_queue
# ⚠ Qlib-Server 的 Redis 连接不支持密码（无 password 参数），共用实例时必须免密

# ---------- 限流 / 安全 ----------
RATE_LIMIT_LOGIN_PER_MIN=5
RATE_LIMIT_WRITE_PER_MIN=120
RATE_LIMIT_READ_PER_MIN=600
AUDIT_RETENTION_DAYS=365
```

### 4.2 前端

```bash
NEXT_PUBLIC_API_BASE=/api           # 永远是相对路径，无主机名
NEXT_PUBLIC_APP_NAME=QlibQuantLab
NEXT_PUBLIC_ENV=development
# 服务端（容器内）转发目标，仅 compose 使用，不进浏览器
BACKEND_INTERNAL_URL=http://backend:8000
```

### 4.3 模式 B 追加字段（`# --- prod ---` 段）

```bash
# Traefik / 域名
TRAEFIK_HOST_API=api.example.com
TRAEFIK_HOST_WEB=app.example.com
TRAEFIK_HOST_QLIB=qlib.example.com
TRAEFIK_CERT_RESOLVER=letsencrypt
EXTERNAL_TRAEFIK_NETWORK=traefik-net
# 生产必须
SESSION_COOKIE_SECURE=true
CORS_ALLOW_ORIGINS=https://app.example.com
APP_JWT_SECRET=<必填，32+ 随机字节>
```

## 5. 「Qlib 硬依赖例外」的边界声明

| 组件 | 是否走 Port | 说明 |
|------|-------------|------|
| 应用缓存/锁 | ✅ `CacheProvider` | 可换 redis/valkey/dragonfly |
| 应用任务队列 | ✅ `MessageQueueProvider` | 可换 rabbitmq/memory |
| 应用对象存储 | ✅ `StorageProvider` | s3/minio/local |
| 应用数据库 | ✅ `DatabaseProvider` | postgres/sqlite |
| 应用认证 | ✅ `AuthProvider` | mock/casdoor |
| **qlib-server 内部的 Redis** | ❌ 它自己的实现 | 官方设计，用于 session-id 去重 + `python-redis-lock`，**不可替换** |
| **qlib-server 内部的 RabbitMQ** | ❌ 它自己的 pika | `task_queue`/`message_queue` 数据任务分发，**不可替换** |

两者可以与应用共用实例（开发期默认共用），也可以通过 `QLIB_SERVER_REDIS_*` / `QLIB_SERVER_QUEUE_*` 指向独立实例 —— 但**永远不能为 0**。README 与 `/api/v1/system/info` 会显式提示这一点。
