#!/usr/bin/env bash
# 一键复种（阶段 8 · F 项，关闭 R7-5）：
#   ① make qlib-data（幂等）→ ② dataset 导入任务（校验目录 + 登记台账 + 回填数据集快照）
#   → ③ e2e 锚点（项目 smoke / 因子 s6-ma20-ic / 模型 s6-reuse-lgb / 回测行）
#
# CI 的 e2e 前置与 dev 栈事故恢复（pg 卷重置后）走**同一个入口**：
#   scripts/seed_dev.sh           # dev 全量（需 .env / 栈在跑；COMPUTE_BACKEND=qlib 时自动拉起 qlib profile）
#   scripts/seed_dev.sh --ci      # CI/stub：跳过 qlib-data，缺目录时伪造最小数据目录（无外网、无 qlib-server）
#   scripts/seed_dev.sh --skip-qlib-data   # 只跳第 ① 步
#   scripts/seed_dev.sh --skip-import      # 只跳第 ② 步（数据集已在时可省）
#   scripts/seed_dev.sh --skip-anchors     # 只跳第 ③ 步
#
# 环境变量：
#   SEED_API_BASE   API 根（默认 http://localhost:${HOST_PORT_API:-8000}/api/v1）
#   SEED_JOB_TIMEOUT  单个任务等待上限秒数（默认 600）
#
# 限流纪律（5/min/IP）：全程只用 1 次 mock 登录（后续全部复用 Cookie），
# 与 e2e/冒烟错峰执行。
set -euo pipefail
cd "$(dirname "$0")/.."

SKIP_QLIB_DATA=0
SKIP_IMPORT=0
SKIP_ANCHORS=0
FABRICATE=0

for arg in "$@"; do
    case "$arg" in
        --ci) SKIP_QLIB_DATA=1; FABRICATE=1 ;;
        --skip-qlib-data) SKIP_QLIB_DATA=1 ;;
        --skip-import) SKIP_IMPORT=1 ;;
        --skip-anchors) SKIP_ANCHORS=1 ;;
        -h | --help)
            sed -n '2,20p' "$0"
            exit 0
            ;;
        *) echo "[seed] 未知参数: $arg" >&2; exit 2 ;;
    esac
done

API="${SEED_API_BASE:-http://localhost:${HOST_PORT_API:-8000}/api/v1}"
JOB_TIMEOUT="${SEED_JOB_TIMEOUT:-600}"
export API JOB_TIMEOUT

log() { echo "[seed] $*"; }
die() { echo "[seed] ✗ $*" >&2; exit 1; }

# ---------------------------------------------------------------- 0. 栈就绪
log "等待 backend 就绪（$API/health/ready）..."
ready=0
for _ in $(seq 1 90); do
    if curl -sf "$API/health/ready" >/dev/null 2>&1; then ready=1; break; fi
    sleep 2
done
[ "$ready" -eq 1 ] || die "backend 未就绪 —— 先 make dev / scripts/dev_up.sh（或检查 HOST_PORT_API）"

# ---------------------------------------------------------------- 1. qlib 数据
if [ "$SKIP_QLIB_DATA" -eq 0 ]; then
    log "① make qlib-data（幂等，已存在则跳过下载）"
    make qlib-data
else
    log "① 跳过 qlib-data（--ci / --skip-qlib-data）"
fi

# ---------------------------------------------------------------- 2. 数据集导入
if [ "$SKIP_IMPORT" -eq 1 ]; then
    log "② 跳过 dataset 导入（--skip-import）"
else
    # COMPUTE_BACKEND=qlib 时 probe 走 qlib-server：把 qlib profile 拉起（幂等）
    if grep -Eq '^COMPUTE_BACKEND=qlib' .env 2>/dev/null; then
        if docker compose --profile qlib ps --status running --services 2>/dev/null | grep -qx qlib-server; then
            log "② qlib-server 已在运行"
        else
            log "② COMPUTE_BACKEND=qlib：拉起 qlib profile（qlib-server + rabbitmq-init）"
            docker compose --profile qlib up -d
        fi
    fi

    if [ "$FABRICATE" -eq 1 ]; then
        log "② 伪造最小数据目录（CI：calendars + instruments，缺失才写，不覆盖真实数据）"
        # 在 worker 容器内跑（挂 qlib_data 卷 rw；脚本见 scripts/fabricate_ci_data.py）
        if docker compose ps --status running --services 2>/dev/null | grep -qx worker; then
            docker compose exec -T worker python /scripts/fabricate_ci_data.py
        else
            docker compose run --rm --no-deps -T worker python /scripts/fabricate_ci_data.py
        fi
    fi

    log "② 入队 dataset 导入（种子模式：幂等 upsert 数据源/台账/数据集）"
    # stdout 首行是 JSON {"kind","job_id","org"}（enqueue_backtest_smoke.py；"跟踪"走 stderr）
    JOB_LINE=$(docker compose exec -T backend python /scripts/enqueue_backtest_smoke.py dataset_import 2>/dev/null | head -n1)
    JOB_ID=$(printf '%s' "$JOB_LINE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])')
    # 等待在 ③ 里做（/jobs 需鉴权：复用 ③ 的那 1 次登录，省限流预算）
    export SEED_IMPORT_JOB_ID="$JOB_ID"
    log "② dataset_import 已入队 $JOB_ID（等待在 ③ 中复用登录进行）"
fi

# ---------------------------------------------------------------- 3. e2e 锚点
if [ "$SKIP_ANCHORS" -eq 1 ]; then
    log "③ 跳过 e2e 锚点（--skip-anchors）"
    if [ -n "${SEED_IMPORT_JOB_ID:-}" ]; then
        log "③ 独立等待 dataset_import ${SEED_IMPORT_JOB_ID}（登录 1 次，/jobs 需鉴权）"
        python3 <<'PY'
import http.cookiejar
import json
import os
import sys
import time
import urllib.request

API = os.environ["API"].rstrip("/")
job_id = os.environ["SEED_IMPORT_JOB_ID"]
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
req = urllib.request.Request(
    API + "/auth/mock/enter",
    data=json.dumps({"profile": "admin", "redirect_to": "/"}).encode(),
    method="POST",
    headers={"Content-Type": "application/json"},
)
with opener.open(req, timeout=30) as resp:
    json.load(resp)

deadline = time.time() + int(os.environ.get("JOB_TIMEOUT", "600"))
job = {}
while time.time() < deadline:
    with opener.open(f"{API}/jobs/{job_id}", timeout=30) as resp:
        job = json.load(resp)["data"]
    if job["status"] in ("succeeded", "failed", "canceled"):
        break
    time.sleep(2)
print(f"    … dataset_import {job_id[:8]} {job.get('status')} error={job.get('error')}")
if job.get("status") != "succeeded":
    raise SystemExit(1)
print("[seed] ② 数据集导入 succeeded")
PY
    fi
else
    log "③ 复种 e2e 锚点（mock admin 单次登录 + CSRF 双提交）"
    python3 <<'PY'
"""e2e 锚点复种：项目 smoke / 因子 s6-ma20-ic / 模型 s6-reuse-lgb / 回测行。全程幂等。"""

from __future__ import annotations

import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = os.environ["API"].rstrip("/")
JOB_TIMEOUT = int(os.environ.get("JOB_TIMEOUT", "600"))
COST = {"commission_rate": 0.0003, "slippage_value": 10.0, "impact_rate_per_million": 0.0001}
WIN_START, WIN_END = "2018-01-01", "2019-12-31"


class ApiError(Exception):
    def __init__(self, status: int, code: int, message: str) -> None:
        super().__init__(f"[{status} code={code}] {message}")
        self.status, self.code, self.message = status, code, message


class Client:
    def __init__(self) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.request("POST", "/auth/mock/enter", {"profile": "admin", "redirect_to": "/"})
        self.csrf = next(c.value for c in self.jar if c.name == "qqlab_csrf")

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            API + urllib.parse.quote(path, safe="/?&=%.:-_"),
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("X-CSRF-Token", getattr(self, "csrf", ""))  # 首次请求无会话 cookie → CSRF 中间件豁免
        try:
            with self.opener.open(req, timeout=120) as resp:
                envelope = json.load(resp)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                err = json.loads(raw)
            except ValueError:
                raise ApiError(exc.code, -1, raw.decode(errors="replace")[:200]) from None
            raise ApiError(exc.code, err.get("code", -1), err.get("message", "?")) from None
        assert envelope["code"] == 0, envelope
        return envelope["data"]

    def wait_job(self, job_id: str, label: str) -> dict:
        deadline = time.time() + JOB_TIMEOUT
        job: dict = {}
        while time.time() < deadline:
            job = self.request("GET", f"/jobs/{job_id}")
            if job["status"] in ("succeeded", "failed", "canceled"):
                break
            time.sleep(2)
        if job.get("status") != "succeeded":
            raise SystemExit(f"{label} 任务未成功: {job.get('status')} error={job.get('error')}")
        print(f"    ✓ {label} succeeded ({job_id[:8]})")
        return job


def pick(items: list[dict], name: str) -> dict | None:
    return next((i for i in items if i.get("name") == name and not i.get("deleted_at")), None)


def main() -> int:
    c = Client()
    me = c.request("GET", "/me")
    print(f"[seed] 登录 {me['username']} org={me['org_id']}（本次唯一一次 auth 命中）")

    # ---- 第 ② 步的导入任务：借本次登录等待（/jobs 需鉴权，不另花限流预算） ----
    import_job = os.environ.pop("SEED_IMPORT_JOB_ID", "")
    if import_job:
        print(f"    … 等待 dataset_import {import_job[:8]}")
        c.wait_job(import_job, "dataset_import")
        print("[seed] ② 数据集导入 succeeded")

    # ---- 数据集（第 ② 步产物；--skip-import 时要求已存在） ----
    datasets = c.request("GET", "/datasets?page_size=100")["items"]
    ds = next(
        (d for d in datasets if d.get("status") == "active" and d.get("start_date")),
        None,
    )
    if ds is None:
        raise SystemExit(
            "无带日期范围的活跃数据集 —— 先跑第 ② 步（dataset 导入）"
            "；全新环境需 qlib-data 或 --ci 伪造目录"
        )
    print(f"[seed] 数据集: {ds['name']} {ds['start_date']}~{ds['end_date']}")

    # ---- 项目 ----
    projects = c.request("GET", "/projects?page_size=100")["items"]
    project = pick(projects, "smoke")
    if project is None:
        project = c.request("POST", "/projects", {"name": "smoke"})
        print("[seed] 项目 smoke 已创建")
    else:
        print("[seed] 项目 smoke 已存在")

    # ---- 因子 ----
    factors = c.request("GET", "/factors?page_size=100")["items"]
    factor = pick(factors, "s6-ma20-ic")
    if factor is None:
        factor = c.request(
            "POST",
            "/factors",
            {
                "project_id": project["id"],
                "name": "s6-ma20-ic",
                "expression": "Mean($close, 20) / $close - 1",
            },
        )
        print("[seed] 因子 s6-ma20-ic 已创建")
    else:
        print("[seed] 因子 s6-ma20-ic 已存在")

    # ---- 模型（e2e 05 只开训练弹窗，不提交训练） ----
    models = c.request("GET", "/models?page_size=100")["items"]
    model = pick(models, "s6-reuse-lgb")
    if model is None:
        model = c.request(
            "POST",
            "/models",
            {
                "project_id": project["id"],
                "dataset_id": ds["id"],
                "name": "s6-reuse-lgb",
                "algo": "lgb",
                "factor_ids": [factor["id"]],
            },
        )
        print("[seed] 模型 s6-reuse-lgb 已创建")
    else:
        print("[seed] 模型 s6-reuse-lgb 已存在")

    # ---- 回测行（e2e 07 打开首行详情，必须有 succeeded 行） ----
    backtests = c.request("GET", "/backtests?page_size=100")["items"]
    done = [b for b in backtests if b.get("job_status") == "succeeded"]
    pending = [b for b in backtests if b.get("job_status") in ("queued", "running")]
    if done:
        print(f"[seed] 已有 succeeded 回测 {len(done)} 条，跳过提交")
    elif pending:
        c.wait_job(pending[0]["job_id"], "backtest(已有队列任务)")
    else:
        strategies = c.request("GET", "/strategies?page_size=100")["items"]
        strategy = next((s for s in strategies if s.get("signal_source") == "rule"), None)
        if strategy is None:
            strategy = c.request(
                "POST",
                "/strategies",
                {"project_id": project["id"], "name": "seed-momentum", "signal_source": "rule", "lookback": 20},
            )
            print("[seed] 策略 seed-momentum 已创建")
        bt = c.request(
            "POST",
            "/backtests",
            {
                "strategy_id": strategy["id"],
                "dataset_id": ds["id"],
                "universe": "csi300",
                "start_date": WIN_START,
                "end_date": WIN_END,
                "topk": 5,
                "max_instruments": 50,
                "cost_config": COST,
            },
        )
        print(f"[seed] 回测已提交 {bt['id'][:8]}")
        c.wait_job(bt["job_id"], "backtest")

    # ---- 复核：四个锚点齐了才算复种完成 ----
    items = {
        "project": pick(c.request("GET", "/projects?page_size=100")["items"], "smoke"),
        "factor": pick(c.request("GET", "/factors?page_size=100")["items"], "s6-ma20-ic"),
        "model": pick(c.request("GET", "/models?page_size=100")["items"], "s6-reuse-lgb"),
    }
    items["backtest"] = next(
        (b for b in c.request("GET", "/backtests?page_size=100")["items"] if b.get("job_status") == "succeeded"),
        None,
    )
    missing = [k for k, v in items.items() if not v]
    if missing:
        raise SystemExit(f"锚点缺失: {missing}")
    print("[seed] ③ 锚点齐备: project=smoke factor=s6-ma20-ic model=s6-reuse-lgb backtest=succeeded")
    return 0


sys.exit(main())
PY
fi

log "✓ 复种完成（项目 smoke / 因子 s6-ma20-ic / 模型 s6-reuse-lgb / 数据集 + 回测行）"
