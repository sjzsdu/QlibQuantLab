# 05 · 实测记录与事故处置（阶段 8）

## 1. 回归矩阵（最终态）

| 门 | 命令/环境 | 结果 |
|----|-----------|------|
| 静态 | `uv run --extra dev ruff check .` | **All checks passed** |
| 单测+集成+架构 | `pytest -q`（conftest 覆盖 sqlite/memory） | **477 passed, 1 skipped**（阶段 7 基线 444 → +33：B 16 / C 14 / D8-12 probe 3）|
| 契约真源 | `TEST_REDIS_URL + TEST_MQ_URL pytest -q`（真 Redis/真 RabbitMQ） | **483 passed, 1 skipped**（16.9s）|
| 前端 | `pnpm lint && tsc --noEmit && pnpm build` | 全绿（前端零改动仍全量验证）|
| e2e（clean clone 栈） | `E2E_BASE_URL=:3100 pnpm exec playwright test --workers=1` | **11 passed**（2.2m）|
| e2e（dev 栈） | 同上（默认 :3000） | **11 passed**（2.3m）|
| stage6 冒烟 | `python3 scripts/stage6_smoke.py` | **34/34** |
| stage7 冒烟（真 Casdoor 三轮错峰） | `docker-compose.casdoor-smoke.yml` 覆盖 + `stage7_smoke.py` | **17/17** |
| 迁移链（全新 PG 库） | `alembic upgrade head` ×2 次演练 | 0001→0005，**20 表**，种子 org/user 在 |

## 2. A 项 · 干净 clone 端到端复现（CI 三 job 本地等效）

```
git clone <repo> → cp .env.example .env → sed 错峰端口（3100/8100/5544/16480/5673/15673 + CORS）
docker compose up -d --build postgres redis rabbitmq backend worker frontend
→ backend healthy、alembic 0005、/ready 六项全绿
→ SEED_API_BASE=:8100 scripts/seed_dev.sh --ci   # D8-12 probe + 导入 + 锚点全绿
→ pnpm install --frozen-lockfile → playwright --workers=1 → 11 passed
```

`seed_dev.sh --ci` 输出要点：伪造目录「缺才写不覆盖」→ dataset_import 入队并 succeeded →
锚点齐备（`project=smoke factor=s6-ma20-ic model=s6-reuse-lgb backtest=succeeded`）→ 幂等重跑提示「已存在」。

## 3. B 项 · Prometheus 活体证据

| 验证 | 结果 |
|------|------|
| `/-/ready` | Prometheus Server is Ready |
| `/api/v1/targets` | `prometheus up` + `qqlab-backend up`（dev 免鉴权抓取）|
| `qqlab_worker_up` 查询 | `1`（真 worker 心跳经 CacheProvider → API → scrape 全链路）|
| `qqlab_job_duration_seconds_avg` 查询 | backtest=15.707 / dataset_import=0.540 / factor_compute=15.672 / train=31.647 |
| `/api/v1/rules` | 组 `qqlab`，**5 条告警**加载 |
| route 标签全路径 | `route="/api/v1/health/live"`、404 归 `unmatched` ✓ |
| 生产 fail-closed | 无 token→404、错 token→401、Bearer/X-Metrics-Token→200（测试覆盖）|
| exposition 规范 | `# HELP/# TYPE` 每族唯一（发现重复后修复，live `uniq -d` 为空、Prometheus 复抓健康）|

## 4. C 项 · 平台审计活体证据

stage7 真 Casdoor 冒烟（17 项）期间，`PlatformAuditTrail` 在生产装配路径下落表：

```
auth.login × 8    auth.login_failed × 2    auth.logout × 1
```

正是 R7-3（失败登录此前只有结构化日志）被补上的实证；迁移侧全新 PG 库 `platform_audit_events` 建表且**无 org_id 列**。

## 5. D 项 · pg 卷损毁恢复演练

完整证据表见 [04 §4](./04-operations-and-rehearsals.md)。要点：备份 84.4K → **`docker volume rm qqlab_pg_data`**（0 表）→
migrate 重建 20 表 → restore → 七表行数与基线**逐项一致** → `/ready` 全绿 → 登录后 `projects total=3`（含已删除项目 `smoke`
＝确为恢复数据）。

## 6. E 项 · 演练

- **双 Redis（表 B1–B10 全实测）**：NOAUTH 拒未授权、qlib-redis 零宿主端口、两容器各指其库、
  worker 心跳落 app-redis（`qqlab:worker:heartbeat`）、`qlib_server_probe ok=true`、dbsize 隔离、回滚后恢复；
- **Traefik（表 A1–A6 待运维）**：本机 `traefik` 镜像拉不动（docker.io EOF；quay 无官方发布；GitHub 仅能读 release 名
  `v3.7.15`）→ override 与静态配置按生产定稿 1:1 固化，有网环境逐行执行即可出实测。

## 7. 事故与环境坑台账

| # | 现象 | 处置 |
|---|------|------|
| 1 | **`.env.example` 行内注释被 compose 当值**（`QLIB_DATA_SYMBOLS= 空值+注释`）→ 新环境 migrate 必崩 | 改 `=0`、注释独立成行；clean clone 复跑验证（02 §5）|
| 2 | **clean clone 撞 dev 栈项目名**：compose `name: qqlab`，我漏了 `-p` 隔离 → clone 栈 recreate 了 dev 容器 | `down` 后从主目录 `up -d --build` 恢复；**卷全在**（项目卷名不随目录变）、数据无损；e2e 结果本身有效（等价 CI 无 dev 栈）。教训固化进 01 D8-11 |
| 3 | docker.io 持续 EOF（minio/traefik 拉不动） | 现有栈不重建依赖镜像；Prometheus 走 quay；Traefik 表转「待运维执行」 |
| 4 | `uv sync --all-extras` 挂死（qlib extra） | CI/文档一律 `--extra dev` |
| 5 | 登录限流 5/min/IP 与冒烟/e2e 抢桶 | 冒烟自带 61s 错峰；e2e 前 `sleep 70`；seed 全程仅 1 次 auth |
| 6 | 契约测试偶发 hang（遗留进程占真源） | fixture 改工厂参数化（0.17s 全绿）；本阶段真源复跑 483 passed 无 hang |
| 7 | 指标 exposition 同族 `# HELP` 重复（kind 循环内逐条输出） | 每族首现才发 HELP/TYPE（写 03 文档时发现）；测试+live+Prometheus 复抓三重验证 |

## 8. 与阶段 7 基线的不回退证明

stage6 **34/34**、stage7 **17/17**、e2e **11/11** 均为阶段 8 改动落地后复跑（非引用旧记录）；
`NON_TENANT_MODELS` 扩充、`PUBLIC_PATTERNS` 增 `/api/v1/metrics`、迁移链 +0005 均被架构/迁移测试显式覆盖。
