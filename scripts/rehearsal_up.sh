#!/usr/bin/env bash
# ============================================================================
# rehearsal_up.sh —— 阶段 9 · B/C 项：模式 B 生产栈演练的一键编排（不改 .env）。
#
#   scripts/rehearsal_up.sh up        # 起基础设施模拟 + 迁移（冷启动×2 幂等）+ 生产栈 + Traefik + 验证
#   scripts/rehearsal_up.sh status    # 两项目容器状态 + 关键探针
#   scripts/rehearsal_up.sh down      # 停两项目（保留数据卷；容器/网络删除，dev 栈零影响）
#   scripts/rehearsal_up.sh purge     # down + 删演练卷（完全清理）
#
# 拓扑（三个 compose 项目互不干扰）：
#   qqlab-infra-sim        deploy/rehearsal/docker-compose.infra-sim.yml（外部实例模拟）
#   qqlab-prod-rehearsal   docker-compose.prod.yml + docker-compose.prod-rehearsal.yml（生产栈本体）
#   qqlab-casdoor-1        复用 dev 栈 Casdoor（脚本把它 connect 到演练网络）
#
# 镜像：默认取 deploy/image-manifest.json 的 tag（scripts/build_push_images.sh 产物），
#       显式 IMAGE_TAG=… 覆盖；本地已有镜像时 pull 失败不致命（回退本地）。
# ============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

ENV_FILE="deploy/rehearsal/env.rehearsal"
BASE=(-f docker-compose.prod.yml -f deploy/rehearsal/docker-compose.prod-rehearsal.yml)
INFRA=(-f deploy/rehearsal/docker-compose.infra-sim.yml)
NET="$(grep -E '^REHEARSAL_NETWORK=' "$ENV_FILE" | cut -d= -f2 | tr -d '[:space:]')"
PROJ="qqlab-prod-rehearsal"

if [ -z "${IMAGE_TAG:-}" ]; then
    IMAGE_TAG="$(python3 -c 'import json;print(json.load(open("deploy/image-manifest.json"))["tag"])')"
fi
export IMAGE_TAG
echo "[rehearsal] net=${NET} image_tag=${IMAGE_TAG}"

compose_base() { docker compose --env-file "$ENV_FILE" "${BASE[@]}" "$@"; }
compose_infra() { docker compose --env-file "$ENV_FILE" "${INFRA[@]}" "$@"; }

wait_healthy() { # 容器名 → healthy（轮询 ≤120s）
    local ctn=$1 i
    for i in $(seq 1 40); do
        local s
        s="$(docker inspect --format '{{.State.Health.Status}}' "$ctn" 2>/dev/null || echo absent)"
        [ "$s" = "healthy" ] && return 0
        sleep 3
    done
    echo "[rehearsal] ✗ ${ctn} 未在 120s 内 healthy（当前: ${s}）" >&2
    docker logs --tail 20 "$ctn" >&2 || true
    return 1
}

cmd_up() {
    # 1. 演练网络（外部；infra-sim 与生产栈共用）
    docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET"
    echo "[rehearsal] ① 网络 ${NET} 就绪"

    # 2. 演练自签证书（*.rehearsal.test；生产=真证书，只换 certs/ 与 env）
    mkdir -p deploy/rehearsal/certs
    if [ ! -f deploy/rehearsal/certs/rehearsal.crt ]; then
        openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
            -keyout deploy/rehearsal/certs/rehearsal.key \
            -out deploy/rehearsal/certs/rehearsal.crt \
            -subj "/CN=*.rehearsal.test" \
            -addext "subjectAltName=DNS:rehearsal.test,DNS:*.rehearsal.test" >/dev/null 2>&1
    fi
    echo "[rehearsal] ② 演练证书就绪（自签 *.rehearsal.test）"

    # 3. Casdoor 是演练栈的一部分（专属实例，下方 up 拉起；dev casdoor 不动）——
    #    刻意不用 `docker network connect` 复用 dev 实例：后加入网络的容器名不进
    #    宿主代理的 DNS（实测解析到 fake-IP 198.18.x → 连接重置，ready auth=false）。
    echo "[rehearsal] ③ IdP = 演练专属 casdoor（随栈创建，宿主 127.0.0.1:18001）"

    # 4. 基础设施模拟（外部 pg / app-redis / rabbitmq / minio）
    #    bitnamilegacy/minio 以非 root（uid 1001）运行且无权 chown 命名卷 → 先预置属主
    docker volume inspect qqlab-infra-sim_rehearsal_minio_data >/dev/null 2>&1 \
        || docker volume create qqlab-infra-sim_rehearsal_minio_data >/dev/null
    docker run --rm -v qqlab-infra-sim_rehearsal_minio_data:/x alpine:3.21 \
        chown -R 1001:1001 /x
    compose_infra up -d
    wait_healthy "qqlab-infra-sim-postgres-1"
    wait_healthy "qqlab-infra-sim-app-redis-1"
    wait_healthy "qqlab-infra-sim-rabbitmq-1"
    for i in $(seq 1 30); do
        curl -sf http://127.0.0.1:19001/minio/health/live >/dev/null && break
        sleep 2
    done
    curl -sf http://127.0.0.1:19001/minio/health/live >/dev/null || { echo "[rehearsal] ✗ minio 未就绪" >&2; exit 1; }
    echo "[rehearsal] ④ infra-sim 四件套就绪（pg/redis/rabbitmq/minio）"

    # 5. qlib-server 专用 RabbitMQ 账号（幂等）
    compose_infra run --rm rabbitmq-init >/dev/null
    echo "[rehearsal] ⑤ rabbitmq-init 完成（qqlab-qlib 账号就绪）"

    # 6. 迁移冷启动 ×2（全新库；第二次必须幂等 no-op）
    #    期望版本**动态取 alembic head**（不钉死具体版本号 —— 钉 0005/20 表会让
    #    以后每次新增迁移都误伤本脚本；阶段 9 审查修正）
    echo "[rehearsal] ⑥ 迁移第 1 次（冷启动）…"
    compose_base run --rm migrate > /tmp/rehearsal_migrate_1st.log 2>&1
    tail -2 /tmp/rehearsal_migrate_1st.log
    head_rev="$(compose_base run --rm --no-deps migrate alembic heads 2>/dev/null | awk 'NR==1{print $1}')"
    ver1="$(compose_infra run --rm --no-deps -e PGPASSWORD=rehearsal-postgres-pass --entrypoint '' postgres psql -h postgres -U qqlab -d qqlab -tAc 'SELECT version_num FROM alembic_version;' | tr -d '[:space:]')"
    echo "[rehearsal]    alembic head=${head_rev} 实际=${ver1}"
    echo "[rehearsal]    迁移第 2 次（幂等校验）…"
    compose_base run --rm migrate > /tmp/rehearsal_migrate_2nd.log 2>&1
    ver2="$(compose_infra run --rm --no-deps -e PGPASSWORD=rehearsal-postgres-pass --entrypoint '' postgres psql -h postgres -U qqlab -d qqlab -tAc 'SELECT version_num FROM alembic_version;' | tr -d '[:space:]')"
    tables="$(compose_infra run --rm --no-deps -e PGPASSWORD=rehearsal-postgres-pass --entrypoint '' postgres psql -h postgres -U qqlab -d qqlab -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" | tr -d '[:space:]')"
    echo "[rehearsal]    alembic_version=${ver2} 表数=${tables}"
    [ -n "$head_rev" ] && [ "$ver1" = "$head_rev" ] && [ "$ver2" = "$head_rev" ] \
        && [ "${tables:-0}" -gt 0 ] 2>/dev/null \
        || { echo "[rehearsal] ✗ 迁移校验失败（期望 ver1=ver2=head[${head_rev:-?}]，表数>0；实际 ${ver1}/${ver2}/${tables}）" >&2; exit 1; }
    echo "[rehearsal] ⑥ 迁移幂等冷启动通过（2 次均到 head=${head_rev}，${tables} 表）"

    # 7. 镜像（pull 优先；失败回退本地已有镜像）
    compose_base --profile qlib pull \
        && echo "[rehearsal] ⑦ 镜像 pull 完成（${IMAGE_TAG}）" \
        || echo "[rehearsal] ⑦ ! pull 失败，回退本地镜像（docker.io 不稳时可接受）"

    # 8. 起生产栈（模式 B 本体 + 演练 Traefik）
    compose_base --profile qlib up -d
    echo "[rehearsal] ⑧ 栈已起，等待健康检查…"
    wait_healthy "${PROJ}-casdoor-1"
    wait_healthy "${PROJ}-backend-1"
    wait_healthy "${PROJ}-qlib-server-1"
    wait_healthy "${PROJ}-qlib-redis-1"

    # 9. 经 Traefik 的验证探针（等价于生产切换清单 §5.3 的 1/6/7 项）
    echo "[rehearsal] ⑨ Traefik 探针："
    curl -sk --resolve api.rehearsal.test:443:127.0.0.1 https://api.rehearsal.test/api/v1/health/live | head -c 120; echo
    curl -sk --resolve api.rehearsal.test:443:127.0.0.1 https://api.rehearsal.test/api/v1/health/ready | head -c 300; echo
    curl -s --resolve qlib.rehearsal.test:9711:127.0.0.1 'http://qlib.rehearsal.test:9711/socket.io/?EIO=4&transport=polling' | head -c 80; echo
    curl -skI --resolve app.rehearsal.test:443:127.0.0.1 https://app.rehearsal.test/ | head -3
    echo "[rehearsal] ✓ up 完成（详细验证表见 docs/stage9/03 与 stage7/03 §5.4 表 A）"
}

cmd_status() {
    compose_infra ps
    compose_base --profile qlib ps
    echo "--- 探针 ---"
    curl -sk --resolve api.rehearsal.test:443:127.0.0.1 https://api.rehearsal.test/api/v1/health/ready; echo
}

cmd_down() {
    compose_base --profile qlib down
    compose_infra down
    # 解除 dev casdoor 与演练网络的历史连接（若早期版本 connect 过）
    docker network disconnect "$NET" qqlab-casdoor-1 2>/dev/null || true
    echo "[rehearsal] ✓ 已停（数据卷保留；重跑 rehearsal_up.sh up 恢复）"
}

cmd_purge() {
    compose_base --profile qlib down -v
    compose_infra down -v
    docker network disconnect "$NET" qqlab-casdoor-1 2>/dev/null || true
    rm -rf deploy/rehearsal/certs
    echo "[rehearsal] ✓ 已完全清理（卷与证书已删）"
}

case "${1:-}" in
    up) cmd_up ;;
    status) cmd_status ;;
    down) cmd_down ;;
    purge) cmd_purge ;;
    *) echo "用法: $0 {up|status|down|purge}" >&2; exit 2 ;;
esac
