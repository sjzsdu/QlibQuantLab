# 06 · 风险登记与关闭（阶段 8）

## 已关闭 / 有实测的既有风险

### R7-3 失败登录审计仅结构化日志 — ✅ 阶段 8 关闭（C 项）

平台审计表补上「无租户归属」盲区：`auth.login_failed` 现在**落 `platform_audit_events`**（org 恒空）。
stage7 真冒烟期间实测落表 `auth.login_failed × 2`（[05 §4](./05-testing.md)）；租户表行为不变（转发优先）。

### R9 Traefik 长连接超时 — ✅ 演练资产就位（表 A 待运维执行）

`deploy/rehearsal/` 演练 override + 静态配置按生产定稿 1:1 固化（traefik:v3.7.15），
验证步骤 A1–A6 回写 [stage7/03 §5.4](../stage7/03-production-deployment.md)。
本机镜像源不可达未跑真 Traefik —— **上线前由运维在有网环境执行表 A**（唯一遗留动作）。

### R11 Qlib-Server 不支持 Redis 密码 — ✅ 方案②本机实测（表 B1–B10）

双 Redis override 演练十项全绿（NOAUTH / 零宿主端口 / 各指其库 / 心跳落 app-redis /
qlib probe ok / dbsize 隔离 / 回滚恢复），证据表在 stage7/03 §5.4。生产切换照表执行。

## 新登记（阶段 8）

| # | 风险 | 影响 | 可能性 | 缓解方案 | 状态 |
|---|------|------|--------|----------|------|
| **S8-1** | 生产未配 `METRICS_TOKEN` 时 `/metrics` 404 fail-closed —— 上线初期可能「忘了开监控」 | 监控盲区 | 中 | 上线清单项：配 token + Prometheus 起 `--profile monitor`；`QqlabMetricsScrapeBroken` 告警兜底 | 开放（运维配置项） |
| **S8-2** | worker 心跳/回收计数存 CacheProvider，缓存丢失或键被逐出 → 指标归零/心跳误报 | 误告警 | 低 | `worker_scrape_ok` 可见 scrape 成败；HELP 写明「缓存丢失即归零」；Redis 持久化（appendonly）已开 | 开放（已可观测） |
| **S8-3** | 备份只覆盖 PG：objects/qlib_data 依赖再生成（重新导出 / `make qlib-data`），再生成需要外网或本地源 | 极端场景下数据不全 | 低 | D8-8 决策记录 + 04 §1 范围表写明；qlib 数据有本地 zip 源兜底（R7） | 开放（接受，见 04 §1） |
| **S8-4** | 平台管理员白名单走 env，人员变动要改 `.env` 重启 | 交接摩擦 | 低 | 设计取舍（D8-4：跨租户面刻意不进 RBAC）；改法一行写在 config 注释 | 开放（接受） |
| **S8-5** | 队列指标为 scrape 时现查 `jobs`（24h 窗口 + `_SAMPLE_LIMIT=5000`），高频抓取有查询成本 | DB 负载 | 低 | 窗口与样本上限硬限制；Prometheus 默认 15s 抓取间隔；表有 `(status, finished_at)` 类索引支撑 | 开放（接受） |
| **S8-6** | p95 仅在样本 ≥5 时输出 —— 低流量期监控面板 p95 曲线断续 | 观感 | 低 | 设计而非缺陷（样本少 p95 无意义，03 §1）；面板按 avg 主看、p95 辅看 | 开放（接受） |

## 承接不变

- stage7 的 R7-1…R7-5（Casdoor 镜像/行为漂移/登录限流/e2e 种子依赖）无新变化，仍按 stage7/06 跟踪；
- CI 侧新增守护：`ci.yml` 每次 push 跑 ruff+pytest+真源契约+alembic+lint/tsc/build+e2e —— 本阶段所有「本地等效复现」
  在 CI 上自动化，回归型风险（含架构 AST 约束）由测试兜底。
