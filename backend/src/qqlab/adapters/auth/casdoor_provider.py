"""CasdoorAuthProvider —— OIDC 授权码流程 + JWKS 验签（阶段 7 实装）。

流程（与 docs/stage7/02-casdoor-integration.md 对应）：

1. ``get_login_url``：拼 Casdoor authorize URL，带 PKCE S256。
   code_verifier = base64url(HMAC-SHA256(client_secret, "qqlab-pkce:" + state)) ——
   **无状态推导**而非落缓存：``get_login_url`` 是端口契约的同步方法（无法 await
   缓存写入），推导式还天然跨 uvicorn 进程（生产 BACKEND_WORKERS=4），且攻击者
   截获回调 URL 里的 code+state 也无法推导 verifier（不知 client_secret）。
2. ``handle_callback``：用 code+verifier 换 token → JWKS 验签（RS256、exp、
   aud=client_id、iss ∈ 白名单）→ claim 归一化 → org/role 映射（fail-closed）。
3. ``verify_token``：与 mock 完全一致 —— 平台会话是自己签发的 HS256 JWT，
   IdP 令牌只在回调时用一次（阶段 1 的「IdP 令牌只留后端」承诺）。
4. ``get_logout_url``：RP-initiated logout（Casdoor ``/api/logout``）。
5. ``healthcheck``：discovery 端点可达性。

dev 拓扑（CASDOOR_INTERNAL_URL）：浏览器走宿主机映射端口（authorize/登出），
后端容器走 compose 内部服务名（token/discovery/JWKS）；两地址都进 iss 白名单 ——
Casdoor 的 iss 按请求 Host 派生，双地址下两者都可能出现在 id_token（casdoor#1622）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import httpx
import jwt as pyjwt

from qqlab.config import Settings
from qqlab.core.errors import DependencyUnavailableError, UnauthorizedError
from qqlab.core.logging import get_logger
from qqlab.core.security import decode_session_token
from qqlab.ports.auth import CurrentUser, Role
from qqlab.ports.cache import CacheProvider

logger = get_logger("qqlab.adapters.casdoor")

_JWKS_CACHE_KEY = "qqlab:auth:jwks:{issuer}"
_JWKS_TTL_SECONDS = 3600
_HTTP_TIMEOUT = 10.0
_HEALTH_TIMEOUT = 3.0
_PKCE_CONTEXT = b"qqlab-pkce:"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class CasdoorAuthProvider:
    name = "casdoor"
    IMPLEMENTED = True

    def __init__(
        self,
        settings: Settings,
        cache: CacheProvider | None = None,
        transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._cache = cache  # JWKS 缓存（可空：单测可不注入）
        self._transport = transport  # 单测注入 httpx.MockTransport（生产为 None）

    # ------------------------------------------------------------ 配置派生
    @property
    def _issuer(self) -> str:
        return self._settings.CASDOOR_ISSUER.rstrip("/")

    @property
    def _api_base(self) -> str:
        """服务端访问 IdP 的地址（token/discovery/JWKS）。"""
        internal = self._settings.CASDOOR_INTERNAL_URL.strip()
        return (internal or self._settings.CASDOOR_ISSUER).rstrip("/")

    # ---------------------------------------------------------------- PKCE
    def _code_verifier(self, state: str) -> str:
        """由 (client_secret, state) 确定性推导 —— 见模块 docstring 的理由。"""
        key = self._settings.CASDOOR_CLIENT_SECRET.encode()
        return _b64url(hmac.new(key, _PKCE_CONTEXT + state.encode(), hashlib.sha256).digest())

    @staticmethod
    def _code_challenge(verifier: str) -> str:
        return _b64url(hashlib.sha256(verifier.encode()).digest())

    # ---------------------------------------------------------------- 端口
    def get_login_url(self, state: str, redirect_to: str) -> str:
        _ = redirect_to  # OIDC 下落点由 state 持有（auth_service 的 state 缓存）
        verifier = self._code_verifier(state)
        params = {
            "client_id": self._settings.CASDOOR_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": self._settings.CASDOOR_REDIRECT_URI,
            "scope": self._settings.CASDOOR_SCOPES,
            "state": state,
            "code_challenge": self._code_challenge(verifier),
            "code_challenge_method": "S256",
        }
        return f"{self._issuer}/login/oauth/authorize?{urlencode(params)}"

    def get_logout_url(self, redirect_to: str) -> str:
        """RP-initiated logout：跳 Casdoor ``/api/logout``，登出后回站内登录页。

        与 mock 的 get_logout_url 同一契约：入参是登出后的落点（next），
        本方法负责拼 logged_out 落地页并绝对化（Casdoor 要求
        post_logout_redirect_uri 为绝对地址且已注册在应用 Redirect URLs），
        origin 取自 CASDOOR_REDIRECT_URI。
        """
        landing = f"/login?logged_out=1&next={quote(redirect_to or '/')}"
        split = urlsplit(self._settings.CASDOOR_REDIRECT_URI)
        params = {
            "post_logout_redirect_uri": f"{split.scheme}://{split.netloc}{landing}",
            "client_id": self._settings.CASDOOR_CLIENT_ID,
        }
        return f"{self._issuer}/api/logout?{urlencode(params)}"

    async def handle_callback(self, code: str, state: str) -> CurrentUser:
        if not code:
            raise UnauthorizedError("登录回调缺少授权码（code）")
        id_token = await self._exchange_code(code, state)
        claims = await self._verify_id_token(id_token)
        return self._map_identity(claims)

    async def verify_token(self, token: str) -> CurrentUser | None:
        claims = decode_session_token(token, self._settings)
        return claims.to_user() if claims else None

    async def healthcheck(self) -> bool:
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=_HEALTH_TIMEOUT) as client:
                resp = await client.get(f"{self._api_base}/.well-known/openid-configuration")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    # -------------------------------------------------------- code → token
    async def _exchange_code(self, code: str, state: str) -> str:
        data = {
            "grant_type": "authorization_code",
            "client_id": self._settings.CASDOOR_CLIENT_ID,
            "client_secret": self._settings.CASDOOR_CLIENT_SECRET,
            "code": code,
            "redirect_uri": self._settings.CASDOOR_REDIRECT_URI,
            "code_verifier": self._code_verifier(state),
        }
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(
                    f"{self._api_base}/api/login/oauth/access_token", data=data
                )
        except httpx.HTTPError as exc:
            logger.warning("casdoor_token_exchange_unreachable", extra={"error": str(exc)})
            raise DependencyUnavailableError("身份服务不可达，请稍后重试") from exc
        if resp.status_code != 200:
            logger.warning(
                "casdoor_token_exchange_failed",
                extra={"status": resp.status_code, "body": resp.text[:200]},
            )
            raise UnauthorizedError("授权码兑换失败（code 无效、已使用或已过期）")
        payload = resp.json()
        id_token = payload.get("id_token") or payload.get("access_token")
        if not id_token:
            raise UnauthorizedError("身份服务未返回 id_token")
        return str(id_token)

    # ------------------------------------------------------ JWKS 验签
    async def _fetch_jwks(self, *, force: bool = False) -> dict[str, Any]:
        key = _JWKS_CACHE_KEY.format(issuer=self._issuer)
        if not force and self._cache is not None:
            raw = await self._cache.get(key)
            if raw:
                try:
                    return json.loads(raw)
                except ValueError:
                    pass  # 缓存损坏 → 重新拉取
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=_HTTP_TIMEOUT) as client:
                resp = await client.get(f"{self._api_base}/.well-known/jwks")
        except httpx.HTTPError as exc:
            logger.warning("casdoor_jwks_unreachable", extra={"error": str(exc)})
            raise DependencyUnavailableError("身份服务不可达，请稍后重试") from exc
        if resp.status_code != 200:
            raise UnauthorizedError("无法获取身份服务签名密钥（JWKS）")
        jwks = resp.json()
        if self._cache is not None:
            await self._cache.set(key, resp.content, ttl=_JWKS_TTL_SECONDS)
        return jwks

    @staticmethod
    def _pick_key(jwks: dict[str, Any], kid: str) -> Any:
        for jwk in jwks.get("keys", []):
            if jwk.get("kid") == kid:
                return pyjwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
        return None

    async def _verify_id_token(self, id_token: str) -> dict[str, Any]:
        try:
            header = pyjwt.get_unverified_header(id_token)
        except pyjwt.PyJWTError as exc:
            raise UnauthorizedError("身份令牌格式无效") from exc
        kid = str(header.get("kid", ""))

        key = self._pick_key(await self._fetch_jwks(), kid)
        if key is None:
            # 密钥轮换：未知 kid 强制刷新一次（JWKS 缓存最长 1h）
            key = self._pick_key(await self._fetch_jwks(force=True), kid)
        if key is None:
            raise UnauthorizedError("身份令牌签名密钥未知（kid 不在 JWKS 中）")

        try:
            return pyjwt.decode(
                id_token,
                key,
                algorithms=["RS256"],
                audience=self._settings.CASDOOR_CLIENT_ID,
                issuer=self._settings.casdoor_issuers,
                options={"require": ["exp", "iss", "aud"]},
            )
        except pyjwt.ExpiredSignatureError as exc:
            raise UnauthorizedError("身份令牌已过期，请重新登录") from exc
        except pyjwt.PyJWTError as exc:
            logger.warning("casdoor_token_verify_failed", extra={"error": str(exc)})
            raise UnauthorizedError("身份令牌校验失败") from exc

    # ---------------------------------------------------- claim → 平台身份
    @staticmethod
    def _normalize_roles(raw: Any) -> list[str]:
        """Casdoor 的 roles claim 有三种形态（取决于应用 Token fields 配置）：
        字符串 / 字符串数组 / Role 对象数组（取 name）。全部归一成字符串列表。"""
        if raw is None:
            return []
        if isinstance(raw, str):
            return [raw.strip()] if raw.strip() else []
        if isinstance(raw, (list, tuple)):
            out: list[str] = []
            for item in raw:
                if isinstance(item, str):
                    if item.strip():
                        out.append(item.strip())
                elif isinstance(item, dict):
                    # 完整 JWT 格式：roles 是 Role 对象数组（含 owner/name）
                    name = item.get("name") or item.get("Name")
                    if name:
                        out.append(str(name).strip())
            return out
        return []

    def _map_identity(self, claims: dict[str, Any]) -> CurrentUser:
        settings = self._settings

        org_raw = claims.get(settings.CASDOOR_ORG_ID_CLAIM)
        if not org_raw:
            raise UnauthorizedError(
                f"身份令牌缺少组织 claim（{settings.CASDOOR_ORG_ID_CLAIM}），拒绝登录"
            )
        org_id = settings.casdoor_org_map.get(str(org_raw), str(org_raw))

        role_map = settings.casdoor_role_map
        role_names = [role_map.get(name, name) for name in self._normalize_roles(claims.get(settings.CASDOOR_ROLE_CLAIM))]
        if not role_names:
            raise UnauthorizedError("账号未分配任何角色，拒绝登录（fail-closed）")
        try:
            roles = Role.parse_all(role_names)
        except ValueError as exc:
            logger.warning("casdoor_role_unmapped", extra={"roles": role_names})
            raise UnauthorizedError(
                f"角色未授权（映射后含平台未知角色：{role_names}），请联系管理员配置 ROLE_MAP"
            ) from exc

        user_id = str(claims.get("sub") or claims.get("id") or "")
        username = str(
            claims.get("preferred_username") or claims.get("name") or user_id
        )
        if not user_id:
            raise UnauthorizedError("身份令牌缺少用户标识（sub），拒绝登录")
        display = claims.get("displayName") or claims.get("name") or username
        email = claims.get("email")
        return CurrentUser(
            user_id=user_id,
            username=username,
            email=str(email) if email else None,
            org_id=org_id,
            org_name=None,  # Casdoor token 不带组织显示名；ensure_org 缺省生成
            display_name=str(display),
            roles=roles,
            is_authenticated=True,
            provider=self.name,
        )
