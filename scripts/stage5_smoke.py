"""Stage 5 live smoke — 真实 cn_data：建模型(因子快照) → qlib 训练 → 双信号回测 →
曲线/四标注 → 任务中心（日志增量 / queued 取消 / running 取消 / 重试）→ 负例。

用法: python3 stage5_smoke.py   （栈已在 :8000 运行、AUTH_PROVIDER=mock、worker 已重启加载阶段 5 代码）
"""
from __future__ import annotations

import json
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
        print(f"    … {label} {job['status']} {job['progress']}%", flush=True)
        time.sleep(2)
    return job


COST = {"commission_rate": 0.0003, "slippage_value": 10.0, "impact_rate_per_million": 0.0001}


def main() -> int:
    admin = Client("admin")
    ok(f"admin 登录: {admin.user['username']} org={admin.user['org_name']}")

    # ---------------------------------------------------------- 0. 队列排空（旧消息）
    idle_deadline = time.time() + 180
    while time.time() < idle_deadline:
        running = admin.request("GET", "/jobs?status=running&page_size=5")["total"]
        queued = admin.request("GET", "/jobs?status=queued&page_size=5")["total"]
        if running == 0 and queued == 0:
            break
        print(f"    … 等待队列排空 (running={running} queued={queued})", flush=True)
        time.sleep(3)
    ok(f"队列就绪: running={running} queued={queued}")

    # ---------------------------------------------------------- 1. 算法目录
    catalog = admin.request("GET", "/models/catalog")
    if [c["algo"] for c in catalog] == ["lgb"] and catalog[0]["available"]:
        ok("模型目录: 仅 lgb 且 available=true（D5-0a 静态目录，偏差见 06-risks §3）")
    else:
        bad(f"模型目录异常: {catalog}")

    # ---------------------------------------------------------- 2. 数据集（复用阶段 4 已导入的）
    datasets = admin.request("GET", "/datasets?page_size=100")
    ds = next(
        (d for d in datasets["items"] if d["status"] == "active" and d.get("start_date")),
        None,
    )
    if ds is None:
        bad("未找到 active 数据集 —— 先跑 stage4_smoke.py 完成导入")
        return 1
    ok(f"数据集: {ds['name'][:28]} {ds['start_date']}~{ds['end_date']} 标的={ds['instrument_count']}")

    # ---------------------------------------------------------- 3. 项目 + 因子
    projects = admin.request("GET", "/projects?page=1&page_size=5")
    proj = projects["items"][0]
    f1 = admin.request("POST", "/factors", {
        "project_id": proj["id"], "name": f"5日动量-{RUN}",
        "expression": "Ref($close, 5) / $close - 1",
    })
    f2 = admin.request("POST", "/factors", {
        "project_id": proj["id"], "name": f"20日均线比-{RUN}",
        "expression": "Mean($close, 20) / $close - 1",
    })
    f3 = admin.request("POST", "/factors", {
        "project_id": proj["id"], "name": f"10日动量-{RUN}",
        "expression": "Ref($close, 10) / $close - 1",
    })
    fdup = admin.request("POST", "/factors", {
        "project_id": proj["id"], "name": f"10日动量副本-{RUN}",
        "expression": "Ref($close, 10) / $close - 1",
    })
    ok(f"创建 3+1 因子: {f1['name']} / {f2['name']} / {f3['name']} / 副本")

    # ---------------------------------------------------------- 4. 模型 A + 因子快照
    model_a = admin.request("POST", "/models", {
        "project_id": proj["id"], "dataset_id": ds["id"],
        "name": f"LGB 动量增强-{RUN}", "factor_ids": [f1["id"], f2["id"]],
    })
    if len(model_a["factor_snapshot"]) == 2 and model_a["status"] == "draft":
        ok(f"建模型 A: 快照 2 因子 status={model_a['status']}")
    else:
        bad(f"模型 A 快照异常: {model_a['factor_snapshot']}")

    admin.request("PATCH", f"/factors/{f1['id']}", {"expression": "Ref($close, 6) / $close - 1"})
    detail = admin.request("GET", f"/models/{model_a['id']}")
    snap_exprs = [s["expression"] for s in detail["factor_snapshot"]]
    if "Ref($close, 5) / $close - 1" in snap_exprs and "Ref($close, 6)" not in " ".join(snap_exprs):
        ok("因子改表达式后模型快照不变（衔接点 #3 可复现性）")
    else:
        bad(f"快照被污染: {snap_exprs}")

    expect_error(
        lambda: admin.request("POST", "/models", {
            "project_id": proj["id"], "dataset_id": ds["id"],
            "name": f"重复表达式-{RUN}", "factor_ids": [f3["id"], fdup["id"]],
        }),
        400, None, "模型内重复因子表达式 → 400",
    )
    expect_error(
        lambda: admin.request("POST", "/models", {
            "project_id": proj["id"], "dataset_id": ds["id"],
            "name": f"坏算法-{RUN}", "algo": "xgboost", "factor_ids": [f1["id"]],
        }),
        400, None, "未知算法 → 400",
    )

    # ---------------------------------------------------------- 5. 策略（双信号源 + 发布）
    strat_rule = admin.request("POST", "/strategies", {
        "project_id": proj["id"], "name": f"动量 Top5-{RUN}", "lookback": 20,
    })
    strat_model = admin.request("POST", "/strategies", {
        "project_id": proj["id"], "name": f"LGB 因子策略-{RUN}",
        "signal_source": "model", "model_id": model_a["id"],
    })
    if strat_rule["signal_source"] == "rule" and strat_model["model_id"] == model_a["id"]:
        ok(f"建策略: rule(lookback=20) + model(绑 A)")
    else:
        bad(f"策略信号源异常: {strat_rule} {strat_model}")

    expect_error(
        lambda: admin.request("POST", "/strategies", {
            "project_id": proj["id"], "name": f"缺模型-{RUN}", "signal_source": "model",
        }),
        422, None, "model 源缺 model_id → 422",
    )
    expect_error(
        lambda: admin.request("POST", f"/strategies/{strat_rule['id']}/publish"),
        400, None, "发布未 confirm → 400",
    )
    pub = admin.request("POST", f"/strategies/{strat_rule['id']}/publish?confirm=true")
    if pub["visibility"] == "public" and pub["version"] == 2:
        ok(f"发布策略: visibility={pub['visibility']} v{pub['version']}")
    else:
        bad(f"发布异常: {pub['visibility']} v{pub['version']}")

    # ---------------------------------------------------------- 6. 负例（前置校验）
    expect_error(
        lambda: admin.request("POST", "/backtests", {
            "strategy_id": strat_model["id"], "dataset_id": ds["id"],
            "max_instruments": 50, "cost_config": COST,
        }),
        409, None, "模型信号但无成功训练 → 409（不排队才失败）",
    )
    bad_cost = dict(COST)
    del bad_cost["slippage_value"]
    expect_error(
        lambda: admin.request("POST", "/backtests", {
            "strategy_id": strat_rule["id"], "dataset_id": ds["id"], "cost_config": bad_cost,
        }),
        422, None, "费用三件套缺滑点 → 422",
    )

    # ---------------------------------------------------------- 7. 训练 A（显式切分 + 小窗口）
    receipt = admin.request("POST", f"/models/{model_a['id']}/train", {
        "split": {"train": ["2014-01-01", "2017-12-29"], "valid": ["2018-01-01", "2019-12-31"]},
        "max_instruments": 50,
    })
    job_a = receipt["job_id"]
    if receipt["split"]["train"] == ["2014-01-01", "2017-12-29"]:
        ok(f"训练 A 入队: job={job_a[:8]} run={receipt['training_run_id'][:8]}")
    else:
        bad(f"切分回显异常: {receipt}")

    payload = admin.request("GET", f"/jobs/{job_a}")["payload"]
    if (
        payload.get("model_id") == model_a["id"]
        and len(payload.get("factors", [])) == 2
        and payload["split"]["valid"] == ["2018-01-01", "2019-12-31"]
        and payload.get("target")
    ):
        ok("job payload 固化执行快照（factors/split/target）")
    else:
        bad(f"payload 快照不完整: keys={sorted(payload)}")

    expect_error(
        lambda: admin.request("POST", f"/models/{model_a['id']}/train", {}),
        409, None, "同模型并发训练 → 409",
    )

    runs = admin.request("GET", f"/training-runs?model_id={model_a['id']}&page_size=10")
    if receipt["training_run_id"] in {r["id"] for r in runs["items"]}:
        ok(f"read-your-writes: 提交后立即可见训练记录 (total={runs['total']})")
    else:
        bad(f"训练记录不可见: {runs}")

    # 日志增量（since_seq）——训练进行中抓两轮快照
    seen: dict[int, str] = {}
    logs_ok = False
    for _ in range(40):
        page = admin.request("GET", f"/jobs/{job_a}/logs?since_seq=0&limit=500")
        if page["items"]:
            seqs = [it["seq"] for it in page["items"]]
            assert page["next_seq"] == max(seqs), (page["next_seq"], seqs)
            for it in page["items"]:
                seen[it["seq"]] = it["message"]
            if page["status"] in ("succeeded", "failed", "canceled") and len(seen) >= 3:
                logs_ok = True
                break
        if page["status"] in ("succeeded", "failed", "canceled") and page["items"]:
            logs_ok = True
            break
        time.sleep(2)
    contig = sorted(seen) == list(range(min(seen), max(seen) + 1)) if seen else False
    if logs_ok and contig:
        ok(f"增量日志: {len(seen)} 条 seq 连续 ({min(seen)}..{max(seen)}) 例: {seen[min(seen)][:40]!r}")
    else:
        bad(f"增量日志异常: n={len(seen)} contiguous={contig}")

    job = wait_terminal(admin, job_a, timeout=900, label="train A")
    if job and job["status"] == "succeeded" and job["progress"] == 100:
        ok(f"训练 A 完成: {job['status']} 尝试={job['attempts']}")
    else:
        bad(f"训练 A 未成功: status={job and job['status']} error={job and job.get('error')}")
        return 1

    run = admin.request("GET", f"/training-runs/{receipt['training_run_id']}")
    m = run["metrics"]
    dr = run["data_range"]
    if (all(k in m for k in ("train_ic", "valid_ic", "valid_ir")) and run["artifact_uri"]
            and m.get("n_valid_days", 0) > 0):
        ok(f"训练指标: train_ic={m['train_ic']:.4f} valid_ic={m['valid_ic']:.4f} "
           f"valid_ir={m['valid_ir']:.4f} valid_days={m['n_valid_days']} engine={m.get('engine')}")
    else:
        bad(f"指标/artifact 缺失或日频IC未启用(n_valid_days): metrics={m} artifact={run['artifact_uri']}")
    src = dr.get("source") or {}
    if src.get("vendor") and src.get("license_ref") and dr.get("limitations"):
        ok(f"四标注(训练): {src['vendor']} · {src['license_ref']} · limitations={str(dr['limitations'])[:48]}…")
    else:
        bad(f"训练四标注缺失: data_range={dr}")
    model_now = admin.request("GET", f"/models/{model_a['id']}")
    if model_now["status"] == "trained" and model_now["last_run"]:
        ok(f"模型状态 → {model_now['status']}")
    else:
        bad(f"模型状态异常: {model_now['status']}")

    # ---------------------------------------------------------- 8. 规则信号回测
    bt_rule = admin.request("POST", "/backtests", {
        "strategy_id": strat_rule["id"], "dataset_id": ds["id"],
        "benchmark": "SH000300",
        "start_date": "2018-01-01", "end_date": "2019-12-31",
        "topk": 5, "max_instruments": 50, "cost_config": COST,
    })
    job_bt = wait_terminal(admin, bt_rule["job_id"], timeout=900, label="bt rule")
    if job_bt and job_bt["status"] == "succeeded":
        ok(f"规则回测完成: job={bt_rule['job_id'][:8]}")
    else:
        bad(f"规则回测失败: {job_bt and job_bt['status']} error={job_bt and job_bt.get('error')}")
        return 1
    bt_rule = admin.request("GET", f"/backtests/{bt_rule['id']}")
    dr = bt_rule["data_range"]
    m_bt = bt_rule["metrics"]
    if m_bt.get("total_return") is not None and m_bt.get("cost_applied"):
        ok(f"规则回测指标: total_return={m_bt['total_return']:.4f} sharpe={m_bt.get('sharpe'):.3f} cost_applied.commission={m_bt['cost_applied'].get('commission_rate')}")
    else:
        bad(f"指标/费用回写缺失: {bt_rule['metrics']} {dr}")
    if dr.get("signal_source") == "rule" and bt_rule.get("limitations"):
        ok(f"信号源/局限标注: {dr['signal_source']} / {str(bt_rule['limitations'])[:40]}…")
    else:
        bad(f"rule 标注缺失: {dr}")
    curve = admin.request("GET", f"/backtests/{bt_rule['id']}/curve")
    if curve["points"] and curve["points"][0][0] <= curve["points"][-1][0]:
        ok(f"净值曲线: {len(curve['points'])} 点 total={curve['total']} 首尾={[round(p[1], 4) for p in (curve['points'][0], curve['points'][-1])]}")
    else:
        bad(f"曲线为空: {curve}")

    # ---------------------------------------------------------- 9. 模型信号回测
    bt_model = admin.request("POST", "/backtests", {
        "strategy_id": strat_model["id"], "dataset_id": ds["id"],
        "benchmark": "SH000300",
        "start_date": "2018-01-01", "end_date": "2019-12-31",
        "topk": 5, "max_instruments": 50, "cost_config": COST,
    })
    job_bt2 = wait_terminal(admin, bt_model["job_id"], timeout=900, label="bt model")
    if job_bt2 and job_bt2["status"] == "succeeded":
        ok(f"模型回测完成: job={bt_model['job_id'][:8]}")
    else:
        bad(f"模型回测失败: {job_bt2 and job_bt2['status']} error={job_bt2 and job_bt2.get('error')}")
        return 1
    bt_model = admin.request("GET", f"/backtests/{bt_model['id']}")
    dr2 = bt_model["data_range"]
    if dr2.get("signal_source") == "model" and dr2.get("training_run_id") == receipt["training_run_id"]:
        ok(f"模型信号标注: training_run_id={dr2['training_run_id'][:8]}（运行时口径 = 最近成功件，D5-8）")
    else:
        bad(f"模型信号标注缺失: {dr2}")
    curve2 = admin.request("GET", f"/backtests/{bt_model['id']}/curve")
    if curve2["points"]:
        ok(f"模型回测曲线: {len(curve2['points'])} 点")
    else:
        bad("模型回测曲线为空")

    # ---------------------------------------------------------- 10. 任务中心：取消/重试
    model_b = admin.request("POST", "/models", {
        "project_id": proj["id"], "dataset_id": ds["id"],
        "name": f"取消靶子-{RUN}", "factor_ids": [f2["id"], f3["id"]],
    })
    model_c = admin.request("POST", "/models", {
        "project_id": proj["id"], "dataset_id": ds["id"],
        "name": f"重试靶子-{RUN}", "factor_ids": [f3["id"]],
    })
    big_split = {"train": ["2010-01-01", "2016-12-31"], "valid": ["2017-01-01", "2019-12-31"]}
    job_b = admin.request("POST", f"/models/{model_b['id']}/train",
                          {"split": big_split, "max_instruments": 600})["job_id"]
    # 等 B 进入 running，再提交 C（concurrency=1 → C 必然排队）
    deadline = time.time() + 120
    while time.time() < deadline:
        if admin.request("GET", f"/jobs/{job_b}")["status"] == "running":
            break
        time.sleep(1)
    job_c = admin.request("POST", f"/models/{model_c['id']}/train",
                          {"split": big_split, "max_instruments": 50})["job_id"]

    cancel_c = admin.request("POST", f"/jobs/{job_c}/cancel")
    if cancel_c["status"] == "canceled":
        ok(f"queued 取消（原子 CAS）: job={job_c[:8]} → {cancel_c['status']}")
    else:
        bad(f"queued 取消未命中 CAS: {cancel_c}")
    expect_error(
        lambda: admin.request("POST", f"/jobs/{job_c}/cancel"),
        409, None, "终态再取消 → 409",
    )

    cancel_b = admin.request("POST", f"/jobs/{job_b}/cancel")
    if cancel_b["status"] == "cancel_requested":
        ok(f"running 取消（缓存标记协作式）: job={job_b[:8]} → {cancel_b['status']}")
    else:
        bad(f"running 取消异常: {cancel_b}")
    job_b_final = wait_terminal(admin, job_b, timeout=600, label="cancel B")
    if job_b_final and job_b_final["status"] == "canceled":
        ok(f"worker 协作落终态: B → {job_b_final['status']}")
    else:
        bad(f"running 取消未生效: {job_b_final and job_b_final['status']}")

    retry = admin.request("POST", f"/jobs/{job_c}/retry")
    detail_retry = admin.request("GET", f"/jobs/{retry['id']}")
    if (retry["status"] == "queued" and detail_retry["payload"].get("retry_of") == job_c
            and detail_retry["payload"].get("factors")):
        ok(f"重试: 复制 payload + retry_of → 新任务 {retry['id'][:8]}")
    else:
        bad(f"重试异常: {retry} payload={sorted(detail_retry['payload'])}")
    job_c2 = wait_terminal(admin, retry["id"], timeout=600, label="retry C")
    if job_c2 and job_c2["status"] == "succeeded":
        ok(f"重试任务实际执行成功: {job_c2['status']} 进度={job_c2['progress']}")
    else:
        bad(f"重试任务未成功: {job_c2 and job_c2['status']} error={job_c2 and job_c2.get('error')}")
    runs_c = admin.request("GET", f"/training-runs?model_id={model_c['id']}&page_size=5")["items"]
    if runs_c and runs_c[0]["job_id"] == job_c2["id"] and runs_c[0]["job_status"] == "succeeded":
        ok(f"重试后 run 改链当前任务: run→{runs_c[0]['job_id'][:8]} job_status=succeeded（UI 不再 join 旧任务终态）")
    else:
        bad(f"run 重链异常: {[(r['job_id'][:8], r['job_status']) for r in runs_c]}")

    # ---------------------------------------------------------- 11. 负例（权限 / 确认 / 绑定）
    viewer = Client("viewer")
    expect_error(
        lambda: viewer.request("POST", f"/models/{model_a['id']}/train", {}),
        403, 1002, "viewer 提交训练 → 403",
    )
    expect_error(
        lambda: viewer.request("POST", f"/jobs/{job_c}/cancel"),
        403, 1002, "viewer 取消任务 → 403",
    )
    viewer_runs = viewer.request("GET", f"/training-runs?model_id={model_a['id']}")
    ok(f"viewer 只读训练记录可用: total={viewer_runs['total']}")
    expect_error(
        lambda: admin.request("DELETE", f"/models/{model_a['id']}"),
        400, None, "删除模型未 confirm → 400",
    )
    expect_error(
        lambda: admin.request("DELETE", f"/models/{model_a['id']}?confirm=true"),
        409, None, "删除被策略绑定的模型 → 409",
    )

    print(f"\n合计: {PASS} 通过 / {FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
