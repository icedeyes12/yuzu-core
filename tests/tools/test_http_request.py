from __future__ import annotations

import asyncio

import httpx

from app.tools import http_request


def test_network_error_is_categorized_and_keeps_http_shape(monkeypatch):
    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def request(self, *_args, **_kwargs):
            raise httpx.ConnectError("All connection attempts failed")

    from app.db import Database

    monkeypatch.setattr(http_request.httpx, "AsyncClient", FailingClient)
    monkeypatch.setattr(http_request, "is_safe_public_url", lambda _url: (True, ""))

    async def fake_get_profile(*_args, **_kwargs):
        return None

    monkeypatch.setattr(Database, "get_profile", fake_get_profile)

    result = asyncio.run(
        http_request.execute({"url": "https://example.com", "method": "GET"})
    )

    assert isinstance(result, dict)
    assert result["ok"] is False
    assert result["error_category"] == "network_error"
    data = result["data"]
    assert isinstance(data, dict)
    assert data["schema_kind"] == "http"
    assert data["url"] == "https://example.com"
