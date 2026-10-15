# scripts/

阶段 3 起在此落盘的一次性脚本（阶段 2 只保留本说明，避免 compose 提前挂载出空目录）：

| 脚本 | 阶段 | 用途 |
|------|------|------|
| `bootstrap_qlib_data.sh` | 3 | 官方 Yahoo 下载 → `dump_bin` 导入；由 `docker compose --profile qlib run --rm qlib-bootstrap` 调用 |
| `dev_up.sh` | 3 | 一键：`cp .env.example .env` → `docker compose up -d --build` → 等健康检查 |
| `smoke_api.sh` | 3 | 覆盖 `/health` `/me` `/projects` 的 curl 冒烟 |
| `pin_versions.sh` | 7 | 导出依赖快照到锁文件 |

> `docker-compose.yml` 里 `qlib-bootstrap` 服务已按 `./scripts:/scripts:ro` 挂载该目录，
> 它挂在 `qlib` profile 下，默认 `docker compose up` 不会触发。
