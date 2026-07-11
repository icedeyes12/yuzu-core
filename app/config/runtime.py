from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RuntimeContext:
    provider: str
    model: str
    api_key: str | None
    base_url: str
    timeout: float = 180.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_request(
        cls,
        provider: str,
        model: str,
        request: Any,
        preferences: Any | None = None,
    ) -> RuntimeContext:
        # Parallel path: builds RuntimeContext without changing
        # existing resolve_api_key / resolve_base_url behavior.
        from app.core.context import resolve_api_key, resolve_base_url

        api_key = resolve_api_key(provider)
        base_url = resolve_base_url(provider, fallback="")

        return cls(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            metadata={
                "remote_addr": getattr(getattr(request, "client", None), "host", None),
                "user_agent": request.headers.get("user-agent")
                if request.headers
                else None,
            },
        )
