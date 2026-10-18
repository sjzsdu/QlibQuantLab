"""Stage 7 live smoke — Casdoor OIDC 授权码全链路（PKCE S256 / JWKS RS256 / 组织角色落地）。

前提:
  1. docker compose --profile casdoor up -d casdoor        # init_data.json 已种子（幂等）
  2. backend 切 casdoor env（临时覆盖，不改 .env）:
       docker compose -f docker-compose.yml -f docker-compose.casdoor-smoke.yml up -d backend
  3. python3 scripts/stage7_smoke.py
  还原: docker compose up -d backend（覆盖文件保留作最小环境清单，见 deploy/casdoor/README.md）

模拟浏览器: 每个身份一个独立 Cookie 罐 —— IdP 先 UI 会话登录（POST /api/login type=login），
再按平台签发的 authorize URL 参数换授权码（type=code + PKCE challenge 原样透传，
verifier 由平台按 state 派生，冒烟不接触）。回调 code+state 回平台完成交换+JWKS 验签。

登录限流（RATE_LIMIT_LOGIN_PER_MIN=5，路径 /api/v1/auth*；无会话按 IP 共桶、有会话按 user:<id> 分桶）:
  轮1: admin+viewer 成功登录 = 4 命中(IP)
  轮2(+61s): norole+unknown fail-closed = 4 命中(IP)
  轮3(+61s): error= 流 2 + 坏 state 1 = 3 命中(IP)；logout 带 admin 会话 → user 桶 1 命中
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlsplit

RUN_STARTED = time.time()

API = "http://localhost:8000/api/v1"
IDP = "http://localhost:8001"
APP = "app-qqlab"
ORG = "qqlab"
REDIR = "http://localhost:3000/api/v1/auth/callback"

PASS, FAIL = 0, 0


def ok(msg: str) -> None:
    global PASS
    PASS += 1
    print(f"  ✅ {msg}")


def bad(msg: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  ❌ {msg}")


class _StopRedirect(urllib.request.HTTPRedirectHandler):
    """不跟随重定向：302 以 HTTPError 抛出（headers 可读 Location / Set-Cookie）。"""

    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN201
        return None


def _sh(cmd: list[str]) -> str:
    """docker 子进程查询（需在仓库根目录运行 —— 依赖 compose 项目上下文）。"""
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, check=False
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


class Http:
    """最小 HTTP 客户端：手管 Cookie —— 302 响应上的 Set-Cookie 也必须抓到。"""

    def __init__(self, base: str) -> None:
        self.base = base
        self.cookies: dict[str, str] = {}
        self._opener = urllib.request.build_opener(_StopRedirect)

    def request(self, method: str, path: str, body: dict | None = None, timeout: int = 60):
        url = path if path.startswith("http") else self.base + path
        headers: dict[str, str] = {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        # 双提交 CSRF：写请求自动带 qqlab_csrf 头（与 Cookie 同值）
        if method not in ("GET", "HEAD", "OPTIONS") and "qqlab_csrf" in self.cookies:
            headers["X-CSRF-Token"] = self.cookies["qqlab_csrf"]
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with self._opener.open(req, timeout=timeout) as resp:
                status, hdrs, raw = resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as e:
            status, hdrs, raw = e.code, e.headers, e.read()
        self._eat_cookies(hdrs)
        return status, hdrs, raw

    def _eat_cookies(self, hdrs) -> None:  # noqa: ANN001
        for sc in hdrs.get_all("Set-Cookie") or []:
            pair, _, _rest = sc.partition(";")
            name, _, val = pair.partition("=")
            # Starlette delete_cookie 发的是带引号的空值 `name=""` —— 剥引号后视为清除
            name, val = name.strip(), val.strip().strip('"')
            if val:
                self.cookies[name] = val
            else:
                self.cookies.pop(name, None)

    def api(self, method: str, path: str, body: dict | None = None):
        """平台信封端点 → (status, envelope dict)。"""
        status, _hdrs, raw = self.request(method, path, body)
        try:
            env = json.loads(raw)
        except ValueError:
            env = {"code": -1, "message": raw[:200].decode(errors="replace")}
        return status, env


def expect(status: int, want: int, label: str, *, code: int | None = None, env=None) -> None:
    if status != want or (code is not None and (env or {}).get("code") != code):
        bad(f"{label} —— 期望 {want}/code={code}，实际 {status}/code={(env or {}).get('code')}: "
            f"{(env or {}).get('message', '')[:90]}")
    else:
        detail = f" code={(env or {}).get('code')}" if code is not None else ""
        msg = ((env or {}).get("message") or "")[:60]
        ok(f"{label} → {status}{detail} {msg}")


# ---------------------------------------------------------------- IdP 浏览器模拟
def idp_ui_login(idp: Http, user: str, password: str) -> bool:
    """UI 会话登录（POST /api/login type=login）→ 建立 Casdoor SSO 会话。"""
    status, _h, raw = idp.request("POST", "/api/login", {
        "type": "login", "username": user, "password": password,
        "organization": ORG, "application": APP, "signinMethod": "Password",
        "rememberMe": False,
    })
    try:
        env = json.loads(raw)
    except ValueError:
        return False
    return status == 200 and env.get("status") == "ok"


def idp_code(idp: Http, authorize_url: str, user: str, password: str) -> str:
    """按平台签发的 authorize URL 参数向 IdP 换授权码（type=code + PKCE challenge 透传）。"""
    p = dict(urllib.parse.parse_qsl(urlsplit(authorize_url).query))
    q = urllib.parse.urlencode({
        "type": "code",
        "clientId": p["client_id"],
        "responseType": "code",
        "redirectUri": p["redirect_uri"],
        "scope": p["scope"],
        "state": p["state"],
        "code_challenge_method": p["code_challenge_method"],
        "code_challenge": p["code_challenge"],
    })
    status, _h, raw = idp.request("POST", f"/api/login?{q}", {
        "username": user, "password": password, "organization": ORG,
        "application": APP, "signinMethod": "Password", "type": "code",
    })
    env = json.loads(raw)
    if status != 200 or env.get("status") != "ok" or not isinstance(env.get("data"), str):
        raise RuntimeError(f"IdP 换码失败: {env}")
    return env["data"]


def begin_login(api: Http) -> tuple[str, str]:
    """GET /auth/login → (authorize_url, state) —— 平台限流 1 命中。"""
    status, env = api.api("GET", "/auth/login")
    assert status == 200 and env.get("code") == 0, f"/auth/login 失败: {status} {env}"
    return env["data"]["url"], env["data"]["state"]


def login(api: Http, idp: Http, user: str, password: str) -> tuple[int, dict | None, object]:
    """完整登录：/auth/login(1命中) → IdP 换码 → /auth/callback(1命中)。"""
    url, state = begin_login(api)
    code = idp_code(idp, url, user, password)
    status, hdrs, raw = api.request("GET", f"/auth/callback?{urllib.parse.urlencode({'code': code, 'state': state})}")
    env = None
    try:
        env = json.loads(raw)
    except ValueError:
        pass
    return status, env, hdrs


class RoundClock:
    """限流错峰：轮与轮之间 ≥61s（IP 桶固定窗口 60s）。"""

    def __init__(self) -> None:
        self._last = time.time()

    def next_round(self) -> None:
        wait = 61 - (time.time() - self._last)
        if wait > 0:
            print(f"    … 限流错峰等待 {wait:.0f}s", flush=True)
            time.sleep(wait)
        self._last = time.time()


def main() -> int:
    clock = RoundClock()

    # ------------------------------------------------------ 轮 1：成功登录 + RBAC
    print("—— 轮 1. admin / viewer 成功登录（2×2=4 限流命中） ——")
    admin_api, admin_idp = Http(API), Http(IDP)
    assert idp_ui_login(admin_idp, "smoke-admin", "Smoke-Dev-Admin-1234"), "IdP UI 会话登录失败"
    url, state = begin_login(admin_api)
    if url.startswith(f"{IDP}/login/oauth/authorize?") and "code_challenge=" in url and \
            dict(urllib.parse.parse_qsl(urlsplit(url).query))["state"] == state:
        ok(f"authorize URL: PKCE S256 + state 绑定（{url.split('?')[0].replace(IDP, 'idp')}）")
    else:
        bad(f"authorize URL 异常: {url}")

    code = idp_code(admin_idp, url, "smoke-admin", "Smoke-Dev-Admin-1234")
    status, hdrs, raw = admin_api.request(
        "GET", f"/auth/callback?{urllib.parse.urlencode({'code': code, 'state': state})}")
    if status == 302 and (hdrs.get("Location") == "/" or hdrs.get("Location", "").endswith("/")):
        sc = "; ".join(hdrs.get_all("Set-Cookie") or [])
        if "qqlab_session=" in sc and "HttpOnly" in sc and "qqlab_csrf=" in sc:
            ok("admin 回调 302 → 站内相对落点 `/`，Set-Cookie: session(HttpOnly) + csrf")
        else:
            bad(f"回调 Set-Cookie 异常: {sc[:160]}")
    else:
        bad(f"admin 回调异常: {status} loc={hdrs.get('Location')} body={raw[:120]!r}")

    status, env = admin_api.api("GET", "/me")
    me = env.get("data") or {}
    if status == 200 and me.get("provider") == "casdoor" and me.get("org_id") == ORG and \
            me.get("roles") == ["admin"] and me.get("username") == "smoke-admin" and me.get("is_authenticated"):
        ok(f"/me: provider=casdoor org_id={me['org_id']} roles={me['roles']} username={me['username']} "
           f"（owner claim 直通 + RS256/JWKS 验签通过）")
    else:
        bad(f"/me 异常: {me}")

    status, env = admin_api.api("GET", "/system/info")
    info = env.get("data") or {}
    if info.get("auth_provider") == "casdoor":
        ok(f"/system/info auth_provider={info['auth_provider']}（前端显隐依据）")
    else:
        bad(f"/system/info auth_provider={info.get('auth_provider')}")

    status, env = admin_api.api("GET", "/projects?page_size=5")
    expect(status, 200, "admin 读项目（business API 会话有效）", code=0, env=env)

    status, env = admin_api.api("GET", "/audit-logs?action=auth.login&page_size=5")
    total = (env.get("data") or {}).get("total") or 0
    if total >= 1:
        ok(f"审计 auth.login 留痕: total={total}")
    else:
        bad(f"审计无 auth.login: {env}")

    viewer_api, viewer_idp = Http(API), Http(IDP)
    assert idp_ui_login(viewer_idp, "smoke-viewer", "Smoke-Dev-Viewer-1234"), "viewer IdP UI 会话登录失败"
    status, env, _h = login(viewer_api, viewer_idp, "smoke-viewer", "Smoke-Dev-Viewer-1234")
    if status == 302:
        ok("viewer 回调 302（限流窗口内第 4 次 auth 命中）")
    else:
        bad(f"viewer 回调异常: {status} {env}")
    status, env = viewer_api.api("GET", "/me")
    me = env.get("data") or {}
    if me.get("roles") == ["viewer"]:
        ok(f"viewer /me roles={me['roles']}")
    else:
        bad(f"viewer /me roles 异常: {me}")
    status, env = viewer_api.api("POST", "/projects", {"name": f"s7-denied-{int(time.time())}"})
    expect(status, 403, "viewer 写项目 → 403 拒绝（RBAC）", code=1002, env=env)

    # ------------------------------------------------------ 轮 2：fail-closed 负例
    clock.next_round()
    print("—— 轮 2. fail-closed：无角色 / 平台未知角色（2×2=4 限流命中） ——")
    for user, pwd, label in (
        ("smoke-norole", "Smoke-Dev-NoRole-1234", "无角色账号登录 → 401 fail-closed"),
        ("smoke-unknown", "Smoke-Dev-Unknown-1234", "未知角色 operator 登录 → 401 fail-closed"),
    ):
        api_h, idp_h = Http(API), Http(IDP)
        assert idp_ui_login(idp_h, user, pwd), f"{user} IdP UI 会话登录失败"
        status, env, _h = login(api_h, idp_h, user, pwd)
        expect(status, 401, label, code=1001, env=env)

    # ------------------------------------------------------ 轮 3：错误回调 / 坏 state / 登出
    clock.next_round()
    print("—— 轮 3. OIDC error 回调 + 坏 state + RP 登出回跳（3 IP 命中 + 1 user 桶） ——")
    api_h = Http(API)
    url, state = begin_login(api_h)
    status, env = api_h.api("GET", "/auth/callback?" + urllib.parse.urlencode(
        {"error": "access_denied", "error_description": "smoke denied", "state": state}))
    expect(status, 401, "回调 error=access_denied → 401", code=1001, env=env)
    # 登录失败发生在身份解析前 → 无 org 归属 → 不落租户审计表（跨租户隔离的设计），
    # 安全事件以结构化日志留存（audit_skipped_no_org，含 action/detail/ip）。
    # docker --since 需 RFC3339（本机 CLI 不支持 @epoch）；UTC 精确到本轮运行起点
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(RUN_STARTED))
    backend_id = _sh(["docker", "compose", "ps", "-q", "backend"]).strip()
    logs = _sh(["docker", "logs", "--since", since, backend_id]) if backend_id else ""
    if "audit_skipped_no_org" in logs and "auth.login_failed" in logs:
        ok("失败登录安全事件入结构化日志（audit_skipped_no_org / auth.login_failed）")
    else:
        bad(f"结构化日志未见失败登录安全事件（backend_id={backend_id!r}）")

    status, env = api_h.api("GET", "/auth/callback?code=fake&state=deadbeef")
    expect(status, 400, "坏 state → 400/1005", code=1005, env=env)

    # 登出：平台会话清理 + RP-initiated 回跳（admin 桶，1 命中）
    status, env = admin_api.api("GET", "/auth/logout?next=/login")
    redirect_to = (env.get("data") or {}).get("redirect_to", "")
    if status == 200 and redirect_to.startswith(f"{IDP}/api/logout?") and \
            "post_logout_redirect_uri=" in redirect_to and "client_id=" in redirect_to:
        ok(f"logout → Casdoor RP-initiated URL（{redirect_to.split('?')[0].replace(IDP, 'idp')}…）")
    else:
        bad(f"logout redirect_to 异常: {status} {redirect_to!r}")
    if "qqlab_session" not in admin_api.cookies:
        ok("平台会话 Cookie 已清除")
    else:
        bad("平台会话 Cookie 未清除")
    status, hdrs, _raw = admin_idp.request("GET", redirect_to)
    loc = hdrs.get("Location") or ""
    if status == 302 and loc.startswith("http://localhost:3000/login?logged_out=1"):
        ok(f"Casdoor 登出 302 → 站内登录页落地（{loc}）")
    else:
        bad(f"Casdoor 登出回跳异常: {status} loc={loc!r}")

    print(f"\n最终: {PASS} 通过 / {FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
