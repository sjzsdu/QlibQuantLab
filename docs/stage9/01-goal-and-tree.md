# 01 · 阶段目标、决策记录与文件树

## 1. 目标

阶段 9 = 生产上线最后一段：镜像发布与追溯回滚（A）、模式 B 生产栈演练编排（B）、
演练机 Traefik 定稿与表 A 实测（C）、监控告警链（D）、备份异地化（E）、运营交接（F）。

| 项 | 目标 | 验收 |
|----|------|------|
| **A** | 镜像发布与追溯回滚（`build_push_images.sh` + `image-manifest.json`） | tag 绑定 git 提交、`-dirty` 防冒充；四镜像 digest 清单；演练栈按清单拉起 |
| **B** | 模式 B 演练编排（infra-sim 外部实例模拟 + `rehearsal_up.sh` 一键起停） | 冷启动 ×2 迁移幂等 + 全栈 healthy + dev 栈零影响 |
| **C** | 演练机 Traefik v3 定稿 + 表 A（R9）实测回填 | 表 A1–A6 实测通过（[stage7/03 §5.4](../stage7/03-production-deployment.md)） |
| **D** | 监控告警链（Alertmanager + notify-bridge + Grafana 看板） | firing → 回执 → resolved 全链路实测 |
| **E** | 备份异地化（`sync_backups_s3` 推对象存储 + 拉回验证） | 推-列-拉回环 + sha256 一致 + 失败语义明确 |
| **F** | 运营交接（runbook + 台账回写 + 审查缺陷修复） | docs/stage9 七件套 + stage1/08 R9/R11 回写 |

执行顺序 A→B→C→D→E→F。**范围红线**：仓库 `.env` 一行未改；前端零改动；
本地 main 不 push（等明确指令）。

## 2. 决策记录（D9-*）

### D9-1 · 演练栈 = 三 compose 项目拓扑（不改 .env）

- `qqlab-infra-sim`（`docker-compose.infra-sim.yml`）：模式 B 的「外部托管基础设施」模拟
  （pg/redis/rabbitmq/minio 四件套，全部回环端口）；
- `qqlab-prod-rehearsal`（`docker-compose.prod.yml` + `docker-compose.prod-rehearsal.yml`）：
  **生产栈本体 1:1**（同 labels、同镜像、同 env_file 语义）；
- 复用 dev 栈 Casdoor（脚本 connect 到演练网络）；
- 编排入口 `scripts/rehearsal_up.sh up|status|down|purge`，容器运行时 env 由
  compose `environment:` 覆盖决定 —— 仓库 `.env` 零改动。

### D9-2 · 占位域名 `*.rehearsal.test` + 自签证书

未拿到真实域名/证书前用 `app/api/qlib.rehearsal.test`（本机 `/etc/hosts` 或 `curl --resolve`
指 127.0.0.1）；`rehearsal_up.sh` 自动生成自签证书进 `deploy/rehearsal/certs/`（已 gitignore）。
拿到真实值后只改 `env.rehearsal` 与证书目录，链路零改动。

### D9-3 · `IMAGE_TAG` 双通道语义

shell 环境变量 > `--env-file`：`rehearsal_up.sh` 从 `deploy/image-manifest.json` 读 tag 并
export，**走脚本时 env.rehearsal 的 IMAGE_TAG 被覆盖**；只有直接 `docker compose --env-file …`
才用到 `env.rehearsal` 的钉死值（当前演练栈运行中的 tag）。manifest 是发版真源（02）。

### D9-4 · traefik 网络别名让 worker URL 与生产同形

rehearsal traefik 服务在 `traefik` 网络加 `aliases: [qlib.rehearsal.test]`，worker 保持
`ws://qlib.rehearsal.test:9711`（与生产 `wss://…` 同形）。修复前 worker 容器内该域名无 DNS
（`qlib_server_probe ok=false` ×2），修复后解析到 Traefik 192.168.97.9、`ok=true`（03 §3）。

### D9-5 · A6 判据修正 + 数据路径定性（阶段 9 核心发现）

原判据「worker 日志出现 `calendar_response`」双层不可达成：worker provider 全 `Local*`
（不 emit）；stock pyqlib 0.9.7 pickle body vs server `json.loads`（即便 emit 也炸）。
**数据路径 = 本地共享卷，qlib-server 不在取数路径上**（证伪实验钉死，见 03 §4 与
stage1/06 §8.6）。新判据 = 事件往返脚本 + `qlib_server_probe ok=true` + 真实回测 succeeded，
已在演练栈实测（stage7/03 表 A A6）。

### D9-6 · 迁移校验动态取 `alembic heads`

`rehearsal_up.sh` 冷启动 ×2 校验改为「动态取 heads（实测 `0005`）+ ver1=ver2=head + 表数>0」，
以后新增迁移不再误伤脚本。

### D9-7 · 同步脚本失败语义（审查修复）

`S3UploadFailedError` 显式并入 except（裸 traceback 不再吐给 cron）；push 前 `_ensure_bucket`
自动建桶（403 不静默）；shell 包装 MODE 分支花括号 bug 修复（审查实测复现，见 06 §2）。

## 3. 范围裁剪

- **前端零改动**（无 `feat(frontend)` 片；阶段 9 交付全部在后端脚本/部署/文档层）；
- qlib-server/vendored 源码不动（`0ad527d3` 原版，vendored 与镜像 md5 一致 —— pickle/json
  协议差异属上游事实，处置方向见 stage1/06 §8.6，阶段 9 不引入 fork）；
- 不重命名历史文档章节；判据修正一律以「阶段 9 修正注记 + 回写」方式落盘，不改写既有记录。

## 4. 文件树（阶段 9 新增/修改）

```
scripts/
├── build_push_images.sh        [A] 修改：manifest/digest 清单 + 追溯回滚头注（185797d 起）
├── rehearsal_up.sh             [B/C] 新增：演练一键编排（①-⑨ 步，动态迁移校验）
├── sync_backups_s3.py          [E] 新增：S3 接口 + 配置驱动（_ensure_bucket/显式异常）
└── sync_backups_s3.sh          [E] 新增：cron 友好 shell 包装（MODE 分支修复）

deploy/
├── image-manifest.json         [A] 生成物（已 gitignore；发版记录进本目录 02）
├── rehearsal/
│   ├── docker-compose.infra-sim.yml       [B] 新增：pg/redis/rabbitmq/minio 模拟
│   ├── docker-compose.prod-rehearsal.yml  [B/C] 新增：生产栈演练 override（含 D 项监控）
│   ├── env.rehearsal                      [B] 新增：插值变量（占位域名/镜像 tag/资源）
│   ├── traefik.prod-rehearsal.yml         [C] 新增：v3.7.15 静态配置（serversTransport 修正）
│   ├── traefik.rehearsal-dynamic.yml      [C] 新增：file provider 默认证书
│   └── certs/                             [C] 生成物（已 gitignore）
└── monitor/
    ├── alertmanager.yml                   [D] 新增：路由配置
    ├── notify_bridge.py                   [D] 新增：webhook → 通道桥（/healthz /receipts）
    ├── prometheus.rehearsal.yml           [D] 新增：演练形态抓取配置
    └── grafana/                           [D] 新增：datasource/看板 provisioning

docs/stage9/                   01-06 + README（本七件套）
docs/stage7/03-production-deployment.md   [C/F] 表 A A1–A6 实测回填 + 判据修正
docs/stage1/06-qlib-integration.md        [F] §3/§4/§8.5 修正注记 + §8.6 数据路径定性
docs/stage1/07-deployment.md              [F] §4.3 判据修正
.github/workflows/ci.yml       审查修复：backend job defaults.run.working-directory
.gitignore                     审查修复：deploy/rehearsal/certs/ + .freebuff/
```
