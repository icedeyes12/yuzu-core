# FILE: app/api/utils.py
# DESCRIPTION: Shared utilities for API endpoints

from __future__ import annotations

from fastapi import Request


def get_client_id(request: Request) -> str:
    """Generate a client identifier from request metadata.
    
    Used for web client session tracking to prevent duplicate connection messages.
    """
    client_host = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    return f"{client_host}_{hash(user_agent) % 10000}"
