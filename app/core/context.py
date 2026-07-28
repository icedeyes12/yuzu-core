# This module MUST stay dependency-free (only stdlib).
# It lives in app/core (not app/api) so importing it never
# triggers app/api/__init__.py → router registry → orchestrator
# chain. That ordering is what breaks the providers ↔ api
# circular import.
#
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


class ConfigurationRequiredError(Exception):
    """(｡•̀ᴗ-)✧"""

    def __init__(self, field: str):
        self.field: str = field
        super().__init__(f"Configuration required: {field}")


@dataclass(frozen=True)
class RequestKeyring:
    """Per-request credential bundle from client-side BYOK headers."""

    provider: str | None = None
    key: str | None = None
    base_url: str | None = None
    model_id: str | None = None


class MissingProviderKeyError(Exception):
    """(｡•̀ᴗ-)✧"""

    def __init__(self, provider_name: str):
        self.provider_name: str = provider_name
        self.provider: str = provider_name
        super().__init__(f"No API key available for provider '{provider_name}'.")


_keyring_ctx: ContextVar[dict[str, RequestKeyring]] = ContextVar(
    "yuzu_request_keyring", default={}
)


def set_request_keyrings(keyrings: dict[str, RequestKeyring]) -> None:
    """Bind a map of keyrings to the current async context (request plane)."""
    _keyring_ctx.set(keyrings)


def get_request_keyring(provider_name: str) -> RequestKeyring | None:
    """Return the current request's keyring for the given provider, or None if unset."""
    return _keyring_ctx.get().get(provider_name)


def get_request_keyrings() -> dict[str, RequestKeyring]:
    """(｡•̀ᴗ-)✧"""
    return dict(_keyring_ctx.get())


def clear_request_keyring() -> None:
    """Unbind the keyring — call in finally to prevent cross-request leakage."""
    _keyring_ctx.set({})
