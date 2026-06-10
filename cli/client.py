# FILE: cli/client.py
# DESCRIPTION: Async HTTP client for communicating with the FastAPI backend.
#              Thin-client — HTTP only, no database imports.

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx


class YuzuClient:
    """
    Async HTTP client for Yuzu Companion backend.

    Thin-client that communicates exclusively via HTTP. Never imports
    database models or internal services.
    """

    def __init__(
        self, base_url: str = "http://localhost:5000", timeout: float = 60.0
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        """Initialize the async HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )

    async def disconnect(self) -> None:
        """Close the async HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Get the HTTP client, raising if not connected."""
        if self._client is None:
            raise RuntimeError("YuzuClient not connected. Call connect() first.")
        return self._client

    async def check_health(self) -> bool:
        """Check if the backend server is healthy."""
        try:
            response = await self.client.get("/")
            return response.status_code == 200
        except httpx.ConnectError:
            return False
        except httpx.TimeoutException:
            return False
        except Exception:
            return False

    async def list_sessions(self) -> list[dict]:
        """Fetch list of all sessions."""
        response = await self.client.get("/api/sessions/list")
        response.raise_for_status()
        data = response.json()
        return data.get("sessions", [])

    async def stream_message(self, session_id: str, message: str) -> AsyncIterator[str]:
        """
        Stream a chat message via SSE.

        Args:
            session_id: Session identifier
            message: User message text

        Yields:
            str: Each SSE data chunk
        """
        async with self.client.stream(
            "POST",
            "/api/send_message_stream",
            json={"session_id": session_id, "message": message},
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    yield line[5:].strip()

    async def get_history(self, session_id: str, limit: int = 50) -> list[dict]:
        """
        Fetch chat history for a session.

        Args:
            session_id: Session identifier
            limit: Maximum number of messages to fetch

        Returns:
            List of message dictionaries
        """
        response = await self.client.get(
            "/api/history",
            params={"session_id": session_id, "limit": limit},
        )
        response.raise_for_status()
        data = response.json()
        return data.get("messages", [])

    async def __aenter__(self) -> YuzuClient:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[no-untyped-def]
        """Async context manager exit."""
        await self.disconnect()
