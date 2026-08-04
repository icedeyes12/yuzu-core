"""(=^･ω･^=)"""

from __future__ import annotations

import asyncio

from app.tools import weather


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, responses: list[FakeResponse]):
        self.responses = iter(responses)
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


def test_configured_location_label_prefers_city():
    client = FakeClient(
        [FakeResponse({"address": {"city": "Jakarta", "state": "DKI Jakarta"}})]
    )

    label = asyncio.run(weather._resolve_configured_location_label(client, -6.2, 106.8))

    assert label == "Jakarta"
    assert client.calls[0][0] == weather._REVERSE_GEOCODING_URL


def test_configured_location_label_falls_back_when_provider_fails():
    class FailingClient:
        async def get(self, url, **kwargs):
            raise weather.httpx.HTTPError("offline")

    label = asyncio.run(
        weather._resolve_configured_location_label(FailingClient(), -6.2, 106.8)
    )

    assert label is None
