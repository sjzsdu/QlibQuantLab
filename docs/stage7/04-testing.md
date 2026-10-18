# 04 · 测试与实机记录

## 1. 测试基线

**401 → 444 passed + 1 skipped（+43），ruff 全绿；三连跑稳定。**

| 套件 | 基线（阶段 6） | 阶段 7 | 增量来源 |
|------|----------------|--------|----------|
| 后端 pytest | 401 passed, 1 skipped | **444 passed, 1 skipped** ×3 连跑 | casdoor 26 + ensure_org 3 + worker_recover 6 + config/ratelimit/auth_flow 扩展 + … |
| ruff `src tests` | 全绿 | 全绿 | — |
| 前端 lint / tsc / build | 全绿 | **全绿**（`pnpm lint`、`tsc --noEmit` exit 0、`next build` exit 0） | D7-10 登录页 |
| stage6 smoke | 34/34 | **34/34**（复跑） | — |
| stage7 smoke | — | **17/17** | 新增 `scripts/stage7_smoke.py` |
| Playwright e2e | 11/11 | **11/11**（复跑） | — |
| prod compose | — | **config 通过 + build 通过** | 见 §4 |

### 新增/扩展测试（全部 `uv run --extra dev pytest` 可复跑）

| 文件 | 体量 | 覆盖 |
|------|------|------|
| `tests/unit/test_casdoor_provider.py` | 433 行（新） | PKCE 推导稳定性/挑战值；token 兑换失败分支（网络→503 语义 / 非 200→401）；JWKS 缓存（1h TTL 只拉一次）+ 未知 kid 强刷；RS256 验签 exp/aud/iss；roles 三形态归一（str / str-list / **Role 对象数组**）；fail-closed 空角色与未知角色（D7-3）；owner 直通（D7-2）；logout URL 形态与落点绝对化；healthcheck |
| `tests/unit/test_identity_ensure_org.py` | 68 行（新） | ensure_org rename 守卫 3 例：`org_name is None` 才允许补名；带 org_name 的用户绝不重命名既有组织（02 §2.5） |
| `tests/unit/test_worker_recover.py` | 157 行（新） | R6-2 六例：stale→requeue、attempts 耗尽→failed、阈值边界（刚到/未到不动）、queued/succeeded 不受影响 |
| `tests/unit/test_ratelimit.py` | 扩展 | 登录限流身份：有效会话走 `user:<id>` 桶、无效 cookie 回落 IP 桶；**评审点③**：memory 缓存 TTL 到期 get 返回 None（惰性删除）+ `ttl=0` 永不过期（与 Redis 适配器语义一致） |
| `tests/unit/test_config.py` | 扩展 | `AUTH_PROVIDER=casdoor` 缺四要素启动 ValueError；`_json_str_map` 空串/非对象报错、`{}` 合法；`casdoor_issuers` 双白名单去重；owner 直通默认值 |
| `tests/api/test_auth_flow.py` | 扩展 | 回调 `error=access_denied` → 401/1001；坏 state → 400/1005；logout 返回落点 + Cookie 清除 |

## 2. stage7 冒烟（`scripts/stage7_smoke.py` → **17/17**）

对**实跑栈**（backend `AUTH_PROVIDER=casdoor` + casdoor 容器 + 种子用户）的黑盒验证。
设计要点：三轮结构 + 60s 错峰（登录限流 5/min/IP，每轮 4 命中）；手工 Cookie 管理 + 禁跟随跳转（读 302 Location/Set-Cookie）；
写请求自动带 `X-CSRF-Token` 双提交；「模拟浏览器」= idp `/api/login type=login`（拿会话）→ `type=code`（拿授权码 + PKCE 参数）。

| 轮 | 检查 |
|----|------|
| 1 · admin/viewer 成功链路 | authorize URL 含 PKCE S256 + state；回调 302 → 站内相对落点 + session/csrf 双 Cookie；`/me` provider=casdoor、org=qqlab（owner 直通）、roles 正确（**RS256/JWKS 验签通过**）；`/system/info auth_provider=casdoor`（D7-10 显隐依据）；business API 会话有效（读项目 200）；审计 `auth.login` 落表；viewer 写项目 → **403/1002 RBAC** |
| 2 · fail-closed | 无角色账号 → 401「账号未分配任何角色」；平台未知角色 `operator` → 401「角色未授权……ROLE_MAP」 |
| 3 · 错误与登出 | 回调 `error=access_denied` → 401/1001；失败登录安全事件进结构化日志（`audit_skipped_no_org` + `auth.login_failed`，02 §4）；坏 state → 400/1005；logout 返回 Casdoor RP-initiated URL + 平台 Cookie 清除；Casdoor 登出 302 → `http://localhost:3000/login?logged_out=1&next=...` |

执行方式（可复现）：

```bash
docker compose --profile casdoor up -d casdoor
docker compose -f docker-compose.yml -f docker-compose.casdoor-smoke.yml up -d backend   # 临时覆盖，不改 .env
python3 scripts/stage7_smoke.py          # 全程 ~3.5min（含两轮 61s 错峰）
docker compose up -d backend             # 还原 mock
```

## 3. 冒烟揪出的真实缺陷（阶段 7 实机修复记录）

1. **gzip 非确定性（测试 flake 根因）**：`values_csv` 用 `gzip.compress` 默认嵌入当前 mtime →
   两次运行跨秒时字节不等，`test_compute_stub.py::test_deterministic` 偶发失败（与负载相关：并行 CPU 下两次 `_run()` 跨秒概率上升）。
   **修复**：`qlib_compute.py` / `stub_compute.py` 两处 `gzip.compress(..., mtime=0)` —— 相同因子值 → 字节级一致
   （对生产同样有益：稳定 payload 比对与可复现导出）。修复后 444 × 3 连跑零 flake。
2. **失败登录审计被静默丢弃**：`DbAuditWriter` 对无 org 归属的记录只发一行**残缺**的 warning（缺 detail/ip）——
   登录失败（身份解析前）的安全事件实际不可查。**修复**：跳过日志补全 `action/resource_id/outcome/detail/ip`
   （`audit_skipped_no_org`），并给登录失败路径注入 client ip（`handle_callback(ip=)` + 回调路由 audit ctx）。
   冒烟第 3 轮以 docker logs 断言验证（为什么不落表：02 §4）。
3. **Set-Cookie 清除解析**：Starlette `delete_cookie` 发的是带引号空值 `name=""`，冒烟客户端曾把引号当值导致「Cookie 未清除」误报 ——
   解析器剥引号后按清除处理（服务端行为本身正确）。

## 4. 生产 compose 验证（详见 03 §1）

- `docker compose -f docker-compose.prod.yml config --quiet` → 通过；服务集 = backend/frontend/migrate/worker（qlib-server 挂 profile）。
- `build backend frontend worker` → **三镜像全部通过**：
  - backend 603MB / frontend 79.2MB（各一次通过）；worker `qqlab-prod-worker` 700MB，
    终态构建约 2.5 分钟（uv 步骤 131s：装 207 包 —— 缓存挂载命中昨夜已下的 188 包、
    本轮补拉 19 包 2m00s、安装 8s，导出层 37.7s）。
  - worker 镜像内 `import qlib/lightgbm/fastapi/jwt/qqlab` 冒烟通过（amd64/Rosetta）。
  - **PyPI 劣化处置记录（运维数据）**：首夜构建撞上 files.pythonhosted.org 直连劣化
    （实测 ~37KB/s），`uv sync` 14 分钟后解压 `ipython` 轮子报
    `deflate decompression error: repeated call with bad state` 失败；且 `uv.lock` 锁定轮子
    URL —— `uv sync --frozen` 不理会 `UV_DEFAULT_INDEX` 镜像站 build-arg（实测无效）。根治：
    `backend/Dockerfile` 四处 uv sync 加 `RUN --mount=type=cache,target=/root/.cache/uv`
    （已下载轮子跨构建持久在 BuildKit 缓存挂载，失败重试**增量续传**，有限次必收敛）——
    本次终态构建即该机制实证：昨夜失败重试期间入缓存的 188 包被直接复用，仅补拉 19 包。
- 与 dev 栈并存验证：`name: qqlab-prod` 独立项目名，构建/配置全程未触碰运行中的 dev 栈。

## 5. 现场事故处置：dev 栈数据卷重置

**事故**：阶段中对 dev 栈执行过一次 `docker compose down -v`（为清 casdoor 卷）——
`-v` 按 compose 文件删**全部命名卷**，pg/redis/rabbit 数据一并重置（后续排查：数据集表空、审计仅当日行）。
qlib 磁盘数据卷未受影响（`make qlib-data` 幂等探测「已存在，跳过下载」）。

**处置链**（全程有据可查，<15min）：

1. `make qlib-data` → 幂等确认 `/qlib_data/dev-org/cn_data` 完好（3875 只 / 1999-11-10 ~ 2020-09-25）；
2. `make dataset-import-smoke` → worker 重登记 dataset（含 data_sources / data_licenses 四标注台账）；
3. 复种 e2e 锚定种子：`POST /projects(name=smoke)`、`POST /factors(s6-ma20-ic, Mean($close,20)/$close-1)`、
   `POST /models(s6-reuse-lgb, lgb)`（均以 mock admin + CSRF 双提交）；
4. 复跑 `stage6_smoke.py` → **34/34**（真实 qlib 因子计算/回测/复用训练全链路重跑通过，顺带产出 e2e 需要的回测行）；
5. 复跑 `pnpm e2e` → **11/11**。

**教训**：①`down -v` 是全项目级操作，多 profile 栈上要先 `docker compose config --volumes` 看影响面；②种子是三个 API 调用，
复种成本低 —— 阶段 6 R6-4「e2e 依赖种子」的风险定级（低）得到实证支持；③`make qlib-data` 的幂等设计（已存在即跳过）避免了
一次 ~10min 的数据重下。

## 6. Casdoor 实机探测记录（R7-2 素材）

对 dev 实跑镜像（`casbin/casdoor-all-in-one`，amd64 digest 见 05 §3）的探测结论全文见
[05 §4](./05-casdoor-deployment.md)。冒烟与单测共同固化的事实：discovery issuer 按 Host；
id_token iss 按兑换请求 Host（casdoor#1622）；`/login/oauth/authorize` 为 SPA 路由；
`/api/login type=code` 发码（OAuth 参数走 query）；ROPC 返回完整 user struct（roles 对象数组 / owner / aud 数组）；
JWKS kid `cert-built-in`；**logout 无 `id_token_hint` 也 302 落地**（该构建）。
