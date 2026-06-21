from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from app.db.connection import pg_execute_async, pg_fetchone_async
from app.db.queries import (
    SQL_SESSION_TOKEN_CREATE,
    SQL_SESSION_TOKEN_REVOKE,
    SQL_SESSION_TOKEN_VALIDATE,
)
from app.logging_config import get_logger

log = get_logger(__name__)

SESSION_COOKIE_NAME = "yuzu_session"
SESSION_TTL_DAYS = 7
_SESSION_MAX_AGE = SESSION_TTL_DAYS * 24 * 60 * 60


def generate_token() -> str:
    return secrets.token_urlsafe(32)


async def create_session(user_id: str) -> str:
    token = generate_token()
    now = datetime.now()
    expires_at = now + timedelta(days=SESSION_TTL_DAYS)
    await pg_execute_async(
        SQL_SESSION_TOKEN_CREATE,
        (token, user_id, now, expires_at),
    )
    return token


async def validate_session(token: str) -> str | None:
    row = await pg_fetchone_async(SQL_SESSION_TOKEN_VALIDATE, (token,))
    if not row:
        return None
    return str(row["user_id"])


async def revoke_session(token: str) -> bool:
    await pg_execute_async(SQL_SESSION_TOKEN_REVOKE, (datetime.now(), token))
    return True


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=_SESSION_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
