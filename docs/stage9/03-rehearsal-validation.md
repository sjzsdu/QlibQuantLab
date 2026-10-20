# 03 · 模式 B 生产栈演练与验证（B/C 项 · 详细验证表）

> 入口：`./scripts/rehearsal_up.sh up|status|down|purge`（文件头有完整用法）；
> 表 A（R9/Traefik）实测表回写在 [stage7/03 §5.4](../stage7/03-production-deployment.md)，
> 本文是编排细节、验证表与 A6 定性证据链的完整记录。`.env` 一行未改。

## 1. 拓扑（三个 compose 项目互不干扰，dev 栈零影响）

| 项目 | 文件 | 内容 |
|------|------|------|
| `qqlab-infra-sim` | `deploy/rehearsal/docker-compose.infra-sim.yml` | 模式 B「外部托管」模拟：pg(15434)/redis(16382)/rabbitmq(15673)/minio(19001,19002)，全回环 |
| `qqlab-prod-rehearsal` | `docker-compose.prod.yml` + `docker-compose.prod-rehearsal.yml` | 生产栈本体 1:1（backend/worker/qlib-server/qlib-redis/frontend/casdoor/traefik + D 项监控四件） |
| `qqlab-casdoor-1` | 复用 dev 栈 Casdoor | 脚本 connect 到演练网络（宿主 18001 演练专属 casdoor 亦随栈创建） |

关键差异（均在 override 内，不进生产文件）：宿主端口回环绑定 + 偏移（避免与 dev 栈冲突）、
占位域名 `*.rehearsal.test`（D9-2）、traefik 网络别名（D9-4）、`qlib-server`/`worker` 锁
`linux/amd64`、演练资源限额（内存敏感机器调小）。

## 2. 编排步骤（`rehearsal_up.sh up` 实测输出序列）

| 步 | 内容 | 实测 |
|----|------|------|
| ① | 网络 `qqlab-prod-rehearsal-traefik` 就绪 | ✅ |
| ② | 自签 `*.rehearsal.test` 证书生成（`deploy/rehearsal/certs/`，已 gitignore） | ✅ |
| ③ | 演练 casdoor 就绪（127.0.0.1:18001） | ✅ |
| ④ | infra-sim 四件套就绪（minio health 探针） | ✅ |
| ⑤ | `rabbitmq-init` 完成（`qqlab-qlib` 账号 / vhost 权限） | ✅ |
| ⑥ | **迁移冷启动 ×2**：每次动态取 `alembic heads` → 校验 ver1=ver2=head + 表数>0（D9-6） | ✅ 两次均 `head=0005`、**20 表**；`alembic_version=0005` |
| ⑦ | 镜像 pull（manifest tag；失败回退本地） | ✅ tag=`sha-185797d0e404-dirty` |
| ⑧ | 起生产栈并等 healthy（轮询 ≤120s/容器） | ✅ 全 healthy |
| ⑨ | Traefik 探针（9711 握手 / dashboard） | ✅ 见表 A |

## 3. 表 A（R9 · Traefik WS 穿透）实测摘要

A1–A6 全过，完整表（含命令/预期/实测三列）见
[stage7/03 §5.4 表 A](../stage7/03-production-deployment.md)。数字备忘：

- A2 dashboard：routers 7 / services 7 / middlewares 6，**errors=0 warnings=0**；
- A3 握手：`EIO=3`（`EIO=4` 同 200）→ 200 + `{"sid":…,"upgrades":[],"pingTimeout":60000}`；
- A4 三级 smoke（repo 脚本在 rehearsal worker 实跑）：exit=0，L1 `ok=true
  detail=ws://qlib.rehearsal.test:9711`、L2 **3875** 标的、L3 `$close` 抽样（SH600000…）；
  L2/L3 读本地共享卷（LocalProvider），L1 才经 Traefik 到 server；
- A5 https：`live=alive`；`ready` 200 且 database/cache/queue/storage/auth 全 true
  （自签证书需 `curl -k`；`APP_ENV=production`）；
- A6：见 §4。
- 传输语义：**EIO3 长轮询**，server `upgrades:[]`、裸 `Upgrade` 400（直连同然，非 Traefik
  问题）—— 不存在真·wss 会话，R9 的静态超时配置（`forwardingTimeouts` 等全 0）针对长轮询
  请求语义仍然正确且保留。

## 4. A6 定性：数据路径与 calendar 往返（阶段 9 核心发现）

### 4.1 修复：traefik 网络别名（D9-4）

worker 启动探测两次失败：`qlib_server_probe ok=false detail="ws://qlib.rehearsal.test:9711:
Connection refused by the server"`（08:44、12:53 —— 域名在 traefik 网络无解析）。
traefik 服务加 `aliases: [qlib.rehearsal.test]` 后：worker 容器内解析到 **192.168.97.9**（Traefik），
`ok=true`（日志 13:05:02）。worker URL 保持与生产同形（D9-4）。

### 4.2 事件往返（新 A6 判据，实测达成）

worker 容器内 socketio EIO3 客户端 → `ws://qlib.rehearsal.test:9711`（别名→Traefik→qlib-server:9710）
→ emit `calendar_request`（JSON body，`{"start_time":"2020-01-01","end_time":"2020-12-31",
"freq":"day","future":false}`）→ **1.9s 收到 `calendar_response` `status=0`、180 个交易日**。

server 日志七步链全证（sid `2a1023f1`，14:48）：
`Connection established` → `Received calendar request` → `Publish calendar task to rabbitmq` →
`DataProcessor receive calendar task` → `Publish calendar message`(180日) →
`Send calendar response to client` → `Connection finished`。

### 4.3 负面验证：stock pyqlib client 走不通（pickle vs json）

完全复刻 pyqlib 0.9.7 `client.py::send_request` 的编码（`pickle.dumps(body)`）发送同一请求：
**30s 无响应**；server 日志 `request_handler.py:162 json.loads(...)` → `UnicodeDecodeError`
traceback（sid `9efb1cb0`，14:48:53）。vendored 源码与镜像 md5 一致 = 上游 `0ad527d3` 原版
（server 从 pickle 改 json 是安全演进；若未来启用 ClientProvider 应改 **client 侧** JSON 编码）。

### 4.4 数据路径证伪实验（决定性）

worker 容器内用 `build_qlib_config`（与回测同源）但把 `flask_server` 指向不可达 `192.0.2.1:1`：
`qlib.init` 照常成功，`D.list_instruments` = **3875 标的**、`D.features` 抽样 = **16231 行** ——
数据不经过 flask_server。佐证：回测窗口（13:11–13:17）qlib-server **零连接**；
13:32 恰好 3 条 = 3 次 smoke 的 L1 探测。脚本存容器 `/tmp/falsify.py`。

源码链、§8.5 归因修正与完整结论见
[stage1/06 §8.6](../stage1/06-qlib-integration.md)（A6 判据修正注记同步落
[stage7/03 §3.3](../stage7/03-production-deployment.md) 与 stage1/07 §4.3）。

### 4.5 真实任务收敛

- `dataset_import` job `bbc9615f` → **succeeded/100**；
- `backtest` job `3f61d623` → **succeeded/100**（3875 标的，progress 10→50→65→100，
  worker 日志 `qlib_prices_fetched instruments=3875`）；
- 演练库：7 业务表齐（organizations/users/datasets/jobs/projects/strategies/backtests），
  `org=Dev Organization(dev-org)`，数据卷复用 dev 的 dump_bin（导入一次到处可用）。

## 5. R11 双 Redis 在演练栈复验（生产等效形态）

| 验证点 | 实测（2026-10-19） |
|--------|-----|
| `CACHE_URL`（backend/worker 两容器） | `redis://:rehearsal-app-redis-pass@app-redis:6379/5`（带密码，一致） |
| app-redis 未授权访问 | ✅ `NOAUTH Authentication required.`（infra-sim 实例） |
| qlib-redis 宿主端口 | ✅ 无（零宿主端口，不出内网） |
| qlib-server 渲染配置 | ✅ `redis_host: qlib-redis`、`redis_task_db: 0`（免密实例） |
| `/api/v1/health/ready` | ✅ `database/cache/queue/storage/auth` 全 true |

阶段 8 表 B（dev 栈 override 形态，B1–B10）与本表（prod-rehearsal 生产等效形态）互为印证。

## 6. 环境事故处置记录（复现指引）

| 事故 | 现象 | 处置 |
|------|------|------|
| OrbStack daemon 停止 | 所有容器消失 / docker 命令失败 | `open -a OrbStack` 拉起（server 29.8.2） |
| RabbitMQ 60s 启动时序 | qlib-server 起动即 unhealthy（pika 连不上） | 等 RabbitMQ 后重启该容器 → healthy（非代码缺陷） |
| `docker logs --since` 取不到输出 | 本机时钟与容器日志时区/时钟偏差 | 改用 `--tail N`；Traefik accessLog 未开（容器日志无请求行，证据以 dashboard API 与探针输出为准） |
| zsh 下 URL 含 `?` 被吃 | curl 参数被本地 shell 展开 | URL 加引号 |
| `docker exec` 传 heredoc 不通 | 引号/转义问题 | `docker cp` 文件进容器再执行 |
| docker.io 间歇不可达 | pull / imagetools inspect 超时 | 脚本 pull 失败回退本地镜像；digest 对账记录见 02 §2 |
