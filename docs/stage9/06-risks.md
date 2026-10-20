# 06 · 风险登记与审查缺陷修复（阶段 9）

## 1. 承接风险的状态回写（正式台账 = [stage1/08](../stage1/08-risks-and-roadmap.md)）

| 风险 | 阶段 9 状态 |
|------|------------|
| **R9** Traefik 长连接超时掐断 Qlib WebSocket | ✅ **表 A A1–A6 演练栈实测全过**（stage7/03 §5.4）；影响面按定性收敛为「探测告警 + smoke L1」，任务执行不受影响（stage1/06 §8.6） |
| **R11** Qlib-Server 不支持 Redis 密码 | ✅ 演练栈（prod-rehearsal 生产等效形态）复验通过（03 §5），与阶段 8 表 B 互证 |

## 2. 审查报告缺陷修复记录（本阶段全部修复）

### 2.1 阻断项（3 个）

| # | 缺陷 | 修复与证据 |
|---|------|-----------|
| 1 | **私钥可被 git 跟踪**：`deploy/rehearsal/certs/`（自签证书+私钥）、`.freebuff/` 未忽略 | `.gitignore` 增加两条；`git check-ignore` 实测生效 |
| 2 | **CI backend job 必失败**：`uv sync` 在仓库根执行（pyproject 在 backend/，无根 pyproject）——不设 defaults 时第一步即 fail（本地等效复现） | `.github/workflows/ci.yml` 加 `defaults.run.working-directory: backend`；YAML 解析验证 |
| 3 | **备份同步 shell 包装 MODE 分支失效**：`case` 花括号 bug 使**所有**调用落到「未知模式」（审查实测复现） | `scripts/sync_backups_s3.sh` 修复；实测 `MODE=push/list` 正确分支、未知 MODE `exit=2`；头注过期描述改指本 runbook |

### 2.2 同轮卫生项

| 项 | 修复 |
|----|------|
| `sync_backups_s3.py`：`S3UploadFailedError` 未捕获 → 裸 traceback 吞进 cron | 显式并入 except（非零退出 + 可读信息），失败注入实测 |
| push 前不检查桶存在 → 首跑 404/403 隐蔽失败 | `_ensure_bucket` 自动建桶；403 显式失败不静默；MinIO 回环实测（04 §4） |
| `rehearsal_up.sh` 迁移校验硬编码 head → 每次新增迁移误伤脚本 | 动态取 `alembic heads` + ver1=ver2=head + 表数>0（D9-6，实测 head=0005/20 表） |
| `notify_bridge.py` import 排序（ruff I001） | 修复，ruff 全绿 |
| **A6 断链**：worker 容器内 `qlib.rehearsal.test` 无 DNS → `qlib_server_probe ok=false` ×2 | traefik 网络别名 `aliases: [qlib.rehearsal.test]`（D9-4）→ `ok=true` + 事件往返 + 真实回测收敛（03 §4） |
| 事实性表述失实（4 处） | stage7/03 §3.3/§5.3/表A A6 判据、stage1/07 §4.3 判据、stage1/06 §8.5 归因 + §3/§4、compose「wss 握手均通过」、smoke 脚本 L2/L3 docstring、`main.py` 探测注释、`qlib_compute` progress 文案 —— 全部按实测修正（修正注记 + §8.6 回写，不改写历史记录） |
| `backend/sync_backups_s3.py` 空文件（0 字节误建） | 确认无引用后删除（真身 `scripts/sync_backups_s3.py`） |

## 3. 新登记 S9-*

| ID | 风险 | 影响 | 等级 | 缓解 | 状态 |
|----|------|------|------|------|------|
| **S9-1** | `-dirty` 镜像 tag（`sha-185797d0e404-dirty`）对应未提交树；提交后若忘记重建会把脏树镜像当正式版 | 版本追溯污染 | 中 | 脚本 `-dirty` 后缀强制可见；发版流程固化（02 §4：提交后必重建 + 更新 env.rehearsal 回退值） | 开放（流程约束） |
| **S9-2** | stock pyqlib 0.9.7 client 与 qlib-server `@0ad527d3` 的 pickle/json 协议不兼容 | 当前无影响（数据路径本地、client 不被使用）；未来启用 ClientProvider 时数据请求会静默超时 | 中 | 已实测钉死并写入 stage1/06 §8.6；启用前必须先改 client 侧 JSON 编码（勿回退 server 的 pickle——RCE 面） | 开放（禁用前置） |
| **S9-3** | 旧 stage8 override 与 `rehearsal_up.sh` 同占 9711 | 并跑端口冲突 | 低 | 05 §1 速查注明入口分工（表 A 走新栈、表 B 走旧 override） | 开放（接受） |
| **S9-4** | worker `closing with timeout 30s` 每 30s 重连 rabbitmq | 日志噪音；断连窗口内消息延迟 | 低 | 与 dev 栈行为一致（非演练回归）；阶段 8 队列告警 `QqlabQueueBacklog` 兜底 | 开放（观察） |
| **S9-5** | `/ready` 不含 qlib-server，入口故障不可被就绪探针发现 | 探测故障靠 worker 启动日志/`QqlabMetricsScrapeBroken` 间接暴露 | 低 | R9 影响面收敛后的已知取舍（任务本就不依赖它）；如需显式暴露可后续把 probe 挂进 `/metrics` 系列 | 开放（接受） |
| **S9-6** | 演练 Grafana admin 默认口令模板（`.env.example` 注释「生产必须改」） | 弱口令 | 中 | 生产上线清单项（`GRAFANA_ADMIN_PASSWORD`）；端口全回环绑定 | 开放（运维配置项） |
