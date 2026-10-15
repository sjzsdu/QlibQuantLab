#!/usr/bin/env bash
# qlib 数据导入（阶段 3 决策 #3：**官方下载 + 本地 zip 两段式**，不走任何实时爬取/自造数据源）。
#
# 官方路径 = qlib 自带 GetData（pyqlib 0.9.7 镜像内已装）：
#   下载 GitHub Release 预构建 zip（数据由 Yahoo 收集，官方声明见脚本输出的 warning）
#   → 本地解压为 dump_bin 布局（features/calendars/instruments，已是 .bin，无需再 dump_bin）。
# 失败即失败：网络不可达 / 404 时给出明确指引，**降级为连通性检查**，绝不换源。
#
# 用法（compose 内）：
#   docker compose --profile qlib run --rm qlib-bootstrap
# 环境变量：
#   QLIB_DATA_ROOT     数据根（默认 /qlib_data）
#   MOCK_ORG_ID        租户目录名（默认 dev-org）
#   QLIB_REGION        cn（默认）| us
#   QLIB_DATA_NAME     qlib_data（默认，全量）| qlib_data_simple（官方样例小集合）
#   QLIB_DATA_VERSION  数据集版本（默认 latest；v2 等）
#   QLIB_DATA_SYMBOLS  >0 = 回测侧只取前 N 个标的（fetch 时截断，不动磁盘数据）
set -euo pipefail

ROOT="${QLIB_DATA_ROOT:-/qlib_data}"
ORG="${MOCK_ORG_ID:-dev-org}"
REGION="${QLIB_REGION:-cn}"
NAME="${QLIB_DATA_NAME:-qlib_data}"
VERSION="${QLIB_DATA_VERSION:-}"
SYMBOLS="${QLIB_DATA_SYMBOLS:-0}"
TARGET="${ROOT}/${ORG}/cn_data"

echo "[bootstrap] region=${REGION} name=${NAME} version=${VERSION:-latest} target=${TARGET}"

# ---- 0) 连通性前置检查（决策 #3：失败降级为连通性结论，不回退数据源） ----
# 用 python 而非 curl：slim 镜像不带 curl；下载本身走 qlib GetData（requests/urllib），也不用 curl。
if ! python - <<'PY'
import sys
import urllib.request

url = "https://github.com/SunsetWolf/qlib_dataset/releases"
try:
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=10) as resp:
        print(f"[bootstrap] precheck ok: HTTP {resp.status}", file=sys.stderr)
except Exception as exc:  # noqa: BLE001
    print(f"[bootstrap] precheck failed: {exc}", file=sys.stderr)
    sys.exit(1)
PY
then
    echo "[bootstrap] ✗ 无法访问 qlib 官方数据发布源（github.com/SunsetWolf/qlib_dataset）" >&2
    echo "  这是连通性问题，不是数据问题：请检查容器出网 / 代理 / DNS。" >&2
    echo "  平台不会改用任何未经确认的数据源（阶段 3 决策 #3）。" >&2
    exit 1
fi

# ---- 1) 官方下载（GetData.qlib_data：版本 zip → 本地解压；目标为空则无删除确认交互） ----
echo "[bootstrap] 通过 qlib 官方 GetData 下载预构建数据（Yahoo 收集，仅供研究）"
mkdir -p "${TARGET}"
python - <<PY
from qlib.tests.data import GetData

GetData().qlib_data(
    name="${NAME}",
    target_dir="${TARGET}",
    version="${VERSION}" or None,
    interval="1d",
    region="${REGION}",
    delete_old=False,   # 目标为空目录，无需删除确认（交互式 input 会挂住容器）
    exists_skip=True,   # 已有数据则跳过（幂等）
)
PY

# ---- 2) 完整性校验（dump_bin 布局三件套） ----
for d in calendars instruments features; do
    if [ ! -d "${TARGET}/${d}" ]; then
        echo "[bootstrap] ✗ 解压后缺少 ${TARGET}/${d}（zip 结构变化？核对 pyqlib 0.9.7 的 GetData）" >&2
        exit 1
    fi
done

INST_COUNT=$(wc -l < "${TARGET}/instruments/all.txt" | tr -d ' ')
CAL_DAYS=$(wc -l < "${TARGET}/calendars/day.txt" | tr -d ' ')

echo "[bootstrap] ✓ 完成：${TARGET}"
echo "[bootstrap]   instruments=${INST_COUNT}  calendar_days=${CAL_DAYS}"
if [ "${SYMBOLS}" -gt 0 ] 2>/dev/null; then
    echo "[bootstrap]   回测将按 QLIB_DATA_SYMBOLS=${SYMBOLS} 只取前 ${SYMBOLS} 个标的（磁盘仍是全量）"
fi
echo "[bootstrap] 下一步：docker compose --profile qlib exec backend python /scripts/enqueue_dataset_import.py"
