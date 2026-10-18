# scripts/

阶段 3 起在此落盘的一次性脚本：

| 脚本 | 阶段 | 用途 |
|------|------|------|
| `bootstrap_qlib_data.sh` | 3 | qlib 官方 GetData 两段式导入（zip → 解压为 dump_bin）；`make qlib-data` 或 `docker compose --profile qlib run --rm qlib-bootstrap` |
| `qlib_connectivity_smoke.py` | 3 | Qlib-Server 三级连通性（L1 WS 握手 / L2 instruments / L3 features）；`make qlib-smoke`（在 worker 容器内跑） |
| `enqueue_backtest_smoke.py` | 3 | 入队 `dataset_import` / `backtest` 任务（决策 #7：脚本入队，不开公共 API）；`make dataset-import-smoke` / `make backtest-smoke`（在 backend 容器内跑） |
| `dev_up.sh` | 3 | 一键：生成 `.env` → `docker compose up -d --build` → 等就绪；`--qlib` 叠加 qlib profile |
| `stage5_smoke.py` | 5 | 阶段 5 全链路实机验收（43 项：模型快照/训练/双信号回测/四标注/增量日志/取消双通道/重试/负例）；栈就绪后 `python3 scripts/stage5_smoke.py`（对 `localhost:8000`），记录见 `docs/stage5/05-testing.md` §3 |
| `stage6_smoke.py` | 6 | 阶段 6 合规/可验证性实机验收（34 项：meta 合规、审计导出 confirm+留痕、universe、因子计算落库、csi300 回测+双导出、训练复用、RBAC）；`python3 scripts/stage6_smoke.py [--e2e]`，记录见 `docs/stage6/05-testing.md` |
| `stage7_smoke.py` | 7 | 阶段 7 Casdoor OIDC 实机验收（17 项 / 三轮错峰：PKCE+state、RS256/JWKS 验签、owner 直通、fail-closed×2、审计、error 回调、坏 state、logout 回跳）；先按 `docs/stage7/04-testing.md` §2 切 casdoor env，`python3 scripts/stage7_smoke.py`（约 3.5min） |
| `pin_versions.sh` | 7 | 导出依赖快照到锁文件 |

> `docker-compose.yml` 里 `qlib-bootstrap`（qlib profile）与 `backend` / `worker` 都按
> `./scripts:/scripts:ro` 挂载该目录；默认 `docker compose up` 不会触发 qlib 链路。

## 阶段 3 标准 smoke 流程

```bash
make dev                 # A3-1：默认栈（stub 计算）就绪
make test-backend        # A3-5：176+ 单测全绿
make qlib-up             # A3-2：Qlib-Server + rabbitmq-init（vhost 授权）
make qlib-data           # A3-3a：导入数据（首次 ~10 分钟，幂等）
make qlib-smoke          # A3-3b：L1/L2/L3 三级连通
make dataset-import-smoke  # A3-4a：入队导入任务 → worker 校验 + 台账
make backtest-smoke      # A3-4b：入队回测 → worker 出结果三标注
docker compose logs -f worker   # 观测任务进度
```
