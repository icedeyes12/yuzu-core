# FILE: app/core/context.py
# DESCRIPTION: Request-scoped ContextVar for client-side BYOK credentials.
#              Populated per-request from X-Provider-* headers (chat endpoint),
#              cleared in finally. Providers read via resolve_* helpers.
#
#              IMPORTANT: This module MUST stay dependency-free (only stdlib).
#              It lives in app/core (not app/api) so importing it never
#              triggers app/api/__init__.py → router registry → orchestrator
#              chain. That ordering is what breaks the providers ↔ api
#              circular import.
#
#              Precedence (Dual-Plane):
#                1. Request plane  — ContextVar keyring (X-Provider-Key header)
#                2. System plane   — os.getenv(f"{PROVIDER}_API_KEY")
#                3. Legacy         — caller-provided fallback (DB-loaded self.api_key)

from __future__ import annotations

import os
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestKeyring:
    """Per-request credential bundle from client-side BYOK headers.

    Fields:
        provider:  Name of the provider this keyring targets (e.g. "openrouter").
                   None acts as a wildcard — applies to any provider.
        key:       Plaintext API key from X-Provider-Key. Never persisted.
        base_url:  Optional override from X-Base-Url.
        model_id:  Optional model override from X-Model-Id.
    """

    provider: str | None = None
    key: str | None = None
    base_url: str | None = None
    model_id: str | None = None


_keyring_ctx: ContextVar[RequestKeyring | None] = ContextVar(
    "yuzu_request_keyring", default=None
)


def set_request_keyring(keyring: RequestKeyring) -> None:
    """Bind a keyring to the current async context (request plane)."""
    _keyring_ctx.set(keyring)


def get_request_keyring() -> RequestKeyring | None:
    """Return the current request's keyring, or None if unset (system plane)."""
    return _keyring_ctx.get()


def clear_request_keyring() -> None:
    """Unbind the keyring — call in finally to prevent cross-request leakage."""
    _keyring_ctx.set(None)


def _provider_matches(keyring: RequestKeyring | None, provider_name: str) -> bool:
    """True if the keyring applies to the given provider (wildcard or exact)."""
    if keyring is None or not keyring.key:
        return False
    return keyring.provider is None or keyring.provider == provider_name


def resolve_api_key(provider_name: str, fallback: str | None = None) -> str | None:
    """Resolve the API key for a provider.

    Precedence (Dual-Plane):
      1. Request plane  — ContextVar keyring (X-Provider-Key header)
      2. System plane   — os.getenv(f"{PROVIDER}_API_KEY")
      3. Legacy         — caller-provided fallback (DB-loaded self.api_key)
    """
    keyring = get_request_keyring()
    if _provider_matches(keyring, provider_name):
        return keyring.key
    env_val = os.environ.get(f"{provider_name.upper()}_API_KEY")
    if env_val:
        return env_val
    return fallback


def resolve_base_url(provider_name: str, fallback: str) -> str:
    """Resolve the base URL for a provider.

    Precedence: ContextVar → os.getenv → fallback (provider default).
    """
    keyring = get_request_keyring()
    if _provider_matches(keyring, provider_name) and keyring.base_url:
        return keyring.base_url
    env_val = os.environ.get(f"{provider_name.upper()}_BASE_URL")
    if env_val:
        return env_val
    return fallback


def resolve_model(provider_name: str, fallback: str) -> str:
    """Resolve the model ID for a provider.

    Precedence: ContextVar model_id → fallback (caller-provided model).
    """
    keyring = get_request_keyring()
    if _provider_matches(keyring, provider_name) and keyring.model_id:
        return keyring.model_id
    return fallback
