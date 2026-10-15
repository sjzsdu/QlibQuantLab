# 04 · 部署（compose 变更 / Makefile / 启动命令）

## 1. docker-compose.yml 阶段 3 变更

| 变更 | 说明 |
|------|------|
| `worker` 独立镜像链 | `build.target: ${WORKER_DOCKER_TARGET:-dev-worker}`（Python 3.11 + qlib）；不再共用 API 的 `<<: *backend` 锚点 |
| `worker` 锁 amd64 平台 | `platform: ${WORKER_PLATFORM:-linux/amd64}`（pyqlib 0.9.7 无 arm64 wheel，实测构建失败后加） |
| `worker` 独立 venv 卷 | `worker_venv:/app/.venv`（与 `backend_venv` 分开 —— 解释器 3.11 vs 3.12） |
| `worker` + scripts 挂载 | `./scripts:/scripts:ro`（连通性 smoke 在 worker 容器内跑） |
| `backend` + scripts 挂载 | `./scripts:/scripts:ro`（入队脚本在 backend 容器内跑） |
| `qlib-server` 修 `QLIB_DATA` | `/qlib_data/{org}/cn_data`（补 `/cn_data` 后缀，与 worker `data_dir_for()` 同源） |
| `qlib-server` + `REGION` | `REGION: ${QLIB_REGION:-cn}` |
| `qlib-server` depends_on `rabbitmq-init` | vhost 授权完成后才启动 |
| **新增 `rabbitmq-init`** | 一次性 `rabbitmqctl set_permissions -p / qqlab …`（qlib profile 内，幂等） |
| **新增 `worker_venv` 卷** | worker 专用 |

**qlib profile 保持 opt-in（决策 #1）**：`qlib-server` / `rabbitmq-init` / `qlib-bootstrap` 都在 `profiles: ["qlib"]` 下，默认 `docker compose up` 不触发。

## 2. .env 新增变量

```bash
# 计算后端：stub（默认，零外部依赖）| qlib（真实数据，经 Qlib-Server）
COMPUTE_BACKEND=stub

# 数据子目录名（dump_bin 根；compose 里 QLIB_DATA 与 worker data_dir_for 同源）
QLIB_DATA_SUBDIR=cn_data

# 标的截断开关（决策 #2）：0 = 全量；>0 = 只取前 N 个标的（首次 smoke 用小集合）
QLIB_DATA_SYMBOLS=0

# worker 平台：pyqlib 0.9.7 无 linux/arm64 wheel（无 sdist）→ Apple Silicon 上锁 amd64（Rosetta）
WORKER_PLATFORM=linux/amd64
```

## 3. Makefile 阶段 3 目标

| 目标 | 命令 | 用途 |
|------|------|------|
| `make qlib-up` | `docker compose --profile qlib up -d --build` | Qlib-Server + rabbitmq-init + 应用栈 |
| `make qlib-data` | `docker compose --profile qlib run --rm qlib-bootstrap` | 官方 zip 两段式导入（幂等） |
| `make qlib-smoke` | `docker compose --profile qlib run --rm worker python /scripts/qlib_connectivity_smoke.py` | L1/L2/L3 三级连通 |
| `make dataset-import-smoke` | `docker compose exec backend python /scripts/enqueue_backtest_smoke.py dataset_import` | 入队导入任务 |
| `make backtest-smoke` | `docker compose exec backend python /scripts/enqueue_backtest_smoke.py backtest` | 入队最小回测 |

## 4. 启动与 smoke 命令（决策 #7：回测只经脚本入队，不开公共 API）

```bash
# A3-1：默认栈（stub 计算）
make dev
# 或：scripts/dev_up.sh

# A3-2：叠加 Qlib-Server（COMPUTE_BACKEND 仍由 .env 决定）
make qlib-up

# A3-3a：导入数据（首次 ~10 分钟，幂等；失败给连通性结论，不换源）
make qlib-data

# A3-3b：三级连通性 smoke
make qlib-smoke
# L1: WS 握手（socketio → qlib-server:9710）
# L2: qlib.init + D.instruments("all")
# L3: D.features 抽样（前 8 个标的 $close）

# A3-4a：入队数据导入（校验目录 + 登记台账）
make dataset-import-smoke

# A3-4b：入队最小回测（动量 topk，费用三件套）
make backtest-smoke
# 观测：
docker compose logs -f worker
docker compose exec postgres psql -U qqlab -c \
  "select id,kind,status,progress,error from jobs order by created_at desc limit 5;"
```

## 5. 切换到真实计算（qlib）

```bash
# .env
COMPUTE_BACKEND=qlib
QLIB_DATA_SYMBOLS=50        # 首次 smoke 只取前 50 个标的

# 重启 worker（qlib extra 生效）
docker compose --profile qlib up -d --build worker
```

## 6. 部署形态不变

- 模式 A（`docker-compose.yml`）：自包含，qlib profile opt-in；
- 模式 B（`docker-compose.prod.yml`）：复用外部基础设施，Traefik labels 只在 compose 层；阶段 3 未改 prod compose（qlib 链路的生产化留到阶段 5+ 评估）。
