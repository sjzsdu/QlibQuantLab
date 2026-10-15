"""会话令牌、开放重定向与角色解析。"""

from __future__ import annotations

import time

import jwt
import pytest

from conftest import make_settings
from qqlab.core.security import ALGORITHM, decode_session_token, issue_session_token, new_token
from qqlab.ports.auth import CurrentUser, Role
from qqlab.services import safe_redirect


def _user(**over) -> CurrentUser:
    payload = dict(
        user_id="u-1",
        username="alice",
        org_id="dev-org",
        roles=(Role.ADMIN, Role.RESEARCHER),
        email="a@example.com",
        display_name="Alice",
        org_name="Dev",
        provider="mock",
    )
    payload.update(over)
    return CurrentUser(**payload)


def test_token_roundtrip() -> None:
    settings = make_settings()
    token = issue_session_token(_user(), settings)
    claims = decode_session_token(token, settings)
    assert claims is not None
    assert claims.user_id == "u-1"
    assert claims.roles == (Role.ADMIN, Role.RESEARCHER)
    user = claims.to_user()
    assert user.is_admin and user.has_any(Role.RESEARCHER)


def test_token_rejected_when_tampered() -> None:
    settings = make_settings()
    token = issue_session_token(_user(), settings)
    assert decode_session_token(token[:-2] + "xx", settings) is None


def test_token_rejected_with_other_secret() -> None:
    settings = make_settings()
    other = make_settings(APP_JWT_SECRET="another-secret-0123456789abcdef0123")
    token = issue_session_token(_user(), other)
    assert decode_session_token(token, settings) is None


def test_expired_token_rejected() -> None:
    settings = make_settings()
    now = int(time.time())
    payload = {
        "sub": "u-1",
        "uname": "alice",
        "org": "dev-org",
        "roles": ["viewer"],
        "exp": now - 10,
        "iat": now - 100,
    }
    token = jwt.encode(payload, settings.APP_JWT_SECRET, algorithm=ALGORITHM)
    assert decode_session_token(token, settings) is None


def test_token_with_bad_roles_rejected() -> None:
    settings = make_settings()
    payload = {
        "sub": "u-1",
        "uname": "alice",
        "org": "dev-org",
        "roles": ["superuser"],  # 未知角色
        "exp": int(time.time()) + 60,
    }
    token = jwt.encode(payload, settings.APP_JWT_SECRET, algorithm=ALGORITHM)
    # 未知角色 → 令牌整体作废（fail-closed）
    assert decode_session_token(token, settings) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "/"),
        ("", "/"),
        ("/projects", "/projects"),
        ("/projects?x=1", "/projects?x=1"),
        ("//evil.com", "/"),
        ("https://evil.com", "/"),
        ("/\\evil.com", "/"),
        ("javascript:alert(1)", "/"),
        ("projects", "/"),
    ],
)
def test_safe_redirect(raw, expected) -> None:  # noqa: ANN001
    assert safe_redirect(raw) == expected


def test_new_token_unique() -> None:
    assert new_token() != new_token()
    assert len(new_token()) >= 32
