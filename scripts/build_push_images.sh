#!/usr/bin/env bash
# ============================================================================
# 构建并推送 QlibQuantLab 的四个生产镜像，供 deploy 仓库的 deploy/qqlab 拉取。
#
# 构建目标与 docker-compose.prod.yml 完全一致：
#   frontend     → frontend/Dockerfile（runner 阶段；构建期注入 BACKEND_INTERNAL_URL，
#                  该值被 Next 的 rewrite 固化进产物，改了要重新构建）
#   backend      → backend/Dockerfile target runtime（Python 3.12，不含 qlib）
#   worker       → backend/Dockerfile target worker-runtime（Python 3.11 + qlib）
#   qlib-server  → qlib-server/Dockerfile
#
# 用法：
#   IMAGE_PREFIX=sjzsdu TAG=latest scripts/build_push_images.sh
#   IMAGE_PREFIX=sjzsdu TAG=v1.0.0 scripts/build_push_images.sh --no-push   # 只构建不推送
#
# 环境变量：
#   IMAGE_PREFIX      镜像命名空间/仓库前缀（默认 sjzsdu；可含 registry host）
#   TAG               镜像标签（默认 latest）
#   TARGET_PLATFORM   目标平台（默认 linux/amd64 —— 与 qlib-server 硬依赖一致，
#                     Apple Silicon 上交叉构建，服务器为 x86 时可直接运行）
#
# 前置：push 需要先 `docker login <registry>`；构建用 BuildKit（compose v2 默认）。
# ============================================================================
set -euo pipefail

IMAGE_PREFIX="${IMAGE_PREFIX:-sjzsdu}"
TAG="${TAG:-latest}"
TARGET_PLATFORM="${TARGET_PLATFORM:-linux/amd64}"

PUSH=1
if [ "${1:-}" = "--no-push" ]; then
    PUSH=0
fi

cd "$(dirname "$0")/.."
echo "[images] root=$(pwd) prefix=${IMAGE_PREFIX} tag=${TAG} platform=${TARGET_PLATFORM} push=${PUSH}"

build() {
    local name="$1"
    shift
    echo "[images] build ${IMAGE_PREFIX}/qqlab-${name}:${TAG}"
    docker build --platform "${TARGET_PLATFORM}" -t "${IMAGE_PREFIX}/qqlab-${name}:${TAG}" "$@"
}

build frontend --build-arg BACKEND_INTERNAL_URL=http://backend:8000 ./frontend
build backend --target runtime ./backend
build worker --target worker-runtime ./backend
build qlib-server ./qlib-server

if [ "${PUSH}" = "1" ]; then
    for name in frontend backend worker qlib-server; do
        echo "[images] push ${IMAGE_PREFIX}/qqlab-${name}:${TAG}"
        docker push "${IMAGE_PREFIX}/qqlab-${name}:${TAG}"
    done
    echo "[images] ✓ 四个镜像已推送：${IMAGE_PREFIX}/qqlab-{frontend,backend,worker,qlib-server}:${TAG}"
else
    echo "[images] ✓ 四个镜像已构建（--no-push，未推送）"
fi
