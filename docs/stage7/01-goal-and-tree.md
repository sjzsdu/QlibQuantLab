# 01 · 目标与任务树：Casdoor OIDC 接入 + 生产部署文档 + R6-2 收尾

## 1. 阶段目标

一句话：**把「可插拔认证」的 Casdoor 分支真正实装并全链路实测，补齐生产部署欠账（Traefik 长连接 R9、Redis 拆分 R11、Casdoor 部署指南），顺手关闭阶段 6 登记的必做项 R6-2（worker 孤儿任务回收）** ——
全程业务代码只依赖 `qqlab.ports`、SDK 只进适配器、API 进程依旧零 qlib；`AUTH_PROVIDER` 仍是唯一切换开关，前端只按 `/system/info` 自适应，不引任何 IdP SDK。

### 输入（阶段 6 遗留 + 评审计划）

| 来源 | 内容 |
|------|------|
| R6-2 | worker 崩溃留下孤儿 `running` 任务 → 阶段 7 必做（生产部署前必须项） |
| 阶段 1 设计 | `CasdoorAuthProvider` 骨架 + TODO（阶段 1 提交）；`/system/info.auth_provider` 已暴露（D7-10 零后端改动） |
| D7-10 | 登录页按 `auth_provider` 自适应：casdoor 时隐藏 mock profile 选择器 |
| R9 / R11 | Traefik 长连接超时、Qlib-Server 不支持 Redis 密码 —— 生产模式 B 的两个硬风险，阶段 7 出文档与清单 |
| 计划评审 3 点 | ①R6-2 单副本前提写明 + 阈值可配；②casdoor 镜像先探 manifest 再按 digest 拉；③memory 缓存 TTL 过期语义单测锁死 |

## 2. 决策记录

### 代码内引用编号（与源码注释/测试 docstring 一一对应）

| # | 决策 | 落点 |
|---|------|------|
| **D7-2** | 组织 claim 直通：`CASDOOR_ORG_ID_CLAIM=owner`（Casdoor JWT 内嵌 user struct 的 owner 字段即组织名）→ `org_id` 取原值，**零 Casdoor 侧配置**；`CASDOOR_ORG_MAP={}` 直通 | `config.py`、`test_config.py`、`.env.example` |
| **D7-3** | 角色 **fail-closed**：`ROLE_MAP` 映射后为空 → 401「账号未分配任何角色」；映射结果含平台未知角色 → 401 并提示配置 `ROLE_MAP`。绝不静默放行也不降级成默认角色 | `casdoor_provider._map_identity`、`test_casdoor_provider.py` |
| **D7-5** | **不引 Casdoor SDK**：`httpx` 换 token / JWKS + `pyjwt[crypto]` 自验 RS256（架构测试 `FORBIDDEN_SDKS` 禁 casdoor SDK；依赖只在 adapters 层） | `pyproject.toml`（`pyjwt[crypto]>=2.10,<3`）、`test_casdoor_provider.py` |
| **D7-7** | dev **双地址拓扑**：`CASDOOR_ISSUER`（浏览器可达，宿主映射端口 8001）与 `CASDOOR_INTERNAL_URL`（后端容器可达，compose 服务名 `http://casdoor:8000`）分设；**两者都进 iss 白名单** | `config.casdoor_issuers`、`docker-compose.casdoor-smoke.yml` |
| **D7-8** | `verify_token` 校验的仍是**平台自签 HS256 会话**，与 mock 完全一致 —— IdP 令牌只在回调用一次（阶段 1「IdP 令牌只留后端」承诺；前端零改动） | `casdoor_provider.verify_token`、`test_casdoor_provider.py` |
| **D7-10** | 登录页读 `/system/info.auth_provider` 自适应：`casdoor` 时隐藏 mock profile 选择器与一键进入文案 | `frontend/src/app/login/page.tsx` |

### 评审补充决策（无编号，实装时定）

1. **PKCE verifier 无状态派生**（偏离原「落 CacheProvider」草案）：`verifier = base64url(HMAC-SHA256(client_secret, "qqlab-pkce:" + state))`。三条理由写进 `casdoor_provider` 模块 docstring：`get_login_url` 是端口契约的**同步**方法（无法 await 缓存写入）；推导式天然跨 uvicorn 进程（生产 `BACKEND_WORKERS=4`，无共享状态要求）；攻击者截获回调 URL 的 `code+state` 也无法反推 verifier（不知 `client_secret`）。
2. **state 落缓存 TTL 600s**（`_STATE_TTL=600`）：`auth_service` 签发 state 时写 `redirect_to`，回调 `_consume_state` 一次性取用。
3. **JWKS 缓存 1h + 未知 kid 强刷**：`CacheProvider` 注入，key `qqlab:auth:jwks:{issuer}`；`_verify_id_token` 里未知 kid 先用缓存、再强制拉一次（密钥轮换不等缓存过期）。
4. **声明式种子（`deploy/casdoor/init_data.json`，casdoor 启动时幂等 create+update）**：原计划的 REST 种子脚本**未创建**（admin 初始密码为空、REST 建应用路径不通），改为文件声明、随容器启动自动应用（org/应用/角色/4 个 smoke 用户），见 05。
5. **logout 不带 `id_token_hint`（实测结论，契约不改）**：该镜像构建下，post-logout 落点已注册时带/不带 hint 都 302 → `get_logout_url` 维持同步签名与现有参数，不扩端口契约。实测回写见 05 §4（R7-2）。
6. **R6-2 阈值可配 + 单副本前提**：`WORKER_STALE_JOB_MINUTES=10`（env 可调）；回收逻辑带**单副本前提**注释 —— 多副本下「心跳 > 阈值」判据存在双执行风险（长训练 >10min 无检查点 + 另一 worker 重启回收 → 重复入队），当前架构 `QLIB_WORKER_CONCURRENCY=1` 且 worker 单副本，前提写入代码注释与 06-risks。
7. **失败登录审计 = 结构化日志而非审计表**：登录失败发生在身份解析前、无 org 归属；`DbAuditWriter` 本就「无 org 不落表」（跨租户隔离设计）。阶段 7 补强了跳过日志（`audit_skipped_no_org` 带 `action/detail/ip/request_id`），冒烟以日志断言验证；成功登录照常落 `audit_logs`（org 内可查）。

### 计划评审 3 点的落地

| 评审点 | 落地 |
|--------|------|
| ① R6-2 单副本前提 + 阈值可配 | `recover_stale_running_jobs` 函数头注释写明前提与多副本风险；`WORKER_STALE_JOB_MINUTES=10` 进 `config.py` 与 `.env.example`；`docs/stage6/06-risks.md` R6-2 状态回写 |
| ② casdoor 镜像先探 manifest 再 digest-pull | 双架构 digest 固化进 `deploy/casdoor/README.md` + manifest 探测命令；compose 锁 `platform: ${CASDOOR_PLATFORM:-linux/amd64}` |
| ③ memory TTL 过期语义单测锁死 | `test_ratelimit.py::test_memory_cache_ttl_expiry_semantics`（TTL 到期 get 返回 None 惰性删除）+ `test_memory_cache_ttl_zero_means_no_expiry`（与 Redis 适配器语义一致） |

## 3. 范围裁剪（本阶段不做）

- **不做 IdP 托管上线**：生产 Casdoor 只出部署指南与验证清单（05），不在本栈起生产 IdP。
- **不做 token 刷新 / 前端会话续期**：平台会话自己签发（D7-8），过期重登即可。
- **不改登录限流默认值**：`RATE_LIMIT_LOGIN_PER_MIN=5` 维持，冒烟/e2e 错峰执行（承接 R6-3）。
- **不做 Casdoor 侧主题/多语言/组织级登录方式定制**：种子只声明 `Password` 登录方式。
- **不动 `.env`**（阶段纪律）：冒烟用临时 compose 覆盖 `docker-compose.casdoor-smoke.yml`，跑完 `docker compose up -d backend` 即还原。

## 4. 文件树（阶段 7 增改）

```
backend/
  src/qqlab/
    adapters/auth/casdoor_provider.py   [改] OIDC 全量实装（PKCE/JWKS/claims/fail-closed/logout/healthcheck）
    api/v1/auth.py                      [改] error= 回调 401+审计+ip、logout 带落点、callback 注入 audit ctx
    services/auth_service.py            [改] handle_callback(ip=)、state TTL、ensure_org rename 守卫
    config.py                           [改] CASDOOR_* 校验补齐、_json_str_map、casdoor_issuers、WORKER_STALE_JOB_MINUTES
    container.py                        [改] CasdoorAuthProvider 装配（注入 CacheProvider）
    repositories/job.py                 [改] recover_stale_running_jobs（R6-2）
    worker/main.py                      [改] 消费前回收孤儿 running（R6-2，单副本前提）
    adapters/audit/db_audit_writer.py   [改] audit_skipped_no_org 日志补 action/detail/ip（安全信号）
    adapters/compute/{qlib,stub}_compute.py [改] gzip mtime=0 字节级确定性（冒烟揪出的 flake 根因）
  tests/unit/
    test_casdoor_provider.py            [新] 433 行：PKCE/JWKS 缓存/三形态 roles/fail-closed/logout/healthcheck
    test_identity_ensure_org.py         [新] ensure_org rename 守卫 3 例
    test_worker_recover.py              [新] R6-2 回收 6 例（requeue/耗尽 failed/阈值边界/不动 queued）
    test_ratelimit.py                   [改] 登录限流身份（session or IP）+ memory TTL 语义 2 例
    test_config.py                      [改] casdoor 启动校验 / map 解析 / owner 直通
  tests/api/test_auth_flow.py           [改] error= → 401、坏 state → 400/1005、logout 落点
  pyproject.toml                        [改] pyjwt[crypto]>=2.10,<3
  uv.lock                               [改] pyjwt[crypto]（cryptography 链）锁定
  Dockerfile                            [改] uv sync 加 RUN --mount cache（轮子跨构建续传，抗 PyPI 直连劣化）
deploy/casdoor/
  init_data.json                        [新] dev 声明式种子（org/app/role/user，幂等）
  README.md                             [新] 镜像 digest、manifest 探测、种子语义、故障排查
docker-compose.yml                      [改] casdoor 服务（profile casdoor、8001、healthcheck、种子挂载）
docker-compose.casdoor-smoke.yml        [新] 冒烟临时覆盖（AUTH_PROVIDER=casdoor env 块）
scripts/stage7_smoke.py                 [新] 阶段 7 实机冒烟 17 项（三轮错峰）
frontend/src/app/login/page.tsx         [改] D7-10 auth_provider 自适应
.env.example                            [改] CASDOOR 段重写（owner/双地址/map 语义）+ WORKER_STALE_JOB_MINUTES
docs/stage7/                            [新] 01–06 + README（本文档所在）
README.md                               [改] 进度行 7
scripts/README.md                       [改] 补 stage6/stage7 冒烟行
docs/stage1/{04,07,08}                  [改] 阶段 7 已落地指针 + R9/R11 状态
docs/stage6/06-risks.md                 [改] R6-2 → ✅ 已解决（保留单副本前提说明）
```
