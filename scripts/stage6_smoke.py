"""Stage 6 live smoke — 合规与可验证性补齐全链路：
legal 索引 → 审计 CSV 导出（二次确认/审计留痕）→ universe 股票池（正/负例）→
因子计算落库（IC 预览 + 四标注）→ csi300 回测 + 报告/持仓导出 → 训练复用因子值
（正例 payload/data_range/审计 + 负例 400/1005）→ RBAC 抽查。

用法: python3 stage6_smoke.py [--e2e]
  （栈已在 :8000 运行、AUTH_PROVIDER=mock、COMPUTE_BACKEND=qlib、worker 已重启加载阶段 6 代码）
  --e2e  额外跑 frontend 的 Playwright 冒烟（需要 :3000 前端在跑；登录限流 5 次/分钟，
         e2e 内部用共享 storageState，整套登录命中 ≤4，紧随本脚本再跑也安全）

登录限流注意: RATE_LIMIT_LOGIN_PER_MIN=5（/api/v1/auth/* 每分钟每 IP）。
本脚本只用 admin + viewer 两个 profile（各 2 次命中，共 4 ≤ 5），不引入第三个 profile。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar

RUN = time.strftime("%m%d%H%M%S")

BASE = "http://localhost:8000/api/v1"
PASS, FAIL = 0, 0


def ok(msg: str) -> None:
    global PASS
    PASS += 1
    print(f"  ✅ {msg}")


def bad(msg: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  ❌ {msg}")


class ApiError(Exception):
    def __init__(self, status: int, code: int, message: str):
        super().__init__(f"[{status} code={code}] {message}")
        self.status, self.code, self.message = status, code, message


class Client:
    def __init__(self, profile: str):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )
        data = self.request("POST", "/auth/mock/enter", {"profile": profile})
        self.user = data
        self.csrf = next(c.value for c in self.jar if c.name == "qqlab_csrf")

    def request(self, method: str, path: str, body=None, expect_error=False):
        url = BASE + urllib.parse.quote(path, safe="/?&=%.:-_")
        payload = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=payload, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("X-CSRF-Token", getattr(self, "csrf", ""))
        try:
            with self.opener.open(req, timeout=120) as resp:
                envelope = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                envelope = json.loads(raw)
            except Exception:
                raise ApiError(e.code, -1, raw.decode(errors="replace")[:200]) from None
            err = ApiError(e.code, envelope.get("code", -1), envelope.get("message", "?"))
            if expect_error:
                return err
            raise err from None
        assert envelope["code"] == 0, envelope
        return envelope["data"]

    def text(self, method: str, path: str, timeout: int = 300) -> str:
        """流式 CSV 端点（导出）：2xx 返回原始文本（保留 BOM），否则按信封抛 ApiError。"""
        url = BASE + urllib.parse.quote(path, safe="/?&=%.:-_")
        req = urllib.request.Request(url, method=method)
        req.add_header("X-CSRF-Token", getattr(self, "csrf", ""))
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                envelope = json.loads(raw)
            except Exception:
                raise ApiError(e.code, -1, raw.decode(errors="replace")[:200]) from None
            raise ApiError(e.code, envelope.get("code", -1), envelope.get("message", "?")) from None


def expect_error(fn, status, code, label):
    try:
        fn()
        bad(f"{label} —— 期望失败却成功了")
    except ApiError as e:
        if e.status == status and (code is None or e.code == code):
            ok(f"{label} → {e.status} code={e.code} {e.message[:60]}")
        else:
            bad(f"{label} —— 期望 {status}/code={code}，实际 {e.status}/code={e.code}: {e.message[:80]}")


def wait_terminal(client: Client, job_id: str, timeout: int = 600, label: str = "job"):
    deadline = time.time() + timeout
    job = None
    while time.time() < deadline:
        job = client.request("GET", f"/jobs/{job_id}")
        if job["status"] in ("succeeded", "failed", "canceled"):
            return job
        print(f"    … {label} {job_id[:8]} {job['status']}", flush=True)
        time.sleep(2)
    return job


COST = {"commission_rate": 0.0003, "slippage_value": 10.0, "impact_rate_per_million": 0.0001}
# 计算/回测/训练统一只做 2018-2019 小窗口（csi300，690 只中 683 可用；避开全市场破产下限）
WIN_START, WIN_END = "2018-01-01", "2019-12-31"


def main() -> int:
    admin = Client("admin")
    ok(f"admin 登录: {admin.user['username']} org={admin.user['org_name']}")

    # ---------------------------------------------------------- 0. 队列排空（旧消息）
    idle_deadline = time.time() + 180
    running = queued = -1
    while time.time() < idle_deadline:
        running = admin.request("GET", "/jobs?status=running&page_size=5")["total"]
        queued = admin.request("GET", "/jobs?status=queued&page_size=5")["total"]
        if running == 0 and queued == 0:
            break
        print(f"    … 等待队列排空 (running={running} queued={queued})", flush=True)
        time.sleep(3)
    ok(f"队列就绪: running={running} queued={queued}")

    # ---------------------------------------------------------- 1. 合规文件索引（切片⑦）
    print("\n—— 1. 合规文件（/legal meta 驱动） ——")
    meta = admin.request("GET", "/legal/meta")
    codes = {m["code"] for m in meta}
    if {"terms", "risk", "disclaimer"} <= codes and all(
        m.get("title") and m.get("version") and m.get("effective_at") for m in meta
    ):
        ok(f"legal/meta: {len(meta)} 篇，codes={sorted(codes)}，标题/版本/生效日期齐全")
    else:
        bad(f"legal/meta 异常: {meta}")
    terms = admin.request("GET", "/legal/terms")
    if terms.get("code") == "terms" and len(terms.get("content", "")) > 100:
        ok(f"legal/terms: v{terms['version']} 生效 {terms['effective_at']}，正文 {len(terms['content'])} 字符")
    else:
        bad(f"legal/terms 异常: {terms}")
    expect_error(
        lambda: admin.request("GET", "/legal/not-a-doc"),
        404, None, "未知合规文档 → 404",
    )

    # ---------------------------------------------------------- 2. 审计 CSV 导出（切片2）
    print("\n—— 2. 审计导出（confirm 闸门 + 审计留痕） ——")
    expect_error(
        lambda: admin.text("GET", "/audit-logs/export"),
        400, 1007, "审计导出无 confirm → 400/1007",
    )
    audit_csv = admin.text("GET", "/audit-logs/export?confirm=true")
    lines = audit_csv.strip().split("\n")
    if lines[0] == "created_at,action,resource_type,resource_id,outcome,actor_username,ip,user_agent,request_id,detail":
        ok(f"审计 CSV: 表头正确，{len(lines)} 行（含导出前存量 {admin.request('GET', '/audit-logs?page_size=1')['total']} 条）")
    else:
        bad(f"审计 CSV 表头异常: {lines[0][:120]}")
    if any(",auth.login," in ln for ln in lines):
        ok("审计 CSV 含 auth.login 明细行（detail 为紧凑 JSON）")
    else:
        bad("审计 CSV 未找到 auth.login 行")
    exported = admin.request("GET", "/audit-logs?action=audit.export&page_size=5")
    if exported["total"] >= 1:
        ok(f"audit.export 审计留痕: total={exported['total']}")
    else:
        bad("audit.export 未记入审计日志")

    # ---------------------------------------------------------- 3. 资源准备（项目/数据集/策略）
    print("\n—— 3. 资源准备 ——")
    datasets = admin.request("GET", "/datasets?page_size=100")
    ds = next((d for d in datasets["items"] if d["status"] == "active" and d.get("start_date")), None)
    if ds:
        ok(f"数据集: {ds['name']} {ds['start_date']}~{ds['end_date']}（{ds.get('license_ref') or '无授权引用'}）")
    else:
        bad("无可用数据集（需先导入 dev cn_data）")
        print(f"\n合计: {PASS} 通过 / {FAIL} 失败")
        return 1
    projects = admin.request("GET", "/projects?page_size=50")
    proj = next((p for p in projects["items"] if not p.get("deleted_at")), None) or projects["items"][0]
    ok(f"项目: {proj['name']}")

    strat = admin.request("POST", "/strategies", {
        "project_id": proj["id"], "name": f"s6-smoke-{RUN}", "signal_source": "rule", "lookback": 20,
    })
    ok(f"规则策略: {strat['id'][:8]}")

    # universe 负例（schema 通过但池文件不存在 → 422/1011，不排队）
    expect_error(
        lambda: admin.request("POST", "/backtests", {
            "strategy_id": strat["id"], "dataset_id": ds["id"],
            "universe": "csi999", "cost_config": COST,
        }),
        422, 1011, "未知股票池 csi999 → 422/1011",
    )

    # ---------------------------------------------------------- 4. 因子计算（切片5）
    print("\n—— 4. 因子计算（IC 预览 + 对象存储落库） ——")
    viewer = Client("viewer")
    ok(f"viewer 登录（限流窗口内第 4 次 auth 命中）: {viewer.user['username']}")

    factor = admin.request("POST", "/factors", {
        "project_id": proj["id"], "name": f"s6-smoke-{RUN}",
        "expression": "Mean($close, 20) / $close - 1",
    })
    fid = factor["id"]
    ok(f"因子: {fid[:8]}")
    expect_error(
        lambda: viewer.request("POST", f"/factors/{fid}/compute", {
            "dataset_id": ds["id"], "universe": "csi300",
            "start_date": WIN_START, "end_date": WIN_END,
        }),
        403, 1002, "viewer 提交因子计算 → 403/1002",
    )
    receipt = admin.request("POST", f"/factors/{fid}/compute", {
        "dataset_id": ds["id"], "universe": "csi300",
        "start_date": WIN_START, "end_date": WIN_END,
    })
    job = wait_terminal(admin, receipt["job_id"], timeout=600, label="factor.compute")
    if job and job["status"] == "succeeded":
        ok(f"因子计算 succeeded: job={receipt['job_id'][:8]}")
    else:
        bad(f"因子计算未成功: {job}")

    runs = admin.request("GET", f"/factors/{fid}/compute-runs")
    run = runs["items"][0] if runs.get("items") else None
    if run and run["job_status"] == "succeeded":
        m, dr = run.get("metrics", {}), run.get("data_range", {})
        ok(f"计算记录: run={run['id'][:8]} ic_mean={m.get('ic_mean')} ic_ir={m.get('ic_ir')} "
           f"coverage={m.get('coverage')} {m.get('n_days')}日×{m.get('n_instruments')}只")
        if dr.get("universe") == "csi300" and dr.get("source", {}).get("vendor") and dr.get("limitations") and dr.get("version"):
            ok(f"四标注: universe={dr['universe']} vendor={dr['source']['vendor']} version={dr['version']}")
        else:
            bad(f"计算记录四标注不全: {dr}")
        if run.get("values_uri") and run.get("ic_uri"):
            ok("对象存储落库: values_uri + ic_uri 均非空")
        else:
            bad(f"对象存储 URI 缺失: values_uri={run.get('values_uri')} ic_uri={run.get('ic_uri')}")
    else:
        bad(f"计算记录缺失或未成功: {run}")
        run = None

    curve = admin.request("GET", f"/factors/{fid}/compute-runs/{run['id']}/ic-curve")
    if curve.get("total", 0) >= 100 and len(curve.get("points", [])) >= 100:
        ok(f"IC 曲线: total={curve['total']} points={len(curve['points'])} downsampled={curve.get('downsampled')}")
    else:
        bad(f"IC 曲线点数异常: total={curve.get('total')} points={len(curve.get('points', []))}")

    # ---------------------------------------------------------- 5. csi300 回测 + 导出（切片3+4）
    print("\n—— 5. csi300 回测 + 报告/持仓导出 ——")
    bt = admin.request("POST", "/backtests", {
        "strategy_id": strat["id"], "dataset_id": ds["id"], "universe": "csi300",
        "start_date": WIN_START, "end_date": WIN_END,
        "topk": 5, "max_instruments": 50, "cost_config": COST,
    })
    bt_job = wait_terminal(admin, bt["job_id"], timeout=600, label="backtest")
    if bt_job and bt_job["status"] == "succeeded":
        ok(f"回测 succeeded: backtest={bt['id'][:8]} universe=csi300 {WIN_START}~{WIN_END}")
    else:
        bad(f"回测未成功: {bt_job}")
    detail = admin.request("GET", f"/backtests/{bt['id']}")
    dr = detail.get("data_range", {})
    if dr.get("universe") == "csi300":
        ok(f"回测 data_range.universe=csi300（engine={dr.get('engine')} n_days={dr.get('n_days')}）")
    else:
        bad(f"回测 data_range.universe 异常: {dr}")

    expect_error(
        lambda: admin.text("GET", f"/backtests/{bt['id']}/export?format=csv&section=report"),
        400, 1007, "报告导出无 confirm → 400/1007",
    )
    report = admin.text("GET", f"/backtests/{bt['id']}/export?format=csv&section=report&confirm=true")
    rlines = report.strip().split("\n")
    if rlines[0].lstrip("\ufeff") == "section,key,value" and report.startswith("\ufeff"):
        ok(f"报告 CSV: BOM + 表头正确，{len(rlines)} 行")
    else:
        bad(f"报告 CSV 表头/BOM 异常: {report[:80]!r}")
    if any(ln.startswith("disclaimer,limitations,") for ln in rlines) and any(
        ln.startswith("data_range,source.vendor,") for ln in rlines
    ):
        ok("报告 CSV 含 data_range,source.vendor 与 disclaimer,limitations 行")
    else:
        bad("报告 CSV 缺四标注关键行")

    positions = admin.text("GET", f"/backtests/{bt['id']}/export?format=csv&section=positions&confirm=true")
    plines = positions.strip().split("\n")
    if plines[0] == "date,instrument,shares" and len(plines) > 1:
        ok(f"持仓 CSV: 表头正确，{len(plines)} 行（含逐日快照）")
    else:
        bad(f"持仓 CSV 异常: {positions[:80]!r}")
    bt_exports = admin.request("GET", "/audit-logs?action=backtest.export&page_size=10")
    if bt_exports["total"] >= 2:
        ok(f"backtest.export 审计留痕: total={bt_exports['total']}")
    else:
        bad(f"backtest.export 留痕不足: total={bt_exports['total']}")

    # ---------------------------------------------------------- 6. 训练复用因子值（切片6）
    print("\n—— 6. 训练复用因子值（opt-in，无记录不静默回退） ——")
    f_norun = admin.request("POST", "/factors", {
        "project_id": proj["id"], "name": f"s6-norun-{RUN}",
        "expression": "Mean($close, 10) / $close - 1",
    })
    m_norun = admin.request("POST", "/models", {
        "project_id": proj["id"], "dataset_id": ds["id"],
        "name": f"s6-norun-{RUN}", "algo": "lgb", "factor_ids": [f_norun["id"]],
    })
    expect_error(
        lambda: admin.request("POST", f"/models/{m_norun['id']}/train", {
            "reuse_factor_values": True, "universe": "csi300", "max_instruments": 50,
            "split": {"train": [WIN_START, "2019-06-28"], "valid": ["2019-07-01", WIN_END]},
        }),
        400, 1005, "无计算记录 + reuse → 400/1005（不静默回退）",
    )

    m = admin.request("POST", "/models", {
        "project_id": proj["id"], "dataset_id": ds["id"],
        "name": f"s6-reuse-{RUN}", "algo": "lgb", "factor_ids": [fid],
    })
    t = admin.request("POST", f"/models/{m['id']}/train", {
        "reuse_factor_values": True, "universe": "csi300", "max_instruments": 50,
        "split": {"train": [WIN_START, "2019-06-28"], "valid": ["2019-07-01", WIN_END]},
    })
    job_payload = admin.request("GET", f"/jobs/{t['job_id']}")["payload"]
    srcs = job_payload.get("factor_value_sources") or []
    if job_payload.get("reuse_factor_values") is True and len(srcs) == 1 and srcs[0].get("run_id") and srcs[0].get("values_uri"):
        ok(f"训练 payload: reuse=True + factor_value_sources=[run={srcs[0]['run_id'][:8]} uri…]")
    else:
        bad(f"训练 payload 异常: {job_payload}")
    t_job = wait_terminal(admin, t["job_id"], timeout=600, label="train.reuse")
    if t_job and t_job["status"] == "succeeded":
        ok(f"复用训练 succeeded: job={t['job_id'][:8]}（qlib 真实路径）")
    else:
        bad(f"复用训练未成功: {t_job}")
    trs = admin.request("GET", f"/training-runs?model_id={m['id']}&page_size=5")
    tr = trs["items"][0] if trs.get("items") else None
    tr_dr = (tr or {}).get("data_range", {})
    if tr and tr_dr.get("reuse_factor_values") is True and tr_dr.get("factor_value_runs") == [srcs[0]["run_id"]]:
        ok(f"data_range: reuse_factor_values=True factor_value_runs={[r[:8] for r in tr_dr['factor_value_runs']]}")
    else:
        bad(f"训练 data_range 异常: {tr_dr}")
    if tr and tr.get("metrics", {}).get("train_ic") is not None:
        mm = tr["metrics"]
        ok(f"训练指标: train_ic={mm.get('train_ic')} valid_ic={mm.get('valid_ic')} n_train={mm.get('n_train_samples')}")
    else:
        bad(f"训练指标缺失: {(tr or {}).get('metrics')}")
    t_audit = admin.request("GET", "/audit-logs?action=train.submit&page_size=10")
    latest = next((a for a in t_audit["items"] if (a.get("detail") or {}).get("reuse_factor_values") is True), None)
    if latest:
        ok(f"train.submit 审计: detail.reuse_factor_values=True run={latest['resource_id'][:8]}")
    else:
        bad("train.submit 审计未记录 reuse_factor_values=True")

    # ---------------------------------------------------------- 7. 汇总
    print(f"\n合计: {PASS} 通过 / {FAIL} 失败")

    if "--e2e" in sys.argv:
        print("\n—— 8. Playwright e2e 冒烟（frontend:e2e） ——")
        code = subprocess.call(["pnpm", "e2e"], cwd="frontend" if __import__("os").path.isdir("frontend") else ".")
        if code == 0:
            ok("Playwright e2e 全部通过")
        else:
            bad(f"Playwright e2e 失败（exit={code}）")

    print(f"\n最终: {PASS} 通过 / {FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
