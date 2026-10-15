#!/usr/bin/env bash
# 一键启动（模式 A）+ 常用 smoke。阶段 3 起 qlib 链路是 opt-in。
#
# 用法：
#   scripts/dev_up.sh            # 默认栈（stub 计算，无 qlib 依赖）
#   scripts/dev_up.sh --qlib     # 叠加 Qlib-Server + rabbitmq-init（COMPUTE_BACKEND 仍由 .env 决定）
set -euo pipefail
cd "$(dirname "$0")/.."

PROFILE_ARGS=()
if [ "${1:-}" = "--qlib" ]; then
    PROFILE_ARGS=(--profile qlib)
    echo "[dev_up] 启用 qlib profile（Qlib-Server + rabbitmq-init）"
fi

test -f .env || { cp .env.example .env; echo "[dev_up] 已生成 .env（默认值，按需修改）"; }

docker compose "${PROFILE_ARGS[@]}" up -d --build

echo "[dev_up] 等待 backend 就绪..."
for _ in $(seq 1 60); do
    if curl -sf http://localhost:${HOST_PORT_API:-8000}/api/v1/health/ready >/dev/null 2>&1; then
        echo "[dev_up] ✓ backend ready"
        break
    fi
    sleep 2
done

echo "[dev_up] 容器状态："
docker compose ps
