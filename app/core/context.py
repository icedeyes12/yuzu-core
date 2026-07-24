# This module MUST stay dependency-free (only stdlib).
# It lives in app/core (not app/api) so importing it never
# triggers app/api/__init__.py → router registry → orchestrator
# chain. That ordering is what breaks the providers ↔ api
# circular import.
#
# Precedence (Dual-Plane):
#   1. Request plane  — ContextVar keyring (X-Provider-Key header)
#   2. System plane   — os.getenv(f"{PROVIDER}_API_KEY")
#   3. Legacy         — caller-provided fallback (DB-loaded self.api_key)
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestKeyring:
    """Per-request credential bundle from client-side BYOK headers."""

    provider: str | None = None
    key: str | None = None
    base_url: str | None = None
    model_id: str | None = None


class MissingProviderKeyError(Exception):
    """Raised when a provider requires an API key but none is available."""

    def __init__(self, provider_name: str):
        self.provider_name = provider_name
        self.provider = provider_name
        super().__init__(
            f"No API key available for provider '{provider_name}'. "
            f"Set your key in the client (BYOK) or configure "
            f"{provider_name.upper()}_API_KEY environment variable."
        )


_keyring_ctx: ContextVar[dict[str, RequestKeyring]] = ContextVar(
    "yuzu_request_keyring", default={}
)


def set_request_keyrings(keyrings: dict[str, RequestKeyring]) -> None:
    """Bind a map of keyrings to the current async context (request plane)."""
    _keyring_ctx.set(keyrings)


def get_request_keyring(provider_name: str) -> RequestKeyring | None:
    """Return the current request's keyring for the given provider, or None if unset."""
    return _keyring_ctx.get().get(provider_name)


def clear_request_keyring() -> None:
    """Unbind the keyring — call in finally to prevent cross-request leakage."""
    _keyring_ctx.set({})


def resolve_api_key(provider: str) -> str | None:
    """Resolve a provider key from the process environment."""
    import os

    return os.environ.get(f"{provider.upper()}_API_KEY")


def resolve_base_url(provider: str, fallback: str = "") -> str:
    """Resolve a provider base URL from the process environment."""
    import os

    return os.environ.get(f"{provider.upper()}_BASE_URL", fallback)
