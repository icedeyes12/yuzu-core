from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cli.client import YuzuClient


@pytest.mark.asyncio
async def test_client_uses_versioned_api_routes():
    client = YuzuClient("http://testserver")
    client._client = MagicMock()

    response = MagicMock()
    response.json.return_value = {"sessions": []}
    client._client.get = AsyncMock(return_value=response)
    await client.list_sessions()
    client._client.get.assert_awaited_once_with("/api/v1/sessions/list")

    client._client.get.reset_mock()
    response.json.return_value = {"chat_history": []}
    await client.get_history("session-id")
    client._client.get.assert_awaited_once_with(
        "/api/v1/chat_history",
        params={"session_id": "session-id", "limit": 50},
    )

    client._client.post = AsyncMock(return_value=response)
    await client.switch_session("session-id")
    client._client.post.assert_awaited_once_with(
        "/api/v1/sessions/switch", json={"session_id": "session-id"}
    )


@pytest.mark.asyncio
async def test_client_stream_uses_versioned_api_route():
    client = YuzuClient("http://testserver")
    response = MagicMock()
    response.raise_for_status = MagicMock()

    async def lines():
        yield 'data: {"type":"done"}'

    response.aiter_lines.return_value = lines()
    stream_context = MagicMock()
    stream_context.__aenter__ = AsyncMock(return_value=response)
    stream_context.__aexit__ = AsyncMock(return_value=None)
    client._client = MagicMock()
    client._client.stream.return_value = stream_context

    events = [event async for event in client.stream_message("hello")]

    assert [event.type for event in events] == ["done"]
    client._client.stream.assert_called_once_with(
        "POST",
        "/api/v1/send_message_stream",
        json={"message": "hello", "interface": "cli"},
        headers={"Accept": "text/event-stream"},
    )
