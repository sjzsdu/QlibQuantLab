# 04 · 监控告警链与备份异地化（D 项 + E 项）

## 1. D 项：告警链架构

```
Prometheus（15s 抓取，qqlab 组 5 条规则）
   → Alertmanager（路由/分组/静默，deploy/monitor/alertmanager.yml）
      → notify-bridge（webhook → 多通道扇出，deploy/monitor/notify_bridge.py）
         → 通道：企微/钉钉/飞书 webhook、SMTP 邮件（.env.example NOTIFY_* 模板已备）
            全部留空时只落本地 sink（卷内 JSON 回执，可 docker exec / /receipts 查）
   Grafana（provisioning：datasource uid=prometheus + 看板 qqlab-overview 自动加载）
```

- 接口 + 配置驱动：bridge `/healthz`（通道列表）、`/receipts`（回执留档）；
- dev 栈入口 `--profile monitor`（HOST_PORT_ALERTMANAGER=9093 / GRAFANA=3100 /
  NOTIFY_BRIDGE=9094，`.env.example` 注释已更新）；演练栈由
  `docker-compose.prod-rehearsal.yml` 内嵌（19090/19093/19094/13100，全回环）；
- 指标暴露鉴权（阶段 8 D8-4 语义在演练实测确认）：`APP_ENV=production` 下
  无 token → **401**（`指标端点 token 无效`）、带 `X-Metrics-Token` → **200** exposition。

## 2. D 项实测（2026-10-19，演练栈）

| 验证点 | 实测 |
|--------|------|
| Prometheus targets | ✅ 2/2 up（`prometheus` + `qqlab-backend`） |
| 告警规则 | ✅ 组 `qqlab` 5 条：`QqlabWorkerDown` / `QqlabHigh5xxRate` / `QqlabQueueBacklog` / `QqlabMetricsScrapeBroken` / `QqlabJobFailureRatioHigh` |
| Grafana | ✅ admin 登录；datasource `Prometheus → http://prometheus:9090`；看板 **uid=`qqlab-overview`**（Qqlab 平台总览）+ 目录 Qqlab |
| Alertmanager | ✅ `GET /api/v2/alerts` → `[]`（当前无告警，非未接线） |
| 通知回执 | ✅ `/receipts` → `20261019T084133Z-firing-QqlabWorkerDown.json` + `20261019T084633Z-resolved-QqlabWorkerDown.json`（firing→resolved 闭环）；`/healthz` → `{"status":"ok","channels":["sink"]}` |
| `/metrics` 鉴权 | ✅ 401 / 200（见 §1） |

## 3. E 项：备份异地化脚本

| 文件 | 角色 |
|------|------|
| `scripts/sync_backups_s3.py` | S3 接口 + 配置驱动：`push`（含 `_ensure_bucket` 自动建桶，403 显式失败）/ `pull` / `list`；上传失败抛 `S3UploadFailedError` **显式并入 except**（审查修复，裸 traceback 不再进 cron）；`pull` 侧 sha256 与本地 `.sha256` 对账 |
| `scripts/sync_backups_s3.sh` | cron 友好包装：MODE 选择、必填 env 检查、退出码（审查修复：MODE 分支花括号 bug —— 修复前所有调用落到「未知模式」） |

与阶段 8 `--profile backup`（pg-backup/pg-restore 本地链）的分工：本地备份→恢复已有
损毁演练背书（stage8/04 §4），本项补**异地副本**一跳。

## 4. E 项实测（2026-10-19，演练 MinIO 19001/19002 完整回环）

| 步 | 实测 |
|----|------|
| `MODE=push`（桶不存在起步） | ✅ 自动建桶 `qqlab-backups` → 推送 `.dump` + `.sha256` |
| 重复 `push` | ✅ 幂等跳过（不重复上传） |
| `MODE=list` | ✅ 列出对象 |
| `MODE=pull` | ✅ 拉回后 sha256 与源一致 |
| `MODE=list`（错误参数/未知模式） | ✅ `exit=2` + 清晰错误信息（修复前 bug：任何 MODE 都报未知模式） |
| 上传失败注入 | ✅ 显式错误信息 + 非零退出（`S3UploadFailedError` 捕获路径） |
| ruff | ✅ 全绿 |

演练桶 `qqlab-backups` 及对象**保留**作为 E 项证据（`rehearsal_up.sh purge` 才随演练卷清除）。
生产 cron 挂载建议（含 env 清单、频率、对账方式）见 [05-operations-runbook.md](./05-operations-runbook.md)。
