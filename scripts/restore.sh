#!/usr/bin/env bash
# 从逻辑备份恢复（阶段 8 · D 项，D8-8）。
#
#   scripts/restore.sh backups/qqlab-<ts>.dump
#
# 前置：
#   1. dump 文件在 ./backups/ 下（脚本换算成容器内路径 /backups/<basename>）；
#   2. **先停写**：docker compose stop backend worker   （恢复期间应用不得读写库）
#   3. 若是「整卷损毁」场景：先 up postgres + run migrate 建好 schema，再执行本脚本。
set -euo pipefail
cd "$(dirname "$0")/.."

dump="${1:?用法: scripts/restore.sh backups/qqlab-<ts>.dump}"
[ -f "$dump" ] || { echo "找不到 dump 文件: $dump" >&2; exit 1; }

docker compose --profile backup run --rm \
  -e DUMP_PATH="/backups/$(basename "$dump")" \
  pg-restore
