from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import socket
import threading
import urllib.parse

from fastapi import HTTPException, Request

from app.auth.session import SESSION_COOKIE_NAME, validate_session
from app.core.context import RequestKeyring
from app.core.logging_config import get_logger

log = get_logger(__name__)
_MAX_BYOK_HEADER_BYTES = 64 * 1024
_MAX_STREAMS_PER_USER = 2
_stream_counts: dict[str, int] = {}
_stream_counts_lock = threading.Lock()


def get_client_id(request: Request) -> str:
    """Generate a stable client identifier from request metadata."""
    client_host = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    digest = hashlib.sha256(user_agent.encode()).hexdigest()[:8]
    return f"{client_host}_{digest}"


async def get_current_user(request: Request) -> str:
    """FastAPI dependency: extract authenticated user_id from session cookie."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = await validate_session(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return user_id


def extract_keyrings(request: Request) -> dict[str, RequestKeyring] | None:
    """Decode the bounded client-side BYOK configuration header."""
    byok_header = request.headers.get("X-BYOK-Config")
    if not byok_header:
        return None
    if len(byok_header.encode("ascii", errors="ignore")) > _MAX_BYOK_HEADER_BYTES:
        raise HTTPException(
            status_code=413, detail="BYOK configuration header is too large"
        )
    try:
        raw_json = urllib.parse.unquote(
            base64.b64decode(byok_header, validate=True).decode("utf-8")
        )
        byok_config = json.loads(raw_json)
        providers = byok_config.get("providers", byok_config)
        if not isinstance(providers, dict):
            raise ValueError("providers must be an object")
        keyrings: dict[str, RequestKeyring] = {}
        for provider, cfg in providers.items():
            if not isinstance(provider, str) or not isinstance(cfg, dict):
                continue
            keyrings[provider] = RequestKeyring(
                provider=provider,
                key=cfg.get("api_key"),
                base_url=cfg.get("base_url") if provider.startswith("custom") else None,
                model_id=cfg.get("model_id"),
            )
        return keyrings
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        log.warning("Invalid X-BYOK-Config header: %s", type(exc).__name__)
        raise HTTPException(
            status_code=400, detail="Invalid BYOK configuration header"
        ) from exc


def validate_external_https_url(value: str | None) -> str:
    """Validate an external HTTPS URL without allowing private network targets."""
    if not value:
        raise HTTPException(status_code=422, detail="Provider base URL is required")
    parsed = urllib.parse.urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise HTTPException(
            status_code=422, detail="Provider base URL must be a public HTTPS URL"
        )
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {"localhost", "localhost.localdomain"}:
        raise HTTPException(
            status_code=422, detail="Private provider hosts are not allowed"
        )
    try:
        addresses = {
            ipaddress.ip_address(info[4][0])
            for info in socket.getaddrinfo(
                hostname, parsed.port or 443, type=socket.SOCK_STREAM
            )
        }
    except HTTPException:
        raise
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail="Provider host could not be resolved"
        ) from exc
    if not addresses or any(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        for address in addresses
    ):
        raise HTTPException(
            status_code=422, detail="Private provider hosts are not allowed"
        )
    return value.strip().rstrip("/")


def try_acquire_stream_slot(user_id: str) -> bool:
    """Reserve one of the bounded per-user streaming slots."""
    with _stream_counts_lock:
        current = _stream_counts.get(user_id, 0)
        if current >= _MAX_STREAMS_PER_USER:
            return False
        _stream_counts[user_id] = current + 1
        return True


def release_stream_slot(user_id: str) -> None:
    with _stream_counts_lock:
        current = _stream_counts.get(user_id, 0)
        if current <= 1:
            _stream_counts.pop(user_id, None)
        else:
            _stream_counts[user_id] = current - 1
