from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import Request
from fastapi.responses import RedirectResponse

from app.api.endpoints import auth
from app.auth.oauth import generate_pkce, sign_state, verify_state


def _request(
    *, headers: dict[str, str] | None = None, cookies: dict[str, str] | None = None
) -> Request:
    raw_headers = [
        (key.lower().encode(), value.encode()) for key, value in (headers or {}).items()
    ]
    cookie_header = "; ".join(
        f"{key}={value}" for key, value in (cookies or {}).items()
    )
    if cookie_header:
        raw_headers.append((b"cookie", cookie_header.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/auth/login",
        "query_string": b"",
        "headers": raw_headers,
        "scheme": "http",
        "server": ("127.0.0.1", 5000),
        "client": ("127.0.0.1", 1234),
    }
    return Request(scope)


def test_rewrite_redirect_uri_uses_forwarded_public_origin() -> None:
    request = _request(
        headers={
            "x-forwarded-host": "companion.yuzuki.space",
            "x-forwarded-proto": "https",
        }
    )

    result = auth._rewrite_redirect_uri(
        request,
        "http://localhost:5000/api/v1/auth/callback",
    )

    assert result == "https://companion.yuzuki.space/api/v1/auth/callback"


def test_rewrite_redirect_uri_uses_local_origin_without_proxy_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OAUTH_REDIRECT_ORIGINS", "http://127.0.0.1:5000")
    request = _request()

    result = auth._rewrite_redirect_uri(
        request,
        "https://companion.yuzuki.space/api/v1/auth/callback",
    )

    assert result == "http://127.0.0.1:5000/api/v1/auth/callback"


def test_rewrite_redirect_uri_uses_allowed_tailnet_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OAUTH_REDIRECT_ORIGINS", "http://100.64.0.10:5000")
    request = _request()
    request.scope["server"] = ("100.64.0.10", 5000)

    result = auth._rewrite_redirect_uri(
        request,
        "https://companion.yuzuki.space/api/v1/auth/callback",
    )

    assert result == "http://100.64.0.10:5000/api/v1/auth/callback"


def test_state_round_trip_preserves_pkce_verifier_and_origin() -> None:
    verifier, _ = generate_pkce()
    state = sign_state(
        "google", verifier, "test-secret", "https://companion.yuzuki.space/login"
    )

    assert verify_state(state, "test-secret") == (
        "google",
        verifier,
        "https://companion.yuzuki.space/login",
    )


def test_login_sets_secure_state_cookie_and_public_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OAUTH_GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv(
        "OAUTH_GOOGLE_REDIRECT_URI", "http://localhost:5000/api/v1/auth/callback"
    )
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setattr(auth, "_COOKIE_SECURE", False)

    request = _request(
        headers={
            "referer": "https://companion.yuzuki.space/login",
            "x-forwarded-host": "companion.yuzuki.space",
            "x-forwarded-proto": "https",
        }
    )

    import asyncio

    response = asyncio.run(auth.login(request))

    assert isinstance(response, RedirectResponse)
    assert (
        "redirect_uri=https%3A%2F%2Fcompanion.yuzuki.space%2Fapi%2Fv1%2Fauth%2Fcallback"
        in response.headers["location"]
    )
    set_cookie = response.headers["set-cookie"]
    assert "_oauth_state=" in set_cookie
    assert "Secure" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=none" in set_cookie


def test_callback_rejects_missing_state_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    request = _request()
    request.scope["path"] = "/api/v1/auth/callback"
    request.scope["query_string"] = b"code=test-code&state=test-state"

    import asyncio

    with pytest.raises(Exception) as exc_info:
        asyncio.run(auth.callback(request))

    assert getattr(exc_info.value, "status_code", None) == 400
    assert getattr(exc_info.value, "detail", None) == "State mismatch"


def test_auth_url_contains_exact_callback() -> None:
    location = "https://accounts.google.com/o/oauth2/v2/auth?redirect_uri=https%3A%2F%2Fcompanion.yuzuki.space%2Fapi%2Fv1%2Fauth%2Fcallback"
    query = parse_qs(urlsplit(location).query)
    assert query["redirect_uri"] == [
        "https://companion.yuzuki.space/api/v1/auth/callback"
    ]
