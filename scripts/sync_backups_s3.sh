#!/usr/bin/env bash
# ============================================================================
# 备份异地同步（阶段 9 · E 项）：把 ./backups/*.dump 推到对象存储，并可拉回验证。
#
# 设计（接口 + 配置驱动，与告警桥同一哲学）：
#   · 「接口」= S3 协议（backend 运行镜像里已有 boto3 —— 零新镜像、零新依赖）；
#   · 「配置」= BACKUP_S3_* 环境变量 —— S3 / Cloudflare R2 / Backblaze B2 / MinIO
#     是同一实现的不同配置（endpoint 决定目标），换存储=改配置，脚本零改动。
#
#   scripts/sync_backups_s3.sh push                    # 推送所有未上传的 dump（幂等）
#   scripts/sync_backups_s3.sh pull  [文件名]           # 从远端拉回（缺省=最新一个）
#   scripts/sync_backups_s3.sh list                    # 列远端对象
#
# 必填环境（生产建议挂 cron，见 docs/stage9/05 运维手册）：
#   BACKUP_S3_BUCKET=qqlab-backups
#   BACKUP_S3_ACCESS_KEY= BACKUP_S3_SECRET_KEY=
# 可选：
#   BACKUP_S3_ENDPOINT=https://s3.ap-xxx.amazonaws.com（R2/B2/MinIO 填兼容端点；空=AWS 默认）
#   BACKUP_S3_REGION=us-east-1   BACKUP_S3_PREFIX=qqlab
#
# 失败语义：任一对象失败 → 退出码非 0（cron/告警可感知）。
# 首跑：push 会在桶不存在时自动建桶（AWS 非 us-east-1 带 LocationConstraint；
# MinIO/R2 等兼容端点裸建）—— 权限不足（403）不静默，原样报错。
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

# 注意：`${1:?...}` 的提示串里不能含裸 `}`—— bash 在第一个未转义 `}` 处终止
# 参数展开，提示串里的 `{push|pull|list}` 会让 MODE 变成 "list [文件名]}"，
# 所有调用都落到"未知模式"分支（阶段 9 审查实测复现）。用法串用方括号/顿号代替。
MODE="${1:-}"
if [ -z "$MODE" ]; then
    echo "用法: scripts/sync_backups_s3.sh push|pull|list [文件名]" >&2
    exit 2
fi
ARG="${2:-}"

# 跑在 backend 运行镜像里（boto3 现成）；-T 分配 TTY 以便 cron 场景；卷映射 ./backups
docker compose --profile backup run --rm --no-deps -T \
    -e BACKUP_S3_ENDPOINT="${BACKUP_S3_ENDPOINT:-}" \
    -e BACKUP_S3_BUCKET="${BACKUP_S3_BUCKET:-}" \
    -e BACKUP_S3_ACCESS_KEY="${BACKUP_S3_ACCESS_KEY:-}" \
    -e BACKUP_S3_SECRET_KEY="${BACKUP_S3_SECRET_KEY:-}" \
    -e BACKUP_S3_REGION="${BACKUP_S3_REGION:-us-east-1}" \
    -e BACKUP_S3_PREFIX="${BACKUP_S3_PREFIX:-qqlab}" \
    -e BACKUP_MODE="$MODE" \
    -e BACKUP_ARG="$ARG" \
    --entrypoint python3 \
    -v "$(pwd)/backups:/backups" \
    -v "$(pwd)/scripts/sync_backups_s3.py:/app/sync_backups_s3.py:ro" \
    backend /app/sync_backups_s3.py
