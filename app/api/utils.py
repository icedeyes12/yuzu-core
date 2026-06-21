# FILE: app/api/utils.py
# DESCRIPTION: Shared utilities for API endpoints

from __future__ import annotations

from fastapi import HTTPException, Request

from app.auth.session import SESSION_COOKIE_NAME, validate_session


def get_client_id(request: Request) -> str:
    """Generate a client identifier from request metadata.

    Used for web client session tracking to prevent duplicate connection messages.
    """
    client_host = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    return f"{client_host}_{hash(user_agent) % 10000}"


async def get_current_user(request: Request) -> str:
    """FastAPI dependency: extract authenticated user_id from session cookie.

    Returns the user_id UUID string or raises HTTPException(401).
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = await validate_session(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return user_id