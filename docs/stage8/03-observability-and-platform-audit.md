# 03 · 可观测性与平台审计（B 项 + C 项）

## B 项 · `/metrics` 可观测性

### 1. 指标全集与产生方式（D8-1/2/3）

端点 `GET /api/v1/metrics`（Prometheus text exposition 0.0.4，`core/metrics.py` 手写渲染、零第三方依赖）。

| 指标 | 类型 | 产生位置 | 语义 |
|------|------|----------|------|
| `qqlab_http_requests_total{method,route,status}` | counter | `RequestContextMiddleware._observe` | 进程内累计；route = **全路径模板**（见 §2.1），未命中归 `route="unmatched"` |
| `qqlab_http_request_duration_ms{...}` | histogram | 同上 | 进程内直方图；异常路径按 500 记录 |
| `qqlab_jobs_depth{kind,status}` | gauge | scrape 时现查 `jobs` 表 | queued/running 现值 |
| `qqlab_jobs_finished_window{kind,status}` | gauge | 同上 | 窗口（`METRICS_QUEUE_WINDOW_HOURS`，默认 24h）完成量；**失败率 PromQL 现算** `failed/(succeeded+failed)` |
| `qqlab_job_duration_seconds_avg{kind}` / `qqlab_job_wait_seconds_avg{kind}` | gauge | 同上 | 窗口内完成任务的执行时长/排队等待均值 |
| `qqlab_job_duration_seconds_p95{kind}` / `qqlab_job_wait_seconds_p95{kind}` | gauge | 同上 | **仅当该 kind 样本 ≥5**（`_MIN_SAMPLES_FOR_QUANTILE`）才输出 —— 样本太少 p95 无统计意义 |
| `qqlab_queue_scrape_ok` | gauge | 队列 scrape 成败 | 0 = 失败（细节看日志），防「指标静默缺失」不可观测 |
| `qqlab_worker_up` | gauge | `CacheProvider` 键 `qqlab:worker:heartbeat` | 1 = 3 倍心跳间隔内有心跳（`WORKER_HEARTBEAT_INTERVAL_SECONDS`，默认 10s） |
| `qqlab_worker_heartbeat_age_seconds` | gauge | 同上 | 最近心跳距今秒数 |
| `qqlab_worker_recycled_total` | counter | `qqlab:worker:recycled_total` | 启动时回收孤儿任务累计；**缓存丢失/未重启即归零**（HELP 已写明） |
| `qqlab_worker_scrape_ok` | gauge | worker 侧 scrape 成败 | 同 queue_scrape_ok |

三分归属与两个「不冒充」的设计约束：

- **队列指标是滑动窗口现值 → 全部用 gauge，不用 counter/histogram** —— 窗口滑出即消失的量不能假装单调累计；
- **worker 计数走 CacheProvider 而非 DB** —— api 进程不做重查询，代价是缓存丢失计数归零（可见于 `worker_scrape_ok` 与 HELP 注释）。

**鉴权三态**（D8-1）：

| 环境 | 行为 |
|------|------|
| dev（无 `METRICS_TOKEN`） | 免鉴权 200 |
| 生产、未配 `METRICS_TOKEN` | **404 fail-closed**（端点不存在，不给探测面） |
| 生产、已配 `METRICS_TOKEN` | `Authorization: Bearer <t>` 或 `X-Metrics-Token: <t>`，错/缺 → 401 |

### 2. 两个实现要点

#### 2.1 route 标签为什么不能直接用 `scope["route"].path`

FastAPI ≥0.143 的 `_IncludedRouter` 让运行时 route 的 `path` 是**相对路径**（丢了 `include_router(prefix=...)` 的前缀）。
`effective_route_contexts()` 每次调用返回新的 context 对象（不能按 `id()` 跨调用对齐），但 ctx 上的
`original_route` 是路由表里的**同一个对象**。因此 `create_app` 时一次性建 `id(route) → ctx.path` 全路径映射存
`app.state.route_templates`，中间件按当前 `scope["route"]` 的 `id` 查，查不到退回相对路径（宁可标签略粗，不可崩）。

#### 2.2 序列上限与 `route=other` 折叠

`max_series` 防 label 基数爆炸：

- **有 route 维度**的序列超限 → 折叠进 `route="other"`（other 槽**不受硬顶**，防止折叠本身又超限）；
- **无 route 维度**的序列超限 → 直接丢弃并计数（这类序列是有限固定集，超限说明配置错了）。

### 3. Prometheus（D8-7，`--profile monitor`）

```bash
docker compose --profile monitor up -d prometheus   # 只起 Prometheus，不带 Grafana/Alertmanager
```

- 镜像 `quay.io/prometheus/prometheus:v3.5.0`（**quay 官方源**，本机 docker.io 不可达时的实证可用源）；
- 抓取：`backend:8000/api/v1/metrics` + Prometheus 自身；TSDB 保留 15d（`prometheus_data` 卷）；
- 宿主回环 `127.0.0.1:${HOST_PORT_PROMETHEUS:-9090}`。

`deploy/monitor/rules.yml` 五条告警（接企业告警渠道归运维）：

| 告警 | 触发 | 意图 |
|------|------|------|
| `QqlabWorkerDown` | `qqlab_worker_up == 0` | worker 心跳消失（挂了/缓存断了） |
| `QqlabHigh5xxRate` | 5xx 比例持续偏高 | 服务端错误激增 |
| `QqlabQueueBacklog` | 队列深度持续高位 | 消费跟不上 |
| `QqlabMetricsScrapeBroken` | `queue_scrape_ok==0` 或 `worker_scrape_ok==0` | **指标管道自身坏了**（可观测性的可观测性） |
| `QqlabJobFailureRatioHigh` | 窗口失败率偏高 | 任务质量劣化 |

**活体实测**：targets 双 UP；`qqlab_worker_up==1`、`qqlab_job_duration_seconds_avg{kind="backtest"}=15.707` 查询命中；
规则组 `qqlab` 5 条加载（详见 [05 §3](./05-testing.md)）。

## C 项 · 平台审计与平台管理员

### 1. 新表 `platform_audit_events`（迁移 0005）

跨租户**全局表**：**刻意无 `org_id` 列**（架构测试 NON_TENANT_MODELS 分类显式登记）。
与租户审计 `audit_logs` 的分工：租户表按 org 隔离检索；本表是平台管理员的全局视图。

- **org 恒空的依据**：登录失败发生在身份解析之前，本就没有租户归属 —— 这类事件在租户表里是
  「无 org 则跳过落表」的盲区（stage7 R7-3），平台表把它补上；
- 已知租户线索（成功登录时 user 的 org）折进 `detail.org_id` —— 列置空、线索保留；
- 索引：`(action, created_at)` / `(actor_username, created_at)` / `(created_at)`（最后一个是保留期剪枝用）。

### 2. 双写装饰器 `PlatformAuditTrail`（D8-5，container.py 唯一装配点）

```
audit = PlatformAuditTrail(DbAuditWriter(database), database, cache, retention_days=…)
```

- **平台事件** = `auth.login / login_failed / logout / token_invalid` + `action.startswith("admin.")` →
  **先转发内层**（租户审计路径行为零变化，内层自吞异常）**再写平台表**；
- 其余动作只转发（调用点代码一行未改）；
- 平台表写失败 / 剪枝失败 → `logger.exception` 后继续，**不影响主流程**（同 DbAuditWriter 纪律）；
- **保留期节流剪枝**：写入时查缓存键 `qqlab:platform_audit:last_prune`，距上次 <24h 直接跳过，
  否则 `DELETE ... WHERE created_at < now - PLATFORM_AUDIT_RETENTION_DAYS`（默认 365 天）再置键 ——
  避免每条写都全表扫。

### 3. 平台管理员（D8-4）与查询端点（D8-6）

- `is_platform_admin(user, settings)`：`PLATFORM_ADMIN_USERS` 条目匹配 `username` **或** `user_id`；
  **mock 留空回落** `MOCK_USER_ID/MOCK_USER_USERNAME`（开发便利）、**casdoor 留空 = 无人**（fail-closed）；
- `require_platform_admin` 依赖：白名单外 → `403` + 结构化日志 `platform_admin_denied`；
  依赖上挂 `__qqlab_roles__` 扫描标记，让架构测试按「已守卫」识别（权限语义在 env，不在 RBAC 表）；
- `GET /api/v1/admin/platform-audit`：分页（page/page_size ≤200）+ `action` 前缀过滤（`auth.` / `admin.config` …），
  按 `created_at desc` 排序，`PageOut` 信封。

**验证矩阵**（14 个新测试 + 活体）：

| 场景 | 期望 | 实测 |
|------|------|------|
| mock 白名单空 | 200（回落 mock 身份） | ✅ |
| 显式 username 条目 | 200 | ✅ |
| 组织 admin 不在白名单 | 403 | ✅ |
| 匿名 | 401 | ✅ |
| casdoor 白名单空 | fail-closed（单测断言 False） | ✅ |
| stage7 真冒烟期间的登录/失败/登出 | 落平台表 | ✅ `auth.login ×8 / login_failed ×2 / logout ×1` |
