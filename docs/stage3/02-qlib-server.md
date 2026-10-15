# 02 · Qlib-Server 自建镜像

## 1. 为什么自建而不追官方镜像

官方 `microsoft/qlib-server` 的 `docker_support/Dockerfile` 基于 `continuumio/miniconda3:4.8.2`（2020 年、amd64），且构建期 `pip install git+https://github.com/microsoft/qlib`（当日 main）。两个问题：

1. **miniconda3:4.8.2 在当前环境拉不到**（决策 #4：不追这个镜像，`ARG BASE_IMAGE` 可切）；
2. **git+main 不可复现** —— 今天解析出来的 qlib 依赖树与 2020 年完全不同。

自建镜像的三条原则：

| 原则 | 实现 |
|------|------|
| **源码钉死** | vendored `microsoft/qlib-server` @ `0ad527d3dedf2b5d17ca0afa4b5ec9645fab4b5f`（去 `.git`；`docs/` `docker_support/` 不进镜像，见 `.dockerignore`） |
| **依赖钉死** | `requirements.lock` 逐包钉死版本，构建不访问 git；`pip install --no-deps` 装 vendored 源码（`setup.py` 的 `install_requires` 已被锁文件覆盖） |
| **配置解耦** | 官方在**构建期** `sed` 改 `config_template.yaml`；我们改为 `entrypoint.sh` 在**启动时**用环境变量渲染占位符 —— 一个镜像跑所有环境 |

## 2. 基座选择：python:3.10-slim（而非 3.11）

官方 `setup.py` 硬约束 `gevent<23`。`gevent==22.10.2` 在 **cp310 有官方 wheel**；cp311 起无 wheel，必须源码编译（要 gcc + cython，构建慢且易碎）。所以基座锁 3.10：

```dockerfile
ARG BASE_IMAGE=python:3.10-slim
```

切其它基座（如自补工具链后的 3.11）时只改这个 ARG；当前实测基线是 3.10 + amd64。

## 3. 依赖锁定（requirements.lock 摘要）

版本矩阵依据 `docs/stage1/06-qlib-integration.md` §2；实测结论回写 §8。

| 段 | 包 | 版本 | 原因 |
|----|-----|------|------|
| ① Qlib | `pyqlib` | 0.9.7 | 与 worker 客户端同版本（决策 #5） |
| ② 数据栈 | `numpy` / `pandas` / `pyarrow` | 1.26.4 / 2.0.3 / 15.0.2 | pyqlib 0.9.7 早于 numpy 2.0，必须锁 `numpy<2` |
| ③ server 兼容 | `python-socketio` / `python-engineio` / `flask-socketio` | 4.4.0 / 3.11.2 / 3.1.2 | Engine.IO **v3 代际**（客户端 socketio 4.6.1 ↔ server 4.4.0 同代） |
| ③ server 兼容 | `Flask` / `Werkzeug` | 2.2.5 / 2.2.3 | flask-socketio 3.x 的兼容上限 |
| ③ server 兼容 | `gevent` / `wsproto` | 22.10.2 / 1.1.0 | 官方 setup.py 硬约束 `gevent<23`、`wsproto<1.2` |
| ③ server 兼容 | `pika` / `redis` / `python-redis-lock` | 1.4.4 / 5.0.1 / 3.3.1 | 硬依赖 RabbitMQ + Redis |

server 端（4.4.0/3.11.2）与 worker 客户端（4.6.1/3.14.2）刻意不同小版本、同代际 —— EIO3 握手兼容即可，见 §2 矩阵。

## 4. 启动时配置渲染（entrypoint.sh）

`config_template.yaml` 里全是 `<QLIB_DATA>` 形态的占位符；`entrypoint.sh` 逐个替换：

| 占位符 | 环境变量 | 默认 |
|--------|----------|------|
| `<QLIB_DATA>` | `QLIB_DATA` | `/qlib_data` |
| `<REGION>` | `REGION` | `cn` |
| `<FLASK_SERVER_HOST>` | `FLASK_SERVER_HOST` | `0.0.0.0` |
| `<QUEUE_HOST/USER/PASS>` | `QUEUE_*` | `rabbitmq` / `guest` / `guest` |
| `<TASK_QUEUE/MESSAGE_QUEUE>` | `*_QUEUE` | `task_queue` / `message_queue` |
| `<REDIS_HOST/PORT/DB>` | `REDIS_*` | `redis` / `6379` / `0` |

compose 里 `QLIB_DATA` 必须指向 **dump_bin 根**（含 `calendars/instruments/features`），即：

```yaml
QLIB_DATA: /qlib_data/${MOCK_ORG_ID:-dev-org}/cn_data   # 与 worker 的 data_dir_for() 完全一致
```

> 阶段 3 曾漏掉 `/cn_data` 后缀（provider_uri 指到上一级导致 `D.features` 取不到数），已修复；worker 侧 `data_dir_for()` 是唯一拼接点，两边同源。

## 5. RabbitMQ vhost 授权（rabbitmq-init）

应用默认用户 `qqlab` 只在默认 vhost（`/qqlab`）有权限；**Qlib-Server 官方实现连的是 vhost `/`**。不改 vendored 源码（保持与上游一致），用一条一次性授权补齐：

```yaml
rabbitmq-init:
  profiles: ["qlib"]
  image: rabbitmq:3.13-management-alpine
  command: ["rabbitmqctl", "set_permissions", "-p", "/", "${RABBITMQ_DEFAULT_USER}", ".*", ".*", ".*"]
  restart: "no"
```

`qlib-server` `depends_on` `rabbitmq-init: {condition: service_completed_successfully}` —— 授权完成后才启动。幂等：重复 `set_permissions` 无副作用。

## 6. Redis 免密（已知取舍，阶段 1 R11）

Qlib-Server 官方实现 `redis.StrictRedis(host, port, db)` **不支持密码**（`qlib_server/utils.py`）。共用应用的 Redis 实例只能免密，靠两层保护：

1. Docker 内网（不暴露到宿主）；
2. 宿主端口只绑回环（`127.0.0.1:16379`）。

生产建议应用与 Qlib-Server 各用一个 Redis 实例（模式 B 的 `.env` 指向不同地址）。

## 7. Apple Silicon：linux/amd64（Rosetta）

compose 里 `platform: ${QLIB_SERVER_PLATFORM:-linux/amd64}`。自建镜像基于 python-slim，Rosetta 2 下可跑；启动比原生慢（首次 30–60s，healthcheck `start_period: 60s`）。arm64 原生镜像待 gevent/qlib 的 arm64 wheel 齐全后再切。
