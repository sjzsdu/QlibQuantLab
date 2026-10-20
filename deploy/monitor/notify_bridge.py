#!/usr/bin/env python3
"""notify_bridge —— Alertmanager webhook → 多通知通道的配置驱动桥（阶段 9 · D 项）。

设计（接口 + 配置驱动，与平台 ports&adapters 同一哲学）：
  · 「接口」= Alertmanager 的标准 webhook 报文契约（POST /notify，JSON）；
  · 「实现」= 每个通道一个翻译/发送函数；
  · 「配置驱动」= 启用哪些通道纯看环境变量 —— 给 URL 即启用，代码零改动：

    NOTIFY_WECOM_URL       企业微信机器人 webhook（完整 URL）
    NOTIFY_DINGTALK_URL    钉钉机器人 webhook URL
    NOTIFY_DINGTALK_SECRET 钉钉加签密钥（可选；配了就 timestamp+sign）
    NOTIFY_FEISHU_URL      飞书自定义机器人 webhook URL
    NOTIFY_EMAIL_HOST/PORT/USER/PASSWORD/FROM/TO   SMTP 邮件通道（TO 逗号分隔）
    NOTIFY_SINK_DIR        本地留档目录（默认 /var/lib/qqlab-notify/sink）——
                           始终启用：每批告警落一份 JSON 回执文件（实测/审计凭据）
    NOTIFY_BIND / NOTIFY_PORT   监听地址（默认 0.0.0.0:9099）

运行（零新镜像：跑在 backend 运行镜像里，纯 stdlib）：
  python3 deploy/monitor/notify_bridge.py
  健康：GET /healthz → {"status":"ok","channels":[…]}
  回执：GET /receipts → sink 目录文件列表

返回码语义：所有通道失败 → 502（让 Alertmanager 按重试策略重发）；至少一个成功 → 200。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import smtplib
import time
import urllib.error
import urllib.request
from email.mime.text import MIMEText
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SINK_DIR = os.environ.get("NOTIFY_SINK_DIR", "/var/lib/qqlab-notify/sink")
BIND = os.environ.get("NOTIFY_BIND", "0.0.0.0")
PORT = int(os.environ.get("NOTIFY_PORT", "9099"))
HTTP_TIMEOUT = 10


def _fmt_text(payload: dict) -> str:
    """Alertmanager webhook → 人类可读文本（各 IM 通道共用一份措辞）。"""
    status = payload.get("status", "?")
    lines = [f"[Qqlab 告警] {status.upper()}"]
    for alert in payload.get("alerts", []):
        labels = alert.get("labels", {})
        ann = alert.get("annotations", {})
        name = labels.get("alertname", "?")
        sev = labels.get("severity", "-")
        summary = ann.get("summary", "")
        starts = alert.get("startsAt", "")[:19]
        lines.append(f"· {sev} {name}: {summary} (since {starts})")
        extra = {k: v for k, v in labels.items() if k not in ("alertname", "severity")}
        if extra:
            lines.append(f"  labels: {json.dumps(extra, ensure_ascii=False)}")
    return "\n".join(lines)


def _post_json(url: str, body: dict) -> None:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:  # noqa: S310 - URL 来自运维配置
        if resp.status >= 300:
            raise RuntimeError(f"HTTP {resp.status}")


def send_wecom(payload: dict) -> str:
    url = os.environ["NOTIFY_WECOM_URL"]
    _post_json(url, {"msgtype": "markdown", "markdown": {"content": _fmt_text(payload)}})
    return "wecom ok"


def send_dingtalk(payload: dict) -> str:
    url = os.environ["NOTIFY_DINGTALK_URL"]
    secret = os.environ.get("NOTIFY_DINGTALK_SECRET", "")
    if secret:  # 加签模式：timestamp + HMAC-SHA256(url) base64url
        ts = str(round(time.time() * 1000))
        string_to_sign = f"{ts}\n{secret}"
        mac = hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha256).digest()
        sign = base64.urlsafe_b64encode(mac).decode().rstrip("=")
        url = f"{url}&timestamp={ts}&sign={sign}"
    _post_json(url, {"msgtype": "markdown", "markdown": {"text": _fmt_text(payload)}})
    return "dingtalk ok"


def send_feishu(payload: dict) -> str:
    url = os.environ["NOTIFY_FEISHU_URL"]
    _post_json(url, {"msg_type": "text", "content": {"text": _fmt_text(payload)}})
    return "feishu ok"


def send_email(payload: dict) -> str:
    host = os.environ["NOTIFY_EMAIL_HOST"]
    port = int(os.environ.get("NOTIFY_EMAIL_PORT", "587"))
    user = os.environ.get("NOTIFY_EMAIL_USER", "")
    password = os.environ.get("NOTIFY_EMAIL_PASSWORD", "")
    sender = os.environ["NOTIFY_EMAIL_FROM"]
    receivers = [x.strip() for x in os.environ["NOTIFY_EMAIL_TO"].split(",") if x.strip()]
    alerts = payload.get("alerts", [])
    first = alerts[0].get("labels", {}).get("alertname", "alert") if alerts else "alert"
    msg = MIMEText(_fmt_text(payload), "plain", "utf-8")
    msg["Subject"] = f"[Qqlab] {payload.get('status', '?').upper()}: {first}"
    msg["From"] = sender
    msg["To"] = ", ".join(receivers)
    with smtplib.SMTP(host, port, timeout=HTTP_TIMEOUT) as smtp:
        smtp.starttls()
        if user:
            smtp.login(user, password)
        smtp.sendmail(sender, receivers, msg.as_string())
    return "email ok"


def send_sink(payload: dict) -> str:
    """本地留档（始终启用）：每批告警一份带回执时间戳的 JSON —— 实测/审计凭据。"""
    os.makedirs(SINK_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    status = payload.get("status", "unknown")
    name = (payload.get("alerts") or [{}])[0].get("labels", {}).get("alertname", "batch")
    path = os.path.join(SINK_DIR, f"{ts}-{status}-{name}.json")
    receipt = {"received_at": ts, "channel": "sink", "payload": payload}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(receipt, fh, ensure_ascii=False, indent=2)
    return f"sink ok ({os.path.basename(path)})"


def enabled_channels() -> list:
    checks = [
        ("wecom", send_wecom, "NOTIFY_WECOM_URL"),
        ("dingtalk", send_dingtalk, "NOTIFY_DINGTALK_URL"),
        ("feishu", send_feishu, "NOTIFY_FEISHU_URL"),
        ("email", send_email, "NOTIFY_EMAIL_HOST"),
    ]
    return [(name, fn) for name, fn, env in checks if os.environ.get(env)]


class Handler(BaseHTTPRequestHandler):
    server_version = "qqlab-notify-bridge/1.0"

    def _json(self, code: int, body: dict) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802 - http.server 命名约定
        if self.path == "/healthz":
            self._json(200, {"status": "ok", "channels": [n for n, _ in enabled_channels()] + ["sink"]})
        elif self.path == "/receipts":
            files = sorted(os.listdir(SINK_DIR)) if os.path.isdir(SINK_DIR) else []
            self._json(200, {"sink_dir": SINK_DIR, "receipts": files})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path != "/notify":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": f"bad payload: {exc}"})
            return

        results, failures = [], 0
        for name, fn in [("sink", send_sink), *enabled_channels()]:
            try:
                results.append({"channel": name, "result": fn(payload)})
            except (urllib.error.URLError, OSError, smtplib.SMTPException, RuntimeError) as exc:
                failures += 1
                results.append({"channel": name, "error": str(exc)[:200]})
        # 全部失败 → 502（Alertmanager 按重试策略重发）；任一成功 → 200
        self._json(502 if failures and failures == len(results) else 200, {"results": results})

    def log_message(self, fmt, *args):  # noqa: A003 - 结构化一行日志
        print(json.dumps({"bridge": "notify", "msg": fmt % args}, ensure_ascii=False), flush=True)


def main() -> None:
    os.makedirs(SINK_DIR, exist_ok=True)
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    print(
        json.dumps(
            {
                "bridge": "notify",
                "event": "start",
                "bind": f"{BIND}:{PORT}",
                "channels": [n for n, _ in enabled_channels()] + ["sink"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
