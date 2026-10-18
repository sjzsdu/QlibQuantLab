"""应用配置：全部外部依赖地址与开关集中于此，只从环境变量读取。

设计约束（见 docs/stage1/05-ports-adapters.md）：
- 连接串类字段**没有默认值**，必须由环境变量注入 → 没配置就在启动时失败，而不是静默连到错误地址。
- 业务代码不得直接读 ``os.environ``，只能通过 ``Settings``。
"""

from __future__ import annotations

from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BackendName = Literal["postgres", "sqlite"]
CacheName = Literal["redis", "valkey", "dragonfly", "memory"]
MqName = Literal["rabbitmq", "memory"]
StorageName = Literal["s3", "minio", "local"]
AuthName = Literal["mock", "casdoor"]

_DEV_JWT_PLACEHOLDER = "dev-only-not-secret-change-me-0123456789abcdef"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ 运行
    APP_ENV: Literal["development", "production", "test"] = "development"
    LOG_LEVEL: str = "INFO"
    IS_WORKER: bool = False
    #: 监听地址（容器内 0.0.0.0；改端口只改环境变量）
    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = 8000

    # ------------------------------------------------------- 数据库（必须注入）
    DATABASE_BACKEND: BackendName = "postgres"
    DATABASE_URL: str  # 例：postgresql+asyncpg://user:pass@host:5432/db
    DATABASE_POOL_SIZE: int = 10
    DATABASE_ECHO: bool = False

    # --------------------------------------------------------- 缓存（必须注入）
    CACHE_BACKEND: CacheName = "redis"
    CACHE_URL: str  # 例：redis://host:6379/5

    # ----------------------------------------------------- 消息队列（必须注入）
    MQ_BACKEND: MqName = "rabbitmq"
    MQ_URL: str  # 例：amqp://user:pass@host:5672/%2Fqqlab
    MQ_PREFETCH: int = 1

    # ------------------------------------------------------ 对象存储
    STORAGE_BACKEND: StorageName = "local"
    STORAGE_S3_ENDPOINT: str = ""
    STORAGE_S3_BUCKET: str = "qqlab"
    STORAGE_S3_ACCESS_KEY: str = ""
    STORAGE_S3_SECRET_KEY: str = ""
    STORAGE_S3_PATH_STYLE: bool = True
    STORAGE_LOCAL_ROOT: str = "./data/objects"

    # ------------------------------------------------------ 认证（必须注入）
    AUTH_PROVIDER: AuthName = "mock"
    APP_JWT_SECRET: str  # 生产必须 >=32 字节随机值
    APP_JWT_TTL_SECONDS: int = 28800
    SESSION_COOKIE_NAME: str = "qqlab_session"
    SESSION_COOKIE_SECURE: bool = False
    CSRF_COOKIE_NAME: str = "qqlab_csrf"
    CORS_ALLOW_ORIGINS: str  # 逗号分隔

    # MockAuthProvider 参数
    MOCK_USER_ID: str = "dev-user"
    MOCK_USER_USERNAME: str = "dev"
    MOCK_USER_DISPLAY_NAME: str = "Dev User"
    MOCK_USER_EMAIL: str = "dev@qlibquantlab.local"
    MOCK_ORG_ID: str = "dev-org"
    MOCK_ORG_SLUG: str = "dev"
    MOCK_ORG_NAME: str = "Dev Organization"
    MOCK_USER_ROLES: str = "admin,researcher"

    # Casdoor（阶段 7 实装；AUTH_PROVIDER=casdoor 时 CASDOOR_* 必填，启动校验）
    #: OIDC issuer（浏览器可达地址，用于 authorize/logout 跳转与 iss 校验白名单①）
    CASDOOR_ISSUER: str = ""
    #: 服务端可达地址（dev 下浏览器走宿主机映射端口、容器走 compose 服务名时拆分；
    #: 生产留空 = 与 ISSUER 相同。token/discovery/JWKS 走此地址，进 iss 白名单②）
    CASDOOR_INTERNAL_URL: str = ""
    CASDOOR_CLIENT_ID: str = ""
    CASDOOR_CLIENT_SECRET: str = ""
    CASDOOR_REDIRECT_URI: str = ""
    CASDOOR_SCOPES: str = "openid profile email"
    #: Casdoor JWT 内嵌 user struct 的角色/组织字段名（默认格式零配置即可用）
    CASDOOR_ROLE_CLAIM: str = "roles"
    CASDOOR_ORG_ID_CLAIM: str = "owner"
    #: JSON 映射：Casdoor 角色名 → 平台角色（未知角色 fail-closed 拒绝登录）
    CASDOOR_ROLE_MAP: str = "{}"
    #: JSON 映射：Casdoor 组织名 → 平台 org_id（缺省直通 claim 原值）
    CASDOOR_ORG_MAP: str = "{}"

    # ------------------------------------------------------ Qlib 计算（worker）
    #: 计算后端：qlib（真数据，经 Qlib-Server）| stub（合成数据对照，零依赖）
    COMPUTE_BACKEND: str = "stub"
    QLIB_SERVER_WS_URL: str  # 例：ws://qlib-server:9710
    QLIB_DATA_ROOT: str = "/qlib_data"
    #: 每个 org 的数据子目录名（bootstrap 与 Qlib-Server 的 QLIB_DATA 保持一致）
    QLIB_DATA_SUBDIR: str = "cn_data"
    #: 标的截断开关（决策 #2）：0 = 全量；>0 = 导入/回测只取前 N 个标的（首次 smoke 用小集合）
    QLIB_DATA_SYMBOLS: int = 0
    QLIB_EXPERIMENT_ROOT: str = "/experiments"
    QLIB_REGION: str = "cn"
    QLIB_WORKER_CONCURRENCY: int = 1
    QLIB_INIT_TIMEOUT_SECONDS: int = 60
    #: R6-2：worker 启动时回收孤儿 running 任务的心跳阈值（分钟）。
    #: **单副本前提**（dev/prod compose 的 worker 均为单服务无 replicas）：
    #: 扩多副本前必须先改为「locked_by 存活消费者校验」，否则长任务可能双执行。
    WORKER_STALE_JOB_MINUTES: int = 10

    # Qlib-Server 自身的硬依赖（不可省略，见 README「Qlib-Server 硬依赖」）
    QLIB_SERVER_REDIS_HOST: str = ""
    QLIB_SERVER_REDIS_PORT: int = 6379
    QLIB_SERVER_REDIS_DB: int = 0
    QLIB_SERVER_QUEUE_HOST: str = ""
    QLIB_SERVER_QUEUE_PORT: int = 5672
    QLIB_SERVER_QUEUE_USER: str = ""
    QLIB_SERVER_QUEUE_PASS: str = ""
    QLIB_SERVER_TASK_QUEUE: str = "task_queue"
    QLIB_SERVER_MESSAGE_QUEUE: str = "message_queue"

    # --------------------------------------------------------- 限流 / 审计
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_LOGIN_PER_MIN: int = 5
    RATE_LIMIT_WRITE_PER_MIN: int = 120
    RATE_LIMIT_READ_PER_MIN: int = 600
    AUDIT_RETENTION_DAYS: int = 365

    # ------------------------------------------------------------ 校验
    @field_validator("APP_JWT_SECRET")
    @classmethod
    def _secret_not_placeholder(cls, v: str) -> str:
        if v == _DEV_JWT_PLACEHOLDER:
            # 开发可用，生产在 model_validator 里拒绝
            return v
        if len(v) < 16:
            raise ValueError("APP_JWT_SECRET 至少 16 个字符")
        return v

    @field_validator("CORS_ALLOW_ORIGINS")
    @classmethod
    def _cors_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("CORS_ALLOW_ORIGINS 不能为空（逗号分隔的 Origin 列表）")
        return v

    @field_validator("DATABASE_URL", "CACHE_URL", "MQ_URL", "QLIB_SERVER_WS_URL")
    @classmethod
    def _required_url(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("外部依赖地址必须通过环境变量注入，不能为空")
        return v.strip()

    @field_validator("COMPUTE_BACKEND")
    @classmethod
    def _compute_backend(cls, v: str) -> str:
        if v not in ("qlib", "stub"):
            raise ValueError(f"COMPUTE_BACKEND 必须是 qlib | stub，收到 {v!r}")
        return v

    @field_validator("CASDOOR_ROLE_MAP", "CASDOOR_ORG_MAP")
    @classmethod
    def _json_str_map(cls, v: str) -> str:
        """两个映射必须是 JSON 对象（str → str）——启动即报错，不等登录时炸。"""
        import json

        try:
            data = json.loads(v or "{}")
        except ValueError as exc:
            raise ValueError(f"必须是合法 JSON 对象，收到 {v!r}") from exc
        if not isinstance(data, dict) or not all(
            isinstance(k, str) and isinstance(val, str) for k, val in data.items()
        ):
            raise ValueError(f"必须是 {str!r} → {str!r} 形式的 JSON 对象，收到 {v!r}")
        return v

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        if self.APP_ENV == "production":
            if self.AUTH_PROVIDER == "mock":
                raise ValueError(
                    "生产环境禁止使用 AUTH_PROVIDER=mock；请配置 CASDOOR_* 并设置 AUTH_PROVIDER=casdoor"
                )
            if not self.SESSION_COOKIE_SECURE:
                raise ValueError("生产环境必须设置 SESSION_COOKIE_SECURE=true")
            if self.APP_JWT_SECRET == _DEV_JWT_PLACEHOLDER or len(self.APP_JWT_SECRET) < 32:
                raise ValueError("生产环境 APP_JWT_SECRET 必须是 >=32 字节的随机值")
            if not self.QLIB_SERVER_REDIS_HOST or not self.QLIB_SERVER_QUEUE_HOST:
                raise ValueError(
                    "Qlib-Server 强依赖 Redis 与 RabbitMQ，QLIB_SERVER_REDIS_HOST / "
                    "QLIB_SERVER_QUEUE_HOST 必须配置（无法通过接口替换）"
                )
        if self.AUTH_PROVIDER == "casdoor":
            # 生产与开发都要求：切到 casdoor 就必须给全 OIDC 四要素（启动即失败，
            # 绝不带着空 issuer 起来后在第一个登录请求才炸）
            missing = [
                name
                for name in ("CASDOOR_ISSUER", "CASDOOR_CLIENT_ID", "CASDOOR_CLIENT_SECRET", "CASDOOR_REDIRECT_URI")
                if not getattr(self, name).strip()
            ]
            if missing:
                raise ValueError(f"AUTH_PROVIDER=casdoor 但缺少必填配置：{', '.join(missing)}")
        if self.STORAGE_BACKEND in ("s3", "minio") and (
            not self.STORAGE_S3_ENDPOINT or not self.STORAGE_S3_ACCESS_KEY
        ):
            raise ValueError(f"STORAGE_BACKEND={self.STORAGE_BACKEND} 需要 STORAGE_S3_* 配置")
        return self

    # ------------------------------------------------------------ 派生属性
    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ALLOW_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def casdoor_role_map(self) -> dict[str, str]:
        import json

        return json.loads(self.CASDOOR_ROLE_MAP or "{}")

    @property
    def casdoor_org_map(self) -> dict[str, str]:
        import json

        return json.loads(self.CASDOOR_ORG_MAP or "{}")

    @property
    def casdoor_issuers(self) -> tuple[str, ...]:
        """iss 校验白名单：浏览器侧 issuer 与服务端侧地址（Casdoor 的 iss 按请求
        Host 派生，dev 拆分双地址时两者都可能出现在 id_token 里 —— casdoor#1622）。"""
        out = [self.CASDOOR_ISSUER.rstrip("/")]
        internal = self.CASDOOR_INTERNAL_URL.strip().rstrip("/")
        if internal and internal not in out:
            out.append(internal)
        return tuple(out)

    @property
    def qlib_ws_host_port(self) -> tuple[str, int]:
        """把 ws://host:port 拆成 qlib client 需要的 flask_server / flask_port。"""
        raw = self.QLIB_SERVER_WS_URL.strip()
        for scheme in ("ws://", "wss://", "http://", "https://"):
            if raw.startswith(scheme):
                raw = raw[len(scheme) :]
                break
        host, sep, port = raw.partition(":")
        if sep and port.isdigit():
            return host, int(port)
        return host, 9710


def load_settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]
