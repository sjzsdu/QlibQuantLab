#!/usr/bin/env bash
# 一键逻辑备份（阶段 8 · D 项，D8-8）：pg_dump -Fc 落 ./backups/qqlab-<UTC 时间戳>.dump。
# 在容器内执行 pg_dump（postgres:16-alpine，与主库同 tag）—— 宿主不需要装 postgres 客户端，
# 模式 B（外部托管 PG）同样适用：.env 的 DATABASE/PG 连接参数指向谁就备份谁。
#
#   scripts/backup.sh            # 备份，输出落盘文件名
#   scripts/backup.sh nightly    # 自定义标签（仅展示用，不改文件名）
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p backups
docker compose --profile backup run --rm pg-backup
echo "最近一次备份：$(ls -t backups/*.dump 2>/dev/null | head -1)"
