# 06 · 残余风险与后续动作

> 口径：阶段内已关闭的写 ✅ + 实证；仍开放的写清触发条件、现状对策与后续动作。全局风险台账在
> [`docs/stage1/08-risks-and-roadmap.md`](../stage1/08-risks-and-roadmap.md)（本阶段回写 R9/R11 状态）。

## 已关闭

### R6-2 worker 崩溃留下孤儿 `running` 任务 — ✅ 已解决（阶段 7）

- **实现**：`repositories/job.py::recover_stale_running_jobs` + `worker/main.py` 消费前回收；
  阈值 `WORKER_STALE_JOB_MINUTES=10`（env 可调）。孤儿行按 attempts：未耗尽 → 回 `queued` 重投，耗尽 → `failed`。
- **单副本前提（评审点①，必须写明）**：判据是「`heartbeat_at` 早于阈值」。多副本下存在双执行风险 ——
  长训练 >10min 无检查点 + 另一 worker 重启回收 → 任务被重复入队执行。当前架构
  `QLIB_WORKER_CONCURRENCY=1` 且 worker 单副本，前提成立；**扩多副本前必须先把回收改为 `locked_by`/租约比对**。
  前提同时固化在 `recover_stale_running_jobs` 函数头注释与 `.env.example`。
- **实证**：`tests/unit/test_worker_recover.py` 6 例（requeue / 耗尽 failed / 阈值边界 / 不动 queued 等）；
  worker 启动日志 `stale_running_recovered`。

### R7-0（阶段 6 R6-1 延伸） worker 镜像 libgomp1 — ✅ 阶段 5 已固化

本阶段 worker 镜像重建（阶段 7 代码）沿用该镜像链，`import lightgbm` 与真实训练再次实证。

## 开放风险（阶段 7 新登记）

### R7-1 Casdoor 镜像获取与架构漂移 — 中（环境性）

**现状**：dev 栈 amd64 靠镜像源 manifest 探测 + digest 拉取 + retag（`deploy/casdoor/README.md` 固化命令与双架构 digest）；
compose 锁 `platform: linux/amd64`。镜像源不可达 / tag 漂移时 casdoor 起不来（应用侧 fail-fast：缺 issuer 不影响启动，
但 healthcheck 不过、登录 503）。
**后续**：生产固定 digest 不用 `latest`；镜像源演练命令已可复制（阶段 6 worker、阶段 7 casdoor 两次实测同配方）。

### R7-2 Casdoor 行为与主干漂移（logout / iss / 路由形态） — 中

**现状**：dev 实测的三个行为与主干源码有差异或强依赖构建版本 ——
① logout **不要求** `id_token_hint`（主干要求；我们依赖「落点已注册即可 302」）；
② `iss` 按请求 Host 派生（casdoor#1622，靠双白名单兜住）；
③ `/login/oauth/authorize` 无服务端路由（SPA 承接）。
实测明细见 [05 §4](./05-casdoor-deployment.md)。
**对策**：契约只依赖 OIDC 标准面（authorize 参数 / token 兑换 / JWKS），行为差异全部收敛在 `CasdoorAuthProvider`
与配置（iss 白名单）里；`scripts/stage7_smoke.py` 是升级镜像后的**必跑复测**。
**后续**：升级 casdoor 镜像前先跑 stage7 smoke（17 项，其中 logout 落地、iss、authorize 三项直击）。

### R7-3 失败登录审计仅结构化日志 — 低（设计取舍）

**现状**：`auth.login_failed` 发生在身份解析前 → 无 org 归属 → 不落租户 `audit_logs`（跨租户隔离硬约束下，
落表只会产生没人查得到的行）。安全信号在结构化日志：`audit_skipped_no_org`（`action/detail/ip/request_id`）
+ HTTP 中间件 401 行，可按 request_id 关联。
**后续**：若合规要求「失败登录入审计表」，需要平台级（org 之外）审计视图 —— 属阶段 8+ 的平台治理范畴，不在本阶段扩表。

### R7-4 登录限流与冒烟/e2e 共享额度 — 低（承接 R6-3，无变化）

`/api/v1/auth*` 全路径 5/min/IP，`GET /auth/login` 与 `/auth/callback` 各计一次。stage7 冒烟内置三轮 60s 错峰；
e2e 用 storageState 把登录压进 setup。CI 并行时仍须串行（或 staging 放宽，**不改生产默认值**）。

### R7-5 e2e/冒烟对开发种子的依赖 — 低（承接 R6-4；本阶段实证过一次事故）

**现状**：e2e 锚定开发种子（项目 `smoke`、因子 `s6-ma20-ic`、模型 `s6-reuse-lgb`、dev cn_data 数据集）。
本阶段因 dev 栈重建（pg 卷重置）种子缺失，e2e 曾 5 红 —— 按 [04 §5 事故处置](./04-testing.md) 复种后 11/11。
**对策**：种子复种是三个 API 调用 + `make qlib-data`（幂等）+ `make dataset-import-smoke`，全过程 <15min 且有据可查；
阶段 6 的 R6-4 结论维持：全新部署除 01-auth 外 e2e 全红是**预期信号**，不是回归。
**后续**：可选做 `scripts/seed_dev.sh` 一键复种（未做：三步已够短，多一个脚本多一份维护）。

## 跟踪但不在本阶段动作

| 项 | 状态 |
|----|------|
| R9 Traefik 长连接超时 | **文档/清单已备**（[03 §3](./03-production-deployment.md)）：compose 动态 labels 全套（升级头/passHostHeader/flushInterval/sticky）就绪；Traefik **静态**超时关闭属运维侧执行项，已列入模式 B 切换清单与 stage1/08 台账 → **阶段 8：** 演练 override 与验证表 A（A1–A6）落 03 §5.4（`deploy/rehearsal/`），表 A 待运维有网执行 |
| R11 Qlib-Server 不支持 Redis 密码 | **方案已定稿入 03 §4**：qlib-server 专属免密 Redis（仅内网）与应用带密码 Redis 分离，`QLIB_SERVER_REDIS_HOST` / `CACHE_URL` 分配；生产切换时按清单执行 → **阶段 8：** 双 Redis 演练表 **B1–B10 本机实测通过**（03 §5.4），切换照表执行 |
| mock → casdoor 切换演练 | dev 已用冒烟覆盖 env 块（`docker-compose.casdoor-smoke.yml`）；生产演练需真实 IdP 域名，归入模式 B 上线流程 |
