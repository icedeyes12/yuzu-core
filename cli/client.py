# FILE: cli/client.py
# DESCRIPTION: Async HTTP client for communicating with the FastAPI backend.
#              Thin-client — HTTP only, no database imports.

from __future__ import annotations

import httpx


class YuzuClient:
    """
    Async HTTP client for Yuzu Companion backend.
    
    Thin-client that communicates exclusively via HTTP. Never imports
    database models or internal services.
    """

    def __init__(self, base_url: str = "http://localhost:5000", timeout: float = 30.0) -> None:
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
        """
        Check if the backend server is healthy.
        
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

    async def __aenter__(self) -> YuzuClient:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[no-untyped-def]
        """Async context manager exit."""
        await self.disconnect()
