# 阶段 8 · 生产上线准备与平台治理

> 一句话：把系统从「功能齐备」推到「**可上线、可观测、可治理、可恢复**」——
> CI 干净环境端到端门禁（A）、/metrics 可观测性（B）、平台审计与平台管理员（C）、
> 备份/恢复与损毁演练（D）、Traefik/双 Redis 演练验证（E）、一键复种与 CI 数据伪造（F）。
> 前端**零改动**（无 feat(frontend) 片）；`.env` 一行未改。

## 交付物

| 项 | 交付物 | 状态 | 验证 |
|----|--------|------|------|
| **A** CI 门禁 | `ci.yml`（backend / frontend / e2e 三 job）+ `stage-smoke.yml`（手动触发 stage6+7 冒烟） | ✅ | 干净 clone 本地等效复现：ruff+pytest、lint+tsc+build、**e2e 11/11** |
| **B** 可观测性 | `core/metrics.py` + `/api/v1/metrics`（RED/队列/worker 三分，D8-1/2/3）+ Prometheus profile（D8-7） | ✅ | 16 新测试；Prometheus 活体 targets UP、`qqlab_worker_up==1`、5 条告警规则加载 |
| **C** 平台治理 | `platform_audit_events`（0005）+ `PlatformAuditTrail` 双写（D8-5）+ `/admin/platform-audit` + `PLATFORM_ADMIN_USERS` 白名单（D8-4） | ✅ | 迁移全新 PG 20 表；stage7 真冒烟落表 login×8/login_failed×2/logout×1；14 新测试 |
| **D** 备份恢复 | `--profile backup`（pg-backup/pg-restore）+ `make backup/restore` + 损毁演练（D8-8） | ✅ | 备份→**删卷**→migrate→恢复→七表逐项对齐→端到端 `/ready`+业务读（[04](./04-operations-and-rehearsals.md) §4） |
| **E** 演练验证 | `deploy/rehearsal/` 双 Redis + Traefik 两套 override（D8-9），两张验证表回写 [stage7/03 §5.4](../stage7/03-production-deployment.md) | ✅ | 双 Redis **B1–B10 实测**；Traefik 表 A1–A6 待运维执行（本机镜像源不可达） |
| **F** 一键复种 | `seed_dev.sh`（`--ci/--skip-*` 幂等）+ `fabricate_ci_data.py` + D8-12 probe 直走文件系统 | ✅ | clean clone 中 `seed_dev.sh --ci` 全绿（导入+锚点），e2e 随后 11/11 |

**测试基线：477 passed + 1 skipped（ruff 全绿）；真源（TEST_REDIS_URL+TEST_MQ_URL）483 passed + 1 skipped；
stage6 smoke 34/34 + stage7 smoke 17/17 复跑不回退；e2e 11/11（clean clone + dev 栈各一次）；前端 lint/tsc/build 全绿。**

## 文档导航

| 文档 | 内容 |
|------|------|
| [01-goal-and-tree.md](./01-goal-and-tree.md) | 阶段目标、决策记录（D8-1…D8-12）、范围裁剪、文件树 |
| [02-ci-and-seeding.md](./02-ci-and-seeding.md) | A 项流水线三 job 设计、契约真源、stage-smoke 手动门禁、F 项复种入口、`.env.example` 注释缺陷修复 |
| [03-observability-and-platform-audit.md](./03-observability-and-platform-audit.md) | B 项指标三分与暴露口径、Prometheus/告警规则；C 项平台审计双写与平台管理员白名单 |
| [04-operations-and-rehearsals.md](./04-operations-and-rehearsals.md) | D 项备份/恢复与 pg 卷损毁演练实测；E 项 rehearsal override 指引 |
| [05-testing.md](./05-testing.md) | 全部实测记录（回归矩阵、冒烟、e2e 双环境、Prometheus/演练活体证据）与事故处置 |
| [06-risks.md](./06-risks.md) | 阶段 8 风险登记与关闭（承接 stage1/08 的 R9/R11、新登记 S8-*） |

## 验收清单

- [x] 后端 `ruff check` 全绿；`pytest -q` → **477 passed + 1 skipped**
- [x] 真源契约：`TEST_REDIS_URL + TEST_MQ_URL` 全量 → **483 passed + 1 skipped**
- [x] `pnpm lint && tsc --noEmit && pnpm build` 全绿（前端零改动，仍全量验证）
- [x] Playwright e2e → **11 passed**（clean clone 栈一次 + dev 栈一次）
- [x] `stage6_smoke` **34/34** + `stage7_smoke` **17/17**（真 Casdoor 三轮错峰）不回退
- [x] 干净 clone 端到端：`cp .env.example .env` → compose 起栈 → migrate 0005 → `seed_dev.sh --ci` → e2e 全绿（CI 三 job 本地等效复现）
- [x] 全新 PG 库 `alembic upgrade head` → 0001→0005，**20 表**（含 `platform_audit_events` 无 org_id）
- [x] Prometheus `--profile monitor` 活体：targets 双 UP、指标查询命中、告警规则 5 条加载
- [x] pg 卷损毁恢复演练：七表行数与基线逐项一致 + `/ready` 全绿 + 业务数据可读
- [x] `.env` 一行未改；`.workbuddy/` 未触碰；架构硬约束（AST/单测）保持全绿
- [x] 全程未 push（提交按 feat(backend) / test(stage8) 分片，等你确认）
