#!/usr/bin/env bash
# ============================================================================
# 构建并推送 QlibQuantLab 的四个生产镜像，供部署侧（deploy 仓库 / 本仓库
# docker-compose.prod.yml）按 tag 拉取。
#
# 构建目标与 docker-compose.prod.yml 完全一致：
#   frontend     → frontend/Dockerfile（runner 阶段；构建期注入 BACKEND_INTERNAL_URL，
#                  该值被 Next 的 rewrite 固化进产物，改了要重新构建）
#   backend      → backend/Dockerfile target runtime（Python 3.12，不含 qlib）
#   worker       → backend/Dockerfile target worker-runtime（Python 3.11 + qlib）
#   qlib-server  → qlib-server/Dockerfile
#
# 追溯与回滚（阶段 9 · A 项）：
#   · TAG 默认 = sha-<git 短 sha>[-dirty] —— 镜像与 git 提交不可分割；
#   · 工作区有未提交改动（含构建上下文里的未跟踪文件）时自动加 -dirty 后缀，
#     拒绝把脏树构建冒充成某个提交；
#   · 每次构建产出 deploy/image-manifest.json：tag / git_sha / 每镜像 digest ——
#     回滚 = 用清单里的 tag（或 digest）重新 pull + up。
#
# 用法：
#   IMAGE_PREFIX=sjzsdu scripts/build_push_images.sh                 # TAG 自动 = sha-<12>
#   IMAGE_PREFIX=sjzsdu TAG=v1.0.0 scripts/build_push_images.sh      # 显式 tag（发版）
#   IMAGE_PREFIX=sjzsdu scripts/build_push_images.sh --no-push       # 只构建不推送
#   IMAGE_PREFIX=sjzsdu scripts/build_push_images.sh --only=frontend # 只构建/推送部分镜像
#
# 环境变量：
#   IMAGE_PREFIX      镜像命名空间/仓库前缀（默认 sjzsdu；可含 registry host，
#                     如 registry.example.com/sjzsdu —— 含 "." 的首段视为私有 registry）
#   TAG               镜像标签（默认见上；显式传入时原样使用，不加 -dirty）
#   TARGET_PLATFORM   目标平台（默认 linux/amd64 —— 与 qlib-server 硬依赖一致，
#                     Apple Silicon 上交叉构建，服务器为 x86 时可直接运行）
#   RETRIES           push/pull 查询的重试次数（默认 3，间隔 5s/10s/15s ——
#                     docker.io 间歇 EOF 的实测缓解手段）
#
# 前置：push 前需 `docker login <registry>`（脚本会在推送前检查登录状态）；
#       构建用 BuildKit（compose v2 默认）；基础镜像（python:3.12/3.11/3.10-slim、
#       node:22-alpine、docker/dockerfile:1）已在本地时构建不依赖外网。
# ============================================================================
set -euo pipefail

IMAGE_PREFIX="${IMAGE_PREFIX:-sjzsdu}"
TARGET_PLATFORM="${TARGET_PLATFORM:-linux/amd64}"
RETRIES="${RETRIES:-3}"

PUSH=1
ONLY=""
for arg in "$@"; do
    case "$arg" in
        --no-push) PUSH=0 ;;
        --only=*) ONLY="${arg#--only=}" ;;
        *) echo "[images] 未知参数: $arg（支持 --no-push / --only=<name,...>）" >&2; exit 2 ;;
    esac
done

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

# ---------------------------------------------------------------- git 绑定
GIT_SHA="$(git rev-parse --short=12 HEAD)"
GIT_LONG_SHA="$(git rev-parse HEAD)"
GIT_DIRTY=0
# 脏树判定：① 已跟踪文件有未提交改动（工作区或暂存区）；
#           ② 构建上下文（backend/ frontend/ qlib-server/）里有未跟踪文件 ——
#              未跟踪文件会进镜像却不被 git sha 覆盖，同样算「不可追溯」。
git diff --quiet HEAD -- 2>/dev/null || GIT_DIRTY=1
CTX_UNTRACKED="$(git ls-files --others --exclude-standard -- backend frontend qlib-server || true)"
[ -n "${CTX_UNTRACKED}" ] && GIT_DIRTY=1

if [ -z "${TAG:-}" ]; then
    TAG="sha-${GIT_SHA}"
    [ "${GIT_DIRTY}" = "1" ] && TAG="${TAG}-dirty"
    TAG_SOURCE="auto(git)"
else
    TAG_SOURCE="explicit"
fi

ALL_IMAGES="frontend backend worker qlib-server"
if [ -n "${ONLY}" ]; then
    for n in ${ONLY//,/ }; do
        case " ${ALL_IMAGES} " in
            *" ${n} "*) ;;
            *) echo "[images] --only 含未知镜像名: ${n}（可选：${ALL_IMAGES}）" >&2; exit 2 ;;
        esac
    done
    IMAGES="${ONLY//,/ }"
else
    IMAGES="${ALL_IMAGES}"
fi

GIT_SRC="$(git config --get remote.origin.url 2>/dev/null || true)"

echo "[images] root=${REPO_ROOT}"
echo "[images] prefix=${IMAGE_PREFIX} tag=${TAG} (${TAG_SOURCE}) platform=${TARGET_PLATFORM} push=${PUSH}"
echo "[images] git=${GIT_SHA} dirty=${GIT_DIRTY}"
if [ "${GIT_DIRTY}" = "1" ]; then
    echo "[images] ⚠ 工作区不干净（未提交改动或构建上下文内未跟踪文件）—— 该镜像不可归属单一提交" >&2
    git status --short -- backend frontend qlib-server | head -10 >&2 || true
fi

# ---------------------------------------------------------------- 重试工具
retry() {
    local n=1 max=$RETRIES delay=5
    while true; do
        if "$@"; then return 0; fi
        if [ "$n" -ge "$max" ]; then
            echo "[images] ✗ 重试 ${n} 次仍失败: $*" >&2
            return 1
        fi
        echo "[images] ! 第 ${n} 次失败，${delay}s 后重试: $*" >&2
        sleep "$delay"
        n=$((n + 1)); delay=$((delay + 5))
    done
}

# ---------------------------------------------------------------- 构建
build() {
    local name="$1"; shift
    local ref="${IMAGE_PREFIX}/qqlab-${name}:${TAG}"
    echo "[images] build ${ref}"
    docker build \
        --platform "${TARGET_PLATFORM}" \
        --provenance=false \
        --label "org.opencontainers.image.revision=${GIT_LONG_SHA}" \
        --label "org.opencontainers.image.version=${TAG}" \
        ${GIT_SRC:+--label "org.opencontainers.image.source=${GIT_SRC}"} \
        -t "${ref}" "$@"
}

FAILED=""
for name in ${IMAGES}; do
    case "$name" in
        frontend)     retry build frontend --build-arg BACKEND_INTERNAL_URL=http://backend:8000 ./frontend || FAILED="$FAILED frontend" ;;
        backend)      retry build backend --target runtime ./backend || FAILED="$FAILED backend" ;;
        worker)       retry build worker --target worker-runtime ./backend || FAILED="$FAILED worker" ;;
        qlib-server)  retry build qlib-server ./qlib-server || FAILED="$FAILED qlib-server" ;;
    esac
done
if [ -n "${FAILED}" ]; then
    echo "[images] ✗ 构建失败:${FAILED}" >&2
    exit 1
fi

# ---------------------------------------------------------------- 推送前登录检查
is_dockerhub_prefix() {
    local first="${IMAGE_PREFIX%%/*}"
    case "$first" in
        *.*) return 1 ;; # 含点 = 私有 registry host
        *)   return 0 ;;
    esac
}

if [ "${PUSH}" = "1" ]; then
    # 登录软检查：只看 ~/.docker/config.json 的 auths 是否含目标 registry。
    # （不能用 `docker system info | grep Username` —— OrbStack 等发行版不打印该字段，
    #   会把已登录误判为未登录；真正的鉴权结果以 docker push 的报错为准。）
    registry_host="${IMAGE_PREFIX%%/*}"
    is_dockerhub_prefix && registry_host="https://index.docker.io/v1/"
    if ! python3 - "$registry_host" <<'PYEOF'
import json, os, sys
host = sys.argv[1]
try:
    cfg = json.load(open(os.path.expanduser("~/.docker/config.json")))
except OSError:
    sys.exit(1)
sys.exit(0 if host in cfg.get("auths", {}) or cfg.get("credsStore") else 1)
PYEOF
    then
        echo "[images] ! 未在 ~/.docker/config.json 检测到 ${registry_host} 的凭据 —— 若无登录，push 将报 unauthorized" >&2
    fi

    for name in ${IMAGES}; do
        echo "[images] push ${IMAGE_PREFIX}/qqlab-${name}:${TAG}"
        retry docker push "${IMAGE_PREFIX}/qqlab-${name}:${TAG}"
    done
fi

# ---------------------------------------------------------------- 镜像清单（追溯/回滚凭据）
MANIFEST="${REPO_ROOT}/deploy/image-manifest.json"
MANIFEST_PREV="${MANIFEST}.prev" # 同 tag 分批构建（--only）时用于合并旧清单
cp -f "${MANIFEST}" "${MANIFEST_PREV}" 2>/dev/null || true
GENERATED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
entries=""
for name in ${IMAGES}; do
    ref="${IMAGE_PREFIX}/qqlab-${name}:${TAG}"
    if [ "${PUSH}" = "1" ]; then
        digest="$(retry docker buildx imagetools inspect "${ref}" --format '{{println .Manifest.Digest}}' 2>/dev/null | head -1 || true)"
    else
        digest=""
    fi
    [ -z "${digest}" ] && digest="$(docker image inspect "${ref}" --format '{{.Id}}')"
    entry="$(printf '    "%s": { "ref": "%s", "digest": "%s" }' "${name}" "${ref}" "${digest}")"
    entries="${entries}${entry},\n"
done
entries="${entries%,\\n}"

mkdir -p "${REPO_ROOT}/deploy"
printf '{\n  "generated_at": "%s",\n  "git_sha": "%s",\n  "git_dirty": %s,\n  "tag": "%s",\n  "tag_source": "%s",\n  "target_platform": "%s",\n  "images": {\n%b\n  }\n}\n' \
    "${GENERATED_AT}" "${GIT_LONG_SHA}" "$([ "${GIT_DIRTY}" = "1" ] && echo true || echo false)" \
    "${TAG}" "${TAG_SOURCE}" "${TARGET_PLATFORM}" "${entries}" > "${MANIFEST}"

# 同 tag 合并旧清单（--only 分批构建不丢其他镜像条目）；换 tag 视为新发布从头记录
MANIFEST_PREV="${MANIFEST_PREV}" python3 - <<'PYEOF'
import json
import os

path = "deploy/image-manifest.json"
try:
    cur = json.load(open(path, encoding="utf-8"))
except (OSError, ValueError):
    raise SystemExit(0)
try:
    prev = json.load(open(os.environ["MANIFEST_PREV"], encoding="utf-8"))
except (OSError, ValueError):
    prev = {}
if prev.get("tag") == cur.get("tag"):
    cur["images"] = dict(sorted({**prev.get("images", {}), **cur.get("images", {})}.items()))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cur, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
try:
    os.remove(os.environ["MANIFEST_PREV"])
except OSError:
    pass
PYEOF
echo "[images] 镜像清单 → deploy/image-manifest.json"
if [ "${PUSH}" = "1" ]; then
    echo "[images] ✓ ${#IMAGES} 个镜像已推送：${IMAGE_PREFIX}/qqlab-{${IMAGES// /,}}:${TAG}"
    echo "[images]   部署侧拉取：IMAGE_PREFIX=${IMAGE_PREFIX} IMAGE_TAG=${TAG} docker compose -f docker-compose.prod.yml pull"
    echo "[images]   回滚：把 IMAGE_TAG 换成上一份 deploy/image-manifest.json 里的 tag/digest 后重拉"
else
    echo "[images] ✓ 已构建（--no-push，未推送）：${IMAGE_PREFIX}/qqlab-{${IMAGES// /,}}:${TAG}"
fi
