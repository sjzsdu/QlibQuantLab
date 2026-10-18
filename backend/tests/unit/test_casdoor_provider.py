"""CasdoorAuthProvider 单测：PKCE / JWKS 验签 / claim 归一化 / org·role 映射 fail-closed。

全部走 httpx.MockTransport —— 不发真实网络请求；RSA 密钥在测试内生成并现场签发 id_token，
等价于真实 Casdoor 的 RS256 + JWKS 链路（阶段 7 决策 D7-5：不引 SDK，httpx+pyjwt 自验）。
"""

from __future__ import annotations

import hashlib
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from conftest import make_settings
from qqlab.adapters.auth.casdoor_provider import CasdoorAuthProvider
from qqlab.adapters.cache.memory_cache import MemoryCacheProvider
from qqlab.core.errors import UnauthorizedError
from qqlab.core.security import issue_session_token
from qqlab.ports.auth import CurrentUser, Role

_ISSUER = "https://idp.example.com"
_CLIENT_ID = "cid"
_CLIENT_SECRET = "csecret"


def _casdoor_settings(**overrides: Any):
    payload = dict(
        AUTH_PROVIDER="casdoor",
        CASDOOR_ISSUER=_ISSUER,
        CASDOOR_CLIENT_ID=_CLIENT_ID,
        CASDOOR_CLIENT_SECRET=_CLIENT_SECRET,
        CASDOOR_REDIRECT_URI="https://app.example.com/api/v1/auth/callback",
    )
    payload.update(overrides)
    return make_settings(**payload)


class _RSAKeyPair:
    """测试内生成 RSA 密钥 + 导出 JWK，模拟 Casdoor 的签名密钥。"""

    def __init__(self, kid: str = "test-key-1") -> None:
        self.kid = kid
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = RSAAlgorithm.to_jwk(self.private_key.public_key())
        import json as _json

        jwk = _json.loads(jwk)
        jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
        self.jwk = jwk

    def sign(self, claims: dict[str, Any]) -> str:
        return pyjwt.encode(claims, self.private_key, algorithm="RS256", headers={"kid": self.kid})


def _base_claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": _ISSUER,
        "aud": _CLIENT_ID,
        "sub": "user-123",
        "name": "alice",
        "preferred_username": "alice",
        "email": "alice@example.com",
        "displayName": "Alice",
        "owner": "built-in",
        "roles": ["admin"],
        "exp": now + 300,
        "iat": now,
    }
    claims.update(overrides)
    return claims


def _transport(keypair: _RSAKeyPair, *, id_token: str | None = None, jwks=None) -> httpx.MockTransport:
    """token 端点返回 id_token；JWKS 端点返回给定密钥集（默认 keypair 的）。"""
    keys = jwks if jwks is not None else [keypair.jwk]

    def handler(request: httpx.Request) -> httpx.Response:
        path = urlsplit(str(request.url)).path
        if path == "/api/login/oauth/access_token":
            body = parse_qs(request.content.decode())
            # PKCE verifier 必须随兑换请求送出（真实 Casdoor 会校验它）
            assert body["code_verifier"][0]
            assert body["grant_type"] == ["authorization_code"]
            return httpx.Response(200, json={"id_token": id_token or keypair.sign(_base_claims())})
        if path == "/.well-known/jwks":
            return httpx.Response(200, json={"keys": keys})
        if path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={"issuer": _ISSUER})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------- get_login_url
def test_login_url_contains_oidc_params() -> None:
    provider = CasdoorAuthProvider(_casdoor_settings())
    url = provider.get_login_url("state-abc", "/projects")
    split = urlsplit(url)
    assert f"{split.scheme}://{split.netloc}" == _ISSUER
    assert split.path == "/login/oauth/authorize"
    params = parse_qs(split.query)
    assert params["client_id"] == [_CLIENT_ID]
    assert params["response_type"] == ["code"]
    assert params["redirect_uri"] == ["https://app.example.com/api/v1/auth/callback"]
    assert params["state"] == ["state-abc"]
    assert params["code_challenge_method"] == ["S256"]
    # S256 挑战 = base64url(sha256(verifier))；verifier 由 (secret, state) 推导
    verifier = provider._code_verifier("state-abc")
    expected = (
        __import__("base64")
        .urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert params["code_challenge"] == [expected]


def test_pkce_verifier_deterministic_and_state_bound() -> None:
    """无状态推导：同 (secret, state) 恒定、不同 state 不同、不同 secret 不同。"""
    provider = CasdoorAuthProvider(_casdoor_settings())
    v1 = provider._code_verifier("s1")
    assert v1 == provider._code_verifier("s1")
    assert v1 != provider._code_verifier("s2")
    other = CasdoorAuthProvider(_casdoor_settings(CASDOOR_CLIENT_SECRET="other"))
    assert v1 != other._code_verifier("s1")


# ---------------------------------------------------------------- 登出
def test_logout_url_is_rp_initiated() -> None:
    provider = CasdoorAuthProvider(_casdoor_settings())
    url = provider.get_logout_url("/projects")
    split = urlsplit(url)
    assert split.path == "/api/logout"
    params = parse_qs(split.query)
    assert params["client_id"] == [_CLIENT_ID]
    landing = params["post_logout_redirect_uri"][0]
    # post_logout_redirect_uri 必须是绝对地址（origin 取自 redirect_uri）
    assert landing.startswith("https://app.example.com/login?logged_out=1")
    assert "next=" in landing


# ---------------------------------------------------------------- handle_callback
@pytest.mark.asyncio
async def test_callback_success_maps_identity() -> None:
    keypair = _RSAKeyPair()
    provider = CasdoorAuthProvider(_casdoor_settings(), cache=MemoryCacheProvider(), transport=_transport(keypair))
    user = await provider.handle_callback("code-1", "state-1")
    assert user.user_id == "user-123"
    assert user.username == "alice"
    assert user.email == "alice@example.com"
    assert user.display_name == "Alice"
    assert user.org_id == "built-in"  # owner claim 直通（D7-2 默认）
    assert [r.value for r in user.roles] == ["admin"]
    assert user.provider == "casdoor"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "roles_raw,expected",
    [
        ("admin", ["admin"]),
        (["admin", "viewer"], ["admin", "viewer"]),
        ([{"name": "admin"}, {"name": "auditor"}], ["admin", "auditor"]),  # 完整 JWT 形态
    ],
    ids=["str", "str-list", "obj-list"],
)
async def test_roles_normalized_three_shapes(roles_raw, expected) -> None:  # noqa: ANN001
    keypair = _RSAKeyPair()
    token = keypair.sign(_base_claims(roles=roles_raw))
    provider = CasdoorAuthProvider(
        _casdoor_settings(), transport=_transport(keypair, id_token=token)
    )
    user = await provider.handle_callback("c", "s")
    assert [r.value for r in user.roles] == expected


@pytest.mark.asyncio
async def test_role_map_alias_applied() -> None:
    keypair = _RSAKeyPair()
    token = keypair.sign(_base_claims(roles=["Administrator"]))
    provider = CasdoorAuthProvider(
        _casdoor_settings(CASDOOR_ROLE_MAP='{"Administrator": "admin"}'),
        transport=_transport(keypair, id_token=token),
    )
    user = await provider.handle_callback("c", "s")
    assert [r.value for r in user.roles] == ["admin"]


@pytest.mark.asyncio
async def test_unknown_role_fail_closed() -> None:
    """映射后含平台未知角色 → 401（D7-3 fail-closed）。"""
    keypair = _RSAKeyPair()
    token = keypair.sign(_base_claims(roles=["admin", "some-casdoor-role"]))
    provider = CasdoorAuthProvider(
        _casdoor_settings(), transport=_transport(keypair, id_token=token)
    )
    with pytest.raises(UnauthorizedError):
        await provider.handle_callback("c", "s")


@pytest.mark.asyncio
async def test_empty_roles_fail_closed() -> None:
    keypair = _RSAKeyPair()
    token = keypair.sign(_base_claims(roles=[]))
    provider = CasdoorAuthProvider(
        _casdoor_settings(), transport=_transport(keypair, id_token=token)
    )
    with pytest.raises(UnauthorizedError):
        await provider.handle_callback("c", "s")


@pytest.mark.asyncio
async def test_org_map_applied() -> None:
    keypair = _RSAKeyPair()
    token = keypair.sign(_base_claims(owner="qqlab-dev"))
    provider = CasdoorAuthProvider(
        _casdoor_settings(CASDOOR_ORG_MAP='{"qqlab-dev": "org-1"}'),
        transport=_transport(keypair, id_token=token),
    )
    user = await provider.handle_callback("c", "s")
    assert user.org_id == "org-1"


@pytest.mark.asyncio
async def test_missing_org_claim_fail_closed() -> None:
    claims = _base_claims()
    del claims["owner"]
    keypair = _RSAKeyPair()
    token = keypair.sign(claims)
    provider = CasdoorAuthProvider(
        _casdoor_settings(), transport=_transport(keypair, id_token=token)
    )
    with pytest.raises(UnauthorizedError):
        await provider.handle_callback("c", "s")


@pytest.mark.asyncio
async def test_bad_signature_rejected() -> None:
    """JWKS 里的密钥验不过签名 → 401（签名密钥不匹配）。"""
    keypair = _RSAKeyPair()
    evil = _RSAKeyPair(kid="test-key-1")  # 同 kid 异密钥 → 签名校验失败
    token = evil.sign(_base_claims())
    provider = CasdoorAuthProvider(
        _casdoor_settings(), transport=_transport(keypair, id_token=token)
    )
    with pytest.raises(UnauthorizedError):
        await provider.handle_callback("c", "s")


@pytest.mark.asyncio
async def test_unknown_kid_rejected_after_refresh() -> None:
    """kid 不在 JWKS（强刷一次后仍不在）→ 401。"""
    keypair = _RSAKeyPair()
    evil = _RSAKeyPair(kid="unknown-kid")
    token = evil.sign(_base_claims())
    provider = CasdoorAuthProvider(
        _casdoor_settings(), transport=_transport(keypair, id_token=token)
    )
    with pytest.raises(UnauthorizedError):
        await provider.handle_callback("c", "s")


@pytest.mark.asyncio
async def test_expired_token_rejected() -> None:
    keypair = _RSAKeyPair()
    token = keypair.sign(_base_claims(exp=int(time.time()) - 60))
    provider = CasdoorAuthProvider(
        _casdoor_settings(), transport=_transport(keypair, id_token=token)
    )
    with pytest.raises(UnauthorizedError):
        await provider.handle_callback("c", "s")


@pytest.mark.asyncio
async def test_wrong_audience_rejected() -> None:
    keypair = _RSAKeyPair()
    token = keypair.sign(_base_claims(aud="other-client"))
    provider = CasdoorAuthProvider(
        _casdoor_settings(), transport=_transport(keypair, id_token=token)
    )
    with pytest.raises(UnauthorizedError):
        await provider.handle_callback("c", "s")


@pytest.mark.asyncio
async def test_issuer_not_in_whitelist_rejected() -> None:
    keypair = _RSAKeyPair()
    token = keypair.sign(_base_claims(iss="https://evil.example.com"))
    provider = CasdoorAuthProvider(
        _casdoor_settings(), transport=_transport(keypair, id_token=token)
    )
    with pytest.raises(UnauthorizedError):
        await provider.handle_callback("c", "s")


@pytest.mark.asyncio
async def test_internal_url_in_iss_whitelist() -> None:
    """dev 双地址：id_token 的 iss 可能是内部地址（casdoor#1622）→ 白名单放行。"""
    keypair = _RSAKeyPair()
    token = keypair.sign(_base_claims(iss="http://casdoor:8000"))
    provider = CasdoorAuthProvider(
        _casdoor_settings(CASDOOR_INTERNAL_URL="http://casdoor:8000"),
        transport=_transport(keypair, id_token=token),
    )
    user = await provider.handle_callback("c", "s")
    assert user.user_id == "user-123"


@pytest.mark.asyncio
async def test_token_exchange_error_maps_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    provider = CasdoorAuthProvider(_casdoor_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(UnauthorizedError):
        await provider.handle_callback("bad-code", "s")


@pytest.mark.asyncio
async def test_callback_empty_code_rejected() -> None:
    provider = CasdoorAuthProvider(_casdoor_settings(), transport=_transport(_RSAKeyPair()))
    with pytest.raises(UnauthorizedError):
        await provider.handle_callback("", "s")


# ---------------------------------------------------------------- verify_token
@pytest.mark.asyncio
async def test_verify_token_platform_session() -> None:
    """verify_token 校验的是平台自签会话 JWT（D7-8：非 JWKS；IdP 令牌只在回调用一次）。"""
    settings = _casdoor_settings()
    provider = CasdoorAuthProvider(settings)
    user = CurrentUser(
        user_id="u1",
        username="alice",
        org_id="org-1",
        roles=(Role.ADMIN,),
        email="a@example.com",
        display_name="Alice",
        is_authenticated=True,
        provider="casdoor",
    )
    token = issue_session_token(user, settings)
    out = await provider.verify_token(token)
    assert out is not None
    assert out.user_id == "u1"
    assert out.org_id == "org-1"
    assert await provider.verify_token("garbage.token.here") is None


# ---------------------------------------------------------------- healthcheck
@pytest.mark.asyncio
async def test_healthcheck_discovery_reachable() -> None:
    provider = CasdoorAuthProvider(
        _casdoor_settings(), transport=_transport(_RSAKeyPair())
    )
    assert await provider.healthcheck() is True


@pytest.mark.asyncio
async def test_healthcheck_unreachable_false() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    provider = CasdoorAuthProvider(_casdoor_settings(), transport=httpx.MockTransport(handler))
    assert await provider.healthcheck() is False


# ---------------------------------------------------------------- JWKS 缓存
@pytest.mark.asyncio
async def test_jwks_cached_in_cache_provider() -> None:
    """JWKS 首次拉取后进缓存（TTL 1h），后续验证不再发请求。"""
    keypair = _RSAKeyPair()
    calls = {"jwks": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = urlsplit(str(request.url)).path
        if path == "/.well-known/jwks":
            calls["jwks"] += 1
            return httpx.Response(200, json={"keys": [keypair.jwk]})
        if path == "/api/login/oauth/access_token":
            return httpx.Response(200, json={"id_token": keypair.sign(_base_claims())})
        return httpx.Response(404)

    provider = CasdoorAuthProvider(
        _casdoor_settings(),
        cache=MemoryCacheProvider(),
        transport=httpx.MockTransport(handler),
    )
    await provider.handle_callback("c1", "s1")
    await provider.handle_callback("c2", "s2")
    assert calls["jwks"] == 1


@pytest.mark.asyncio
async def test_unknown_kid_forces_jwks_refresh() -> None:
    """密钥轮换：缓存里是旧 JWKS，token 用新 kid 签 → 强刷一次后成功。"""
    old_key = _RSAKeyPair(kid="old")
    new_key = _RSAKeyPair(kid="new")
    cache = MemoryCacheProvider()
    rotated = {"active": False}
    calls = {"jwks": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = urlsplit(str(request.url)).path
        if path == "/.well-known/jwks":
            calls["jwks"] += 1
            key = new_key if rotated["active"] else old_key
            return httpx.Response(200, json={"keys": [key.jwk]})
        if path == "/api/login/oauth/access_token":
            signed_by = new_key if rotated["active"] else old_key
            return httpx.Response(200, json={"id_token": signed_by.sign(_base_claims())})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    provider = CasdoorAuthProvider(_casdoor_settings(), cache=cache, transport=transport)

    # 阶段一：正常登录（old key），缓存装上旧 JWKS
    await provider.handle_callback("c", "s")
    assert calls["jwks"] == 1
    # 阶段二：轮换（JWKS 换 new、token 用 new 签）→ 未知 kid 触发强刷
    rotated["active"] = True
    user = await provider.handle_callback("c", "s")
    assert user.user_id == "user-123"
    # 第二次回调：先读缓存（旧 key，kid 未命中）→ 强刷一次（new）→ 成功
    # 若缓存没生效（每次都直接拉新 JWKS），kid 首次即命中、calls 会是 3
    assert calls["jwks"] == 2
