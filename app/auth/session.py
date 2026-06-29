from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta

from app.db.facade import Database
from app.logging_config import get_logger

log = get_logger(__name__)

SESSION_COOKIE_NAME = "yuzu_session"
SESSION_TTL_DAYS = 7
_SESSION_MAX_AGE = SESSION_TTL_DAYS * 24 * 60 * 60

_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() == "true"


def generate_token() -> str:
    return secrets.token_urlsafe(32)


async def create_session(user_id: str) -> str:
    token = generate_token()
    now = datetime.now()
    expires_at = now + timedelta(days=SESSION_TTL_DAYS)
    await Database.create_session_token(token, user_id, now, expires_at)
    return token


async def validate_session(token: str) -> str | None:
    row = await Database.validate_session_token(token)
    if not row:
        return None
    return str(row["user_id"])


async def revoke_session(token: str) -> bool:
    await Database.revoke_session_token(token, datetime.now())
    return True


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=_SESSION_MAX_AGE,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="strict",
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
