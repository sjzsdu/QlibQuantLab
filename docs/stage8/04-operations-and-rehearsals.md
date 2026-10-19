# 04 · 备份恢复与运维演练

> 阶段 8 · D 项（D8-8 备份 / D8-9 演练）+ E 项运维面。生产域名/DNS/TLS/Alertmanager 归运维。

## 1. 备份范围与策略

| 数据 | 位置 | 备份方式 | 说明 |
|---|---|---|---|
| **业务数据（真源）** | postgres | `make backup` → 逻辑 dump | org/用户/项目/因子/任务/审计/平台审计 |
| 对象存储 | minio | **不备份** | 导出物可由用户重新导出；`objects_data` 卷 |
| Qlib 数据 | `qlib_data` 卷 | **不备份** | 可经 `make qlib-data` 重新导入（dump_bin 再生）|
| 缓存/队列 | redis / rabbitmq | **不备份** | 运行期态，重启即重建；R10/R11 已定稿 |

- **为什么只有 postgres**：其余四类要么可再生成（qlib/objects）、要么是运行期态（redis/rabbit）。业务真源不可再生，是唯一必须持久化的东西。
- **产物**：`backups/qqlab-<UTC>.dump`（`pg_dump -Fc`，自定义格式，`pg_restore` 可按表/按时间点选择性恢复）。
- **`.gitignore` 已忽略 `backups/`**：dump 含用户/审计数据，绝不入库。
- **宿主无需 postgres 客户端**：`pg_dump`/`pg_restore` 跑在 `postgres:16-alpine` 容器内（与主库同 tag，版本天然匹配）。模式 B（外部托管 PG）同理：`.env` 指向谁就备份谁。

## 2. 命令

```bash
make backup                     # 备份 → ./backups/qqlab-<ts>.dump
make restore DUMP=backups/qqlab-<ts>.dump   # 恢复（务必先停写）
```

等价底层（脚本封装，见 `scripts/backup.sh` / `scripts/restore.sh`）：

```bash
docker compose --profile backup run --rm pg-backup
docker compose --profile backup run --rm -e DUMP_PATH=/backups/<file>.dump pg-restore
```

`pg-restore` 用 `--clean --if-exists --no-owner`：就地替换对象（dev/演练场景先 `migrate` 建好 schema 再灌数据）。

## 3. 恢复前置（务必按序）

1. **停写**：`docker compose stop backend worker` —— 恢复期间应用不得读写库；
2. 整卷损毁场景先建 schema：`docker compose up -d postgres` → `docker compose run --rm migrate`；
3. 再跑 `make restore`；
4. 起回应用：`docker compose up -d backend worker`，用 `/ready` + 登录 + 业务列表确认。

## 4. 演练实测（阶段 8 · 2026-10-19，本机 dev 栈）

完整「备份 → 损毁 → 重建 → 恢复 → 端到端」链路：

| 阶段 | 命令 | 结果 |
|---|---|---|
| 备份 | `make backup` | `backups/qqlab-20261019T030820Z.dump`（84.4K）|
| 基线 | `psql` 七表计数 | orgs=2 users=4 projects=3 jobs=10 datasets=1 audit=69 plat_audit=0 alembic=0005 |
| **损毁** | `stop backend worker postgres` → `rm -sf postgres` → `docker volume rm qqlab_pg_data` | 卷 gone；重新 up 后 **0 表** |
| 重建 | `docker compose run --rm migrate` | alembic 0001→0005，**20 表** |
| 恢复 | `make restore DUMP=...` | `restored: qqlab-20261019T030820Z.dump` |
| 对齐 | `psql` 七表计数 | **与基线逐项一致**（含 alembic=0005）|
| 端到端 | `up -d backend worker` → `/ready` → 登录+项目列表 | backend healthy、`/ready` 六项全绿、`projects total=3`（含已删除项目 `smoke` ＝确为恢复数据，非重建种子）|

## 5. E 项 · rehearsal override 指引（D8-9）

两张演练验证表在 [`docs/stage7/03-production-deployment.md` §5.4](../stage7/03-production-deployment.md)（A 待运维执行 / B 本机实测），
override 本体在 `deploy/rehearsal/`，与开发栈合并使用、**不改 `.env`**：

```bash
# R11 双 Redis 拆分（表 B，本机已实测 B1–B10；演练后去 override 重建三容器即回滚）
docker compose -f docker-compose.yml \
  -f deploy/rehearsal/docker-compose.rehearsal-dual-redis.yml --profile qlib \
  up -d app-redis qlib-redis backend worker qlib-server

# R9 Traefik WS 穿透（表 A，待有网环境执行：traefik:v3.7.15 仅发布在 docker.io）
docker compose -f docker-compose.yml \
  -f deploy/rehearsal/docker-compose.rehearsal-traefik.yml --profile qlib up -d traefik
```

- Traefik 静态配置 `deploy/rehearsal/traefik.rehearsal.yml` 与生产定稿（stage7/03 §3.2）同款超时语义；
  labels 与 prod compose（§3.1）1:1，演练=照抄生产；
- 双 Redis：`app-redis`（带密码，应用 `CACHE_URL`）+ `qlib-redis`（免密、**零宿主端口**，Qlib-Server
  硬约束见 R11）；模式 B 等效 = 两地址换外部托管实例，键完全相同。

## 6. 生产接入点（归运维）

- 调度：`make backup` 挂 cron/CI，按 RPO 定频次（建议 ≤24h）；
- 保留：`backups/` 落对象存储或备份盘，异地留存；
- 告警：备份任务失败告警接企业渠道（Alertmanager 归运维）；
- 恢复演练：本文 §4 链路在预发环境定期复演，验证 dump 与 schema 迁移同步（新迁移落库后必须重做一次备份，否则旧 dump 缺新表）。
