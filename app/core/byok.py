from __future__ import annotations

from app.core.context import get_request_keyring

CHUTES = "chutes"
YUZU_PORTAL = "yuzu_portal"
YUZU_PORTAL_PROVIDER = YUZU_PORTAL
DEFAULT_YUZU_PORTAL_BASE_URL = "http://localhost:20128/v1"
YUZU_PORTAL_BASE_URL = DEFAULT_YUZU_PORTAL_BASE_URL


def get_provider_key(provider: str) -> str | None:
    keyring = get_request_keyring(provider)
    return (
        keyring.key.strip() if keyring and keyring.key and keyring.key.strip() else None
    )


def get_provider_base_url(provider: str) -> str:
    keyring = get_request_keyring(provider)
    if keyring and keyring.base_url and keyring.base_url.strip():
        return keyring.base_url.strip().rstrip("/")
    if provider == YUZU_PORTAL:
        return DEFAULT_YUZU_PORTAL_BASE_URL
    return ""
