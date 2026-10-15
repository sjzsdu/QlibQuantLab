#!/usr/bin/env bash
# 启动时用环境变量渲染 qlib-server 配置（替代官方镜像构建期 sed —— 镜像与环境解耦）。
# 占位符来自 vendor/qlib-server/config_template.yaml；未提供的 env 取容器内默认值。
set -euo pipefail

TEMPLATE="${QLIB_CONFIG_TEMPLATE:-/app/config_template.yaml}"
OUT="${QLIB_CONFIG:-/app/config.yaml}"

cp "$TEMPLATE" "$OUT"

replace() { # replace <占位符名> <值>
    sed -i "s@<$1>@$2@g" "$OUT"
}

replace QLIB_DATA         "${QLIB_DATA:-/qlib_data}"
replace REGION            "${REGION:-cn}"
replace FLASK_SERVER_HOST "${FLASK_SERVER_HOST:-0.0.0.0}"
replace QUEUE_HOST        "${QUEUE_HOST:-rabbitmq}"
replace QUEUE_USER        "${QUEUE_USER:-guest}"
replace QUEUE_PASS        "${QUEUE_PASS:-guest}"
replace TASK_QUEUE        "${TASK_QUEUE:-task_queue}"
replace MESSAGE_QUEUE     "${MESSAGE_QUEUE:-message_queue}"
replace REDIS_HOST        "${REDIS_HOST:-redis}"
replace REDIS_PORT        "${REDIS_PORT:-6379}"
replace REDIS_DB          "${REDIS_DB:-0}"

echo "[qlib-server] config rendered -> ${OUT}"
echo "[qlib-server] provider_uri=${QLIB_DATA:-/qlib_data} region=${REGION:-cn} queue=${QUEUE_HOST:-rabbitmq} redis=${REDIS_HOST:-redis}:${REDIS_PORT:-6379}/${REDIS_DB:-0}"

# main.py 里 -c 之后的位置参数原样透传（如 -m request_handler 只起单模块）
exec python /app/main.py -c "$OUT" "$@"
