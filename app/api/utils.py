from __future__ import annotations

import hashlib

from fastapi import HTTPException, Request

from app.auth.session import SESSION_COOKIE_NAME, validate_session


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
