# 05 · 运营交接与运维手册（F 项）

> 引用点：`scripts/sync_backups_s3.sh` 头注（生产 cron 建议）与
> `docker-compose.prod-rehearsal.yml` qlibws 注释（WS/轮询语义记录）。

## 1. 演练栈日常操作

```bash
./scripts/rehearsal_up.sh up       # 起基础设施模拟 + 迁移（冷启动×2 幂等）+ 生产栈 + Traefik + 验证
./scripts/rehearsal_up.sh status   # 两项目容器状态 + 关键探针
./scripts/rehearsal_up.sh down     # 停（保留数据卷；容器/网络删除，dev 栈零影响）
./scripts/rehearsal_up.sh purge    # down + 删演练卷（完全清理）
```

- 占位域名：`curl -k --resolve api.rehearsal.test:443:127.0.0.1 https://api.rehearsal.test/…`
  或本机 `/etc/hosts` 指 127.0.0.1；Traefik dashboard `http://127.0.0.1:8082/dashboard/`；
- 资源与镜像 tag 见 `deploy/rehearsal/env.rehearsal`（IMAGE_TAG 语义 = D9-3，发版流程 = 02 §4）；
- **旧 stage8 override（`docker-compose.rehearsal-traefik.yml`）勿与 rehearsal_up.sh 并跑**
  （同占 9711 端口冲突）；表 B（双 Redis）仍走旧 override 入口。

## 2. 备份异地同步 · 生产 cron 建议（E 项）

```cron
# 每日 03:10 推送 + 每周日 04:00 全量列检（服务器本地时区）
10 3 * * * cd /srv/QlibQuantLab && MODE=push ./scripts/sync_backups_s3.sh >> /var/log/qqlab-sync.log 2>&1
0 4 * * 0  cd /srv/QlibQuantLab && MODE=list ./scripts/sync_backups_s3.sh >> /var/log/qqlab-sync.log 2>&1
```

必填环境（头注为准）：`S3_ENDPOINT_URL` / `S3_REGION` / `S3_BUCKET=qqlab-backups` /
`S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY`（可选 `S3_FORCE_PATH_STYLE=1`、`BACKUP_DIR`）。
失败语义：上传失败非零退出 + 显式错误（`S3UploadFailedError`），cron 邮件/日志可直接判读；
**每月一次演练拉回**：`MODE=pull` 后 `sha256sum -c`（对账实现见 sync 脚本）。
备份范围与边界（本地 pg/objects/qlib_data 分工）见 stage8/04 §1。

## 3. Qlib socketio 链路语义（实测记录，compose 注释引用本节）

**事实（2026-10-19 演练栈 + server 日志实测）**：

1. 传输 = **engineio EIO3 长轮询（polling）**：握手 `GET /socket.io/?EIO=3&transport=polling`
   → 200 + sid，响应体 `"upgrades":[]` —— qlib-server **不提供 websocket 升级**；
2. 裸 `Upgrade: websocket` 请求 → **400**，直连（不经 Traefik）同样 400 —— 是服务器语义，
   **不是 Traefik 问题**；因此链路上**不存在真·wss 会话**，历史文档中「wss 握手」措辞
   已按事实修正（compose 注释 + stage7/03 表 A A4）；
3. R9 的静态超时（`serversTransport.forwardingTimeouts` 等全 0，v3.7.15 唯一正确字段，
   见 stage7/03 §3.2）对长轮询语义**仍然正确**：每个轮询请求可能挂数十秒，不设 0 会被掐；
4. 健康探测 = worker 启动 `qlib_server_probe`（socketio 握手，`ok=true/false` 进结构化日志，
   失败**只告警不退出**）；数据取数走本地共享卷（stage1/06 §8.6）。

**故障速查**：

| 症状 | 判读 |
|------|------|
| `qlib_server_probe ok=false` | 先 `docker exec <worker> getent hosts qlib.rehearsal.test`（DNS/别名 D9-4）→ `curl -si 'http://127.0.0.1:9711/socket.io/?EIO=3&transport=polling'`（Traefik/入口）→ `docker logs qlib-server`（服务本体） |
| 回测失败但 probe ok | 与 qlib-server 无关：查数据卷（`/qlib_data/<org>` 是否导入）、`qlib_prices_fetched`、任务日志 |
| `Calendar request` 无响应 | 查 body 是否 pickle（stock client 不兼容，03 §4.3）→ server 日志 `UnicodeDecodeError` |

## 4. 告警处置 SOP（5 条规则）

| 告警 | 首查 | 动作 |
|------|------|------|
| `QqlabWorkerDown` | `GET /api/v1/metrics` 的 `qqlab_worker_up` + worker 容器日志 | 心跳丢失 → 重启 worker；OOM 先看 `.env.example` `WORKER_MEM_LIMIT` 注释 |
| `QqlabHigh5xxRate` | Grafana Qqlab 平台总览 → 5xx 曲线 → backend 日志 request_id | 按 request_id 下钻 |
| `QqlabQueueBacklog` | `/metrics` 队列段 + jobs 表 `status=queued` 计数 | 拉 worker 副本（`deploy.replicas`；并发=1 是 qlib 单例约束） |
| `QqlabMetricsScrapeBroken` | 401/404 → `METRICS_TOKEN` 是否配、`METRICS_ENABLED` | fail-closed 语义是设计（stage8 D8-4） |
| `QqlabJobFailureRatioHigh` | jobs 表近 24h failed 占比 + 任务日志 | 区分数据/代码/基础设施原因 |

回执核对：`curl -s 127.0.0.1:19094/receipts`（演练）或宿主 9094（dev `--profile monitor`）。

## 5. 发版与回滚速查

```bash
IMAGE_PREFIX=sjzsdu make deploy-images   # 构建+推送+写 manifest（详见 02）
IMAGE_TAG=<tag> make deploy-pull         # 生产侧按 tag 拉取
# 回滚 = 用 image-manifest.json（或 02 发版记录）里的旧 tag/digest 重新 pull + up
```
