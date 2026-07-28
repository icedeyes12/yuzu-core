from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from app.core.context import get_request_keyring


class RequestLike(Protocol):
    client: object | None
    headers: Mapping[str, str]


@dataclass(frozen=True)
class RuntimeContext:
    provider: str
    model: str
    api_key: str | None
    base_url: str
    timeout: float = 180.0
    metadata: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_request(
        cls,
        provider: str,
        model: str,
        request: RequestLike,
        _preferences: object | None = None,
    ) -> RuntimeContext:
        keyring = get_request_keyring(provider)
        api_key = keyring.key if keyring else None
        base_url = keyring.base_url if keyring and keyring.base_url else ""

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
