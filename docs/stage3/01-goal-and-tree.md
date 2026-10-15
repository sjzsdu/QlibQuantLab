# 01 · 目标与文件树

## 目标

1. **Qlib-Server 可自建、可启动、可连通**：vendored 源码 + 钉死依赖 + 启动时配置渲染；Apple Silicon 走 `linux/amd64`（Rosetta）。
2. **Qlib 不进 Web 进程**：API 镜像（Python 3.12）物理不含 qlib；worker 镜像（Python 3.11 + `--extra qlib`）是全仓唯一 import qlib 的进程；架构测试断言。
3. **最小回测闭环**：动量 topk 日频纯规则信号（无模型）→ 自研模拟器（t 收盘信号 → t+1 开盘成交，先卖后买）→ 结果三标注（`metrics` / `data_range` / `limitations`）→ 曲线落对象存储。
4. **费用 100% 透传**：六类费用字段（佣金 / 最低佣金 / 滑点 / 冲击成本 / 过户费 / 印花税）全部由 `CostConfig` 驱动，不用任何「qlib 默认值」；单测逐一开关验证。
5. **台账合规**：`dataset_import` 幂等 seed `data_sources`（yahoo_official）+ `data_licenses`（禁止再分发）+ `datasets` 快照。
6. **租户边界 fail-closed**：入队时 `JobRepository.create` 注入外部 org 串（`org_key`），worker 执行前校验 `stable_uuid(org_key) == job.org_id`，不一致即标 failed 并报错。

## 阶段 3 新增 / 改动文件树

```
QlibQuantLab/
├── qlib-server/                        # [新增] Qlib-Server 自建镜像
│   ├── Dockerfile                      #   ARG BASE_IMAGE；builder/runtime 两段；--no-deps 安装 vendored 源码
│   ├── requirements.lock               #   依赖钉死（pyqlib 0.9.7 / numpy<2 / socketio 4.4.0 / engineio 3.11.2 / gevent 22.10.2 …）
│   ├── entrypoint.sh                   #   启动时用 env 渲染 config_template.yaml 占位符
│   ├── .dockerignore
│   └── vendor/qlib-server/             #   vendored microsoft/qlib-server @ 0ad527d3（去掉 .git；docs/docker_support 不进镜像）
│
├── scripts/                            # [新增] 阶段 3 脚本
│   ├── bootstrap_qlib_data.sh          #   官方 GetData 两段式（zip → 解压为 dump_bin）；幂等
│   ├── qlib_connectivity_smoke.py      #   L1 WS 握手 / L2 instruments / L3 features 三级探测（worker 容器内）
│   ├── enqueue_backtest_smoke.py       #   入队 dataset_import / backtest（backend 容器内）
│   ├── dev_up.sh                       #   一键启动 + 等就绪
│   └── README.md
│
├── backend/
│   ├── Dockerfile                      # [改] 新增 worker 链：worker-base(3.11) / worker-builder / dev-worker / worker-runtime
│   ├── pyproject.toml                  # [改] requires-python >=3.11；新增 qlib extra（pyqlib==0.9.7 + socketio 4.6.1 + engineio 3.14.2）
│   ├── uv.lock                         # [改] 重新生成
│   └── src/qqlab/
│       ├── config.py                   # [改] +COMPUTE_BACKEND 校验、+QLIB_DATA_SUBDIR、+QLIB_DATA_SYMBOLS
│       ├── ports/compute.py            # [改] +BacktestSpec.start/end_date；CostConfig.from_dict 兼容扁平/嵌套两形态
│       ├── adapters/compute/           # [新增] 计算适配器（worker 专用包）
│       │   ├── __init__.py             #   build_compute 工厂（惰性导入；API 进程结构上不可能加载 qlib）
│       │   ├── simulator.py            #   最小日频模拟器（纯标准库；目标市值 delta；先卖后买；六类费用）
│       │   ├── stub_compute.py         #   合成数据实现（确定性 seed）
│       │   └── qlib_compute.py         #   qlib 取数实现（D.instruments/D.features 经 Qlib-Server；模拟器共用）
│       ├── repositories/job.py         # [新增] Job/JobLog/Backtest 仓库；create() 注入 org_key + payload_hash
│       └── worker/
│           ├── main.py                 # [改] 注册 dataset_import / backtest；COMPUTE_BACKEND=qlib 时启动探测
│           ├── qlib_env.py             # [改] +probe_qlib_server / +probe_dataset_via_qlib；qlib_online 上下文管理器
│           └── handlers/               # [新增] 任务 handler
│               ├── __init__.py
│               ├── base.py             #   run_job 生命周期：org_key 校验 → mark_running → execute → commit
│               ├── backtest.py         #   读快照 → ComputePort → 三标注回写 + 曲线上传
│               └── dataset_import.py   #   目录校验（qlib 优先，未装则文件系统）+ 台账 seed（幂等）
│
├── backend/tests/
│   ├── architecture/test_import_boundaries.py  # [改] +QLIB 白名单 +3 条 qlib 隔离断言
│   ├── unit/test_simulator.py          # [新增] 12 条：成本透传 / flat / upside / 区间过滤
│   ├── unit/test_compute_stub.py       # [新增] 15 条：合成数据确定性 / 工厂惰性 / qlib_env 纯函数
│   └── unit/test_worker_handlers.py    # [新增] 6 条：台账幂等 / 三标注 / 失败可见 / 类型不匹配 / 重复消费跳过
│
├── docker-compose.yml                  # [改] qlib-server 补 /cn_data 后缀 + REGION；+rabbitmq-init；worker 独立 3.11 镜像与 venv 卷；+scripts 挂载
├── .env.example                        # [改] +COMPUTE_BACKEND / +QLIB_DATA_SUBDIR / +QLIB_DATA_SYMBOLS
├── Makefile                            # [改] +qlib-up / +qlib-data / +qlib-smoke / +backtest-smoke / +dataset-import-smoke
└── docs/
    ├── stage1/06-qlib-integration.md   # [改] §8 追加阶段 3 实测结论（版本矩阵 / 冲击成本口径 / org_key）
    └── stage3/                         # [新增] 本文档
```
