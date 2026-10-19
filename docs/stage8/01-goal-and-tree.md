# 01 · 阶段目标、决策记录与文件树

## 1. 目标

阶段 7 交付了生产部署「文档定稿」，阶段 8 补齐上线前的**工程化欠账**，六个工作项 A–F：

| 项 | 目标 | 验收 |
|----|------|------|
| **A** | CI 干净环境端到端门禁（GitHub Actions 三 job） | 本地等效复现三 job 全绿 |
| **B** | `/metrics` 可观测性 + Prometheus 监控 profile | 端点三分指标 + 活体抓取链 |
| **C** | 平台审计（跨租户）+ 平台管理员授权面 | 新表/双写/端点 + 白名单 fail-closed |
| **D** | 备份/恢复 + pg 卷损毁恢复演练 | 备份→删卷→恢复→数据逐项对齐 |
| **E** | Traefik WS 与双 Redis 两套演练 override + 验证表 | 各一张验证表回写 stage7/03 §5.4 |
| **F** | 一键复种入口 + CI 数据伪造（D8-12 probe 直走文件系统） | `seed_dev.sh --ci` 幂等全绿 |

执行顺序 F→A→B→C→E→D（先打通复种与门禁，观测/治理随后，最后运维演练），每项完成即实测汇报。

## 2. 决策记录（D8-*）

### D8-1 · `/metrics` 手写 Prometheus 文本渲染

- `core/metrics.py` 的 `MetricsRegistry` **纯标准库**（无 prometheus_client 依赖）：label 排序/转义、累计桶、`max_series` 溢出折叠、`reset`；
- 暴露口 `GET /api/v1/metrics`，content-type `text/plain; version=0.0.4`；
- 鉴权三态：**dev 免鉴权**；生产无 `METRICS_TOKEN` → **404 fail-closed**（端点不存在，不给未授权探测面）；有 token → `Authorization: Bearer <t>` 或 `X-Metrics-Token: <t>`。

### D8-2 · 指标三分（谁产生、谁统计）

| 三分 | 位置 | 说明 |
|------|------|------|
| RED（请求率/错误/时延） | `RequestContextMiddleware._observe` | 每请求记录 method/route/status 直方图；异常路径记 500 |
| 队列深度/完成量/时长 | scrape 时现查 `jobs` 表 | 24h 窗口（`METRICS_QUEUE_WINDOW_HOURS`），**gauge 而非 histogram** —— 滑动窗口不冒充单调累计 |
| worker 心跳/回收计数 | `CacheProvider` 键 | `qqlab:worker:heartbeat` / `qqlab:worker:recycled_total`，逻辑放 `core/worker_heartbeat.py` 供 api 与 worker 双端 import |

### D8-3 · route 标签取全路径模板 + 序列上限

- FastAPI ≥0.143 的 `_IncludedRouter` 使 `scope["route"].path` 是**相对路径**（缺 `include_router` 前缀）。方案：`create_app` 时用 `effective_route_contexts()` 建 `id(route) → 全路径模板` 映射存 `app.state.route_templates`，中间件按 `id` 查，查不到退回相对路径；
- 序列上限：真实路由超 `max_series` 折叠进 `route=other`（other 槽不受硬顶）；无 route 维度的超限指标直接丢弃 —— 防 label 基数爆炸打爆时序库。

### D8-4 · 平台管理员 = env 白名单

- `PLATFORM_ADMIN_USERS`（逗号/空白分隔），与组织内 RBAC **正交**：组织 admin ≠ 平台管理员；
- 条目同时匹配 `username` 与 `user_id`；**mock 留空 = 回落 `MOCK_USER_ID`/`MOCK_USER_USERNAME`**（开发便利）；**casdoor 留空 = 无人**（fail-closed，不给默认跨租户面）。

### D8-5 · 平台审计 = AuditWriter 装饰器双写

- `PlatformAuditTrail` 包装 `DbAuditWriter`，**仅 container.py 一处装配**（调用点零改动）；
- 平台事件 = `auth.login/login_failed/logout/token_invalid` + `admin.*` → 转发内层（租户表行为不变）**且**写 `platform_audit_events`（**org 列恒空** —— 登录失败发生在身份解析前本就无租户归属，已知租户线索折进 `detail.org_id`）；
- 写失败/剪枝失败只记日志不影响主流程；保留期 `PLATFORM_AUDIT_RETENTION_DAYS=365`，写入时**节流剪枝**（缓存键 24h 至多一次全表扫）。

### D8-6 · 平台审计查询端点（执行期补充）

- `GET /admin/platform-audit`：分页 + `action` 前缀过滤，`require_platform_admin` 守卫（依赖扫描标记 `__qqlab_roles__` 供架构测试识别为「已守卫」，权限语义在 env 白名单而非 RBAC 表）；
- 匿名 401；白名单外的组织 admin 403（不泄露平台面存在性之外的信息）。

### D8-7 · 监控挂 `--profile monitor`，只内置 Prometheus

- 镜像 `quay.io/prometheus/prometheus:v3.5.0`（**quay 官方源，已实证拉取成功** —— 本机 docker.io 当前不可达）；
- 抓 `backend:8000/api/v1/metrics` + 自身；`deploy/monitor/rules.yml` 五条告警（WorkerDown / High5xxRate / QueueBacklog / MetricsScrapeBroken / JobFailureRatioHigh）；
- **不内置 Grafana/Alertmanager**（范围外，接企业告警渠道归运维）。

### D8-8 · 备份挂 `--profile backup`，范围只有 postgres

- `pg-backup` / `pg-restore` 一次性服务（`postgres:16-alpine` 与主库同 tag，宿主无需 pg 客户端），产物 `backups/qqlab-<UTC>.dump`（`pg_dump -Fc`，已入 `.gitignore`）；
- objects/qlib_data **不备份**：可再生成（重新导出 / `make qlib-data`）；redis/rabbitmq 是运行期态。业务真源唯一必须持久化的是 PG。

### D8-9 · E 项演练走 `deploy/rehearsal/` 临时 override

- 两套 override 与开发栈合并用（**不改 `.env`**）：双 Redis（实测）与 Traefik（镜像源不可达 → 表 A 待运维执行）；
- Traefik 钉 `v3.7.15`（2026-10-15 发布含 CVE 修复）；labels 与静态超时与生产定稿 1:1。

### D8-10 · `seed_dev.sh` 支持 `--ci`

- `--ci`（= `--skip-qlib-data`：伪造最小数据目录 + 跳过下载）/ `--skip-qlib-data` / `--skip-import` / `--skip-anchors` 分档；幂等（锚点已存在即跳过）。

### D8-11 · CI 可复现性钉版（执行期补充）

- action 钉 `astral-sh/setup-uv@v10` + `version: 0.12.5`；依赖装 `uv sync --extra dev`（**禁 `--all-extras`**，qlib extra 挂死）；
- 本地复现干净 clone 必须 `docker compose -p <隔离名>` —— compose 文件 `name: qqlab` 会撞 dev 栈项目名（CI 上无影响；本机一次演练踩过，见 05 §4）。

### D8-12 · probe 在 `COMPUTE_BACKEND != qlib` 时直走文件系统

- dataset probe 不再依赖 qlib import（API 进程零 qlib 硬约束的延续）：非 qlib 后端直接读 `calendars/instruments` 目录校验；`--ci` 伪造的数据目录即由此链路消费。单测覆盖两条分支。

## 3. 范围裁剪（明确不做）

- 真实生产域名 / DNS / TLS 签发 / Alertmanager 接入 → 归运维（表 A 逐条给判据）；
- Grafana 面板、长周期存储 → 不做（Prometheus 15d retention 起步）；
- 前端零改动（平台审计查询面向 API/运维，不进 UI）→ 无 feat(frontend) 提交片；
- minio/objects 与 qlib_data 的备份 → 可再生成，不做（D8-8）。

## 4. 文件树（阶段 8 新增/修改）

```
.github/workflows/
  ci.yml                    [新] A · 三 job 主门禁
  stage-smoke.yml           [新] A · 手动触发 stage6+7 冒烟
backend/src/qqlab/
  core/metrics.py           [新] B · MetricsRegistry（纯标准库）
  core/worker_heartbeat.py  [新] B · 心跳/回收计数键（api+worker 共享）
  api/v1/metrics.py         [新] B · 指标端点（token 门 + 队列/worker scrape）
  adapters/audit/platform_audit_trail.py [新] C · 平台审计双写装饰器
  models/system.py          [改] C · PlatformAuditEvent（无 org_id）
  adapters/__init__.py      [改] 装配导出
  api/deps.py               [改] C · is_platform_admin / require_platform_admin
  api/v1/admin.py           [改] C · /admin/platform-audit
  api/v1/__init__.py        [改] 路由注册
  config.py                 [改] METRICS_*/PLATFORM_*/WORKER_HEARTBEAT_*
  container.py              [改] PlatformAuditTrail 唯一装配点
  core/middleware.py        [改] RED 观测
  main.py                   [改] metrics + route_templates 映射装配
  models/__init__.py        [改] NON_TENANT_MODELS
  schemas/{__init__,common}.py [改] PlatformAuditEventOut
  worker/main.py            [改] 心跳循环 + 回收计数
  worker/handlers/dataset_import.py [改] D8-12 probe 分支
backend/alembic/versions/0005_platform_audit_events.py [新] C
backend/tests/
  unit/{test_metrics_registry,test_worker_heartbeat,test_platform_audit_trail,test_dataset_probe}.py [新]
  integration/{test_metrics_api,test_platform_admin_api}.py [新]
  contract/test_cache_contract.py [改] 真源 fixture 工厂化
  integration/test_alembic_migration.py [改] +platform 表
  architecture/test_route_permissions.py [改] PUBLIC_PATTERNS +/api/v1/metrics
deploy/monitor/{prometheus.yml,rules.yml}   [新] B · D8-7
deploy/rehearsal/                          [新] E · D8-9 两套 override + traefik 静态配置
docker-compose.yml       [改] prometheus + backup/restore 服务与卷
.env.example             [改] HOST_PORT_PROMETHEUS + **QLIB_DATA_SYMBOLS=0 修复**（见 02 §5）
Makefile                 [改] backup/restore 目标
scripts/
  seed_dev.sh            [新] F · 一键复种（--ci 等分档）
  fabricate_ci_data.py   [新] F · CI 最小数据目录伪造
  backup.sh / restore.sh [新] D · 备份恢复包装
docs/stage8/             [新] 七件套（本目录）
docs/stage7/03           [改] §5.4 两张演练验证表（E 项回写）
```

> 范围外的既有未跟踪文件 `scripts/build_push_images.sh` 不属于阶段 8，保持原样、不纳入提交。
