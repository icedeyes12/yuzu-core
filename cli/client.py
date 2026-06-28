
from __future__ import annotations

from collections.abc import AsyncIterator
import json

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
        """Check if the backend server is healthy.

        Returns:
            True if backend responds with status 200, False otherwise.
        """
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

    async def switch_session(self, session_id: int) -> None:
        """Switch the active session on the backend.

        Args:
            session_id: Session ID to activate
        """
        response = await self.client.post(
            "/api/sessions/switch",
            json={"session_id": session_id},
        )
        response.raise_for_status()

    async def stream_message(self, message: str) -> AsyncIterator[str]:
        """
        Stream a chat message via SSE.

        Args:
            message: User message text

        Yields:
            str: Each SSE data chunk
        """
        async with self.client.stream(
            "POST",
            "/api/send_message_stream",
            json={"message": message},
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    # Parse JSON to extract chunk value
                    try:
                        data_str = line[5:].strip()
                        if data_str:
                            data = json.loads(data_str)
                            chunk = data.get("chunk", "")
                            if chunk:
                                yield chunk
                    except json.JSONDecodeError:
                        # Fallback: yield raw if not valid JSON
                        yield line[5:].strip()

    async def get_history(self, session_id: int, limit: int = 50) -> list[dict]:
        """
        Fetch chat history for a session.

        Args:
            session_id: Session identifier
            limit: Maximum number of messages to fetch

        Returns:
            List of message dictionaries
        """
        response = await self.client.get(
            "/api/chat_history",
            params={"session_id": session_id, "limit": limit},
        )
        response.raise_for_status()
        data = response.json()
        return data.get("chat_history", [])

    async def __aenter__(self) -> YuzuClient:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[no-untyped-def]
        """Async context manager exit."""
        await self.disconnect()
