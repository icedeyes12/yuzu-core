from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from app.tools import http_request


class FakeFiles:
    def __init__(self) -> None:
        self.calls = []

    async def persist_bytes(self, **kwargs):
        self.calls.append(kwargs)
        return {"id": str(uuid4())}


@pytest.mark.asyncio
async def test_downloaded_image_uses_owner_scoped_file_service(monkeypatch):
    files = FakeFiles()
    response = httpx.Response(
        200,
        headers={"Content-Type": "image/png"},
        content=b"png",
        request=httpx.Request("GET", "https://example.com/a.png"),
    )

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def request(self, *_args, **_kwargs):
            return response

    monkeypatch.setattr(http_request, "is_safe_public_url", lambda _url: (True, ""))
    monkeypatch.setattr(http_request.httpx, "AsyncClient", Client)
    monkeypatch.setattr(http_request, "get_file_service", lambda: files)
    monkeypatch.setattr(
        "app.db.Database.get_profile",
        lambda _user_id: _async_value({"partner_name": "Yuzu"}),
    )
    owner = str(uuid4())

    result = await http_request.execute(
        {"url": "https://example.com/a.png"}, user_id=owner
    )

    assert result["ok"] is True
    assert files.calls[0]["owner_id"] == owner
    assert files.calls[0]["kind"] == "attachment"
    assert result["data"]["path"].startswith("/api/v1/files/fil_")


async def _async_value(value):
    return value
