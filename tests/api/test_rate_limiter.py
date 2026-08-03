from __future__ import annotations

import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.rate_limits import (
    RateLimiter,
    enforce_rate_limit,
    get_client_ip,
)
from main import app


def test_sliding_window_expires_entries() -> None:
    now = [100.0]
    limiter = RateLimiter(clock=lambda: now[0])

    assert limiter.allow("client", limit=1, window_seconds=60)
    assert not limiter.allow("client", limit=1, window_seconds=60)
    now[0] = 160.1
    assert limiter.allow("client", limit=1, window_seconds=60)


def test_active_limit_releases_slot() -> None:
    limiter = RateLimiter()

    assert limiter.acquire_active("user", limit=1)
    assert not limiter.acquire_active("user", limit=1)
    limiter.release_active("user")
    assert limiter.acquire_active("user", limit=1)


def test_rate_limit_raises_problem_detail_compatible_429() -> None:
    limiter = RateLimiter(clock=time.monotonic)

    limiter.allow("client", limit=1, window_seconds=60)
    with pytest.raises(HTTPException) as raised:
        enforce_rate_limit(limiter, "client", limit=1, window_seconds=60)

    assert raised.value.status_code == 429
    assert raised.value.headers["Retry-After"]


def test_auth_login_rate_limit_returns_429() -> None:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def no_startup(_app):
        yield

    original = app.router.lifespan_context
    app.router.lifespan_context = no_startup
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            responses = [
                client.get("/api/v1/auth/login?provider=unknown") for _ in range(11)
            ]
    finally:
        app.router.lifespan_context = original

    assert responses[-1].status_code == 429
    assert responses[-1].headers["content-type"] == "application/problem+json"
    assert responses[-1].json()["status"] == 429


def test_client_ip_uses_request_client() -> None:
    from starlette.requests import Request

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "client": ("192.0.2.10", 1234),
            "server": ("testserver", 80),
        }
    )
    assert get_client_ip(request) == "192.0.2.10"


def test_metrics_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("YUZU_METRICS_ENABLED", raising=False)
    from app.metrics import metrics

    assert metrics.enabled is False
    assert metrics.render() == ("", "text/plain; version=0.0.4; charset=utf-8")


def test_metrics_can_be_enabled(monkeypatch) -> None:
    from app.metrics import Metrics

    enabled = Metrics(enabled=True)
    enabled.request_started()
    body, _content_type = enabled.render()
    assert "yuzu_http_requests_total" in body
