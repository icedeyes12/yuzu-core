from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class StreamEvent:
    """Normalized event emitted by the backend SSE stream."""

    type: str
    content: str = ""
    data: dict[str, Any] | None = None
    error: str = ""
    turn_id: str = ""


class YuzuClient:
    """Async HTTP client for the Yuzu Companion API."""

    def __init__(self, base_url: str | None = None, timeout: float = 60.0) -> None:
        self.base_url = (
            base_url or os.getenv("YUZU_BACKEND_URL", "http://localhost:5000")
        ).rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout
            )

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("YuzuClient not connected. Call connect() first.")
        return self._client

    async def check_health(self) -> bool:
        try:
            response = await self.client.get("/")
            return response.status_code == 200
        except (httpx.HTTPError, OSError):
            return False

    async def list_sessions(self) -> list[dict[str, object]]:
        response = await self.client.get("/api/sessions/list")
        response.raise_for_status()
        data = response.json()
        sessions = data.get("sessions", [])
        return sessions if isinstance(sessions, list) else []

    async def switch_session(self, session_id: int | str) -> None:
        response = await self.client.post(
            "/api/sessions/switch", json={"session_id": str(session_id)}
        )
        response.raise_for_status()

    async def stream_message(self, message: str) -> AsyncIterator[StreamEvent]:
        async with self.client.stream(
            "POST",
            "/api/send_message_stream",
            json={"message": message, "interface": "cli"},
            headers={"Accept": "text/event-stream"},
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload:
                    continue
                yield self._parse_stream_event(payload)

    @staticmethod
    def _parse_stream_event(payload: str) -> StreamEvent:
        try:
            value = json.loads(payload)
        except json.JSONDecodeError:
            return StreamEvent(type="token", content=payload)
        if not isinstance(value, dict):
            return StreamEvent(type="token", content=str(value))

        event_type = value.get("type")
        if not isinstance(event_type, str):
            chunk = value.get("chunk", "")
            return StreamEvent(
                type="token", content=chunk if isinstance(chunk, str) else ""
            )

        data = value.get("data")
        normalized_data = data if isinstance(data, dict) else None
        content = value.get("content", "")
        error = value.get("message", value.get("error", ""))
        return StreamEvent(
            type=event_type,
            content=content if isinstance(content, str) else "",
            data=normalized_data,
            error=error if isinstance(error, str) else "",
            turn_id=value.get("turn_id", "")
            if isinstance(value.get("turn_id", ""), str)
            else "",
        )

    async def get_history(
        self, session_id: int | str, limit: int = 50
    ) -> list[dict[str, object]]:
        response = await self.client.get(
            "/api/chat_history", params={"session_id": session_id, "limit": limit}
        )
        response.raise_for_status()
        data = response.json()
        history = data.get("chat_history", [])
        return history if isinstance(history, list) else []

    async def __aenter__(self) -> YuzuClient:
        await self.connect()
        return self

    async def __aexit__(
        self, exc_type: object, exc_val: object, exc_tb: object
    ) -> None:
        await self.disconnect()
