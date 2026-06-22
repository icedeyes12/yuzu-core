from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.auth.oauth import (
    OAUTH_STATE_COOKIE_NAME,
    build_auth_url,
    exchange_code,
    generate_pkce,
    get_provider,
    resolve_identity,
    sign_state,
    verify_state,
)
from app.auth.session import (
    SESSION_COOKIE_NAME,
    _COOKIE_SECURE,
    clear_session_cookie,
    create_session,
    revoke_session,
    set_session_cookie,
    validate_session,
)
from app.db.connection import pg_execute_async, pg_fetchone_async
from app.db.queries import (
    DEFAULT_PROFILE_PARAMS,
    SQL_AUTH_ME_LOOKUP,
    SQL_IDENTITY_INSERT,
    SQL_IDENTITY_LOOKUP,
    SQL_PROFILE_INSERT_DEFAULT_RETURNING,
    SQL_PROFILE_UNCLAIMED_LOOKUP,
    SQL_PROFILE_UPDATE_AVATAR,
)
from app.logging_config import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise HTTPException(status_code=500, detail=f"Missing env var: {name}")
    return val.strip()


@router.get("/login")
async def login(provider: str = "google"):
    config = get_provider(provider)
    if not config:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    client_id = _require_env(config.client_id_env)
    redirect_uri = _require_env(config.redirect_uri_env)
    session_secret = _require_env("SESSION_SECRET")

    code_verifier, code_challenge = generate_pkce()
    state = sign_state(provider, code_verifier, session_secret)
    auth_url = build_auth_url(config, client_id, redirect_uri, code_challenge, state)

    log.info("OAuth login: provider=%s redirect_uri='%s'", provider, redirect_uri)

    response = RedirectResponse(url=auth_url, status_code=302)
    response.set_cookie(
        key=OAUTH_STATE_COOKIE_NAME,
        value=state,
        max_age=600,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/callback")
async def callback(request: Request):
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    state_cookie = request.cookies.get(OAUTH_STATE_COOKIE_NAME)
    session_secret = _require_env("SESSION_SECRET")
    if not state_cookie or state_cookie != state:
        raise HTTPException(status_code=400, detail="State mismatch")

    verified = verify_state(state, session_secret)
    if not verified:
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    provider_name, code_verifier = verified
    config = get_provider(provider_name)
    if not config:
        raise HTTPException(status_code=400, detail="Unknown provider in state")

    client_id = _require_env(config.client_id_env)
    client_secret = _require_env(config.client_secret_env)
    redirect_uri = _require_env(config.redirect_uri_env)

    try:
        token_response = await exchange_code(
            config, client_id, client_secret, redirect_uri, code, code_verifier
        )
    except Exception as e:
        log.error("OAuth token exchange failed: %s", e)
        raise HTTPException(status_code=502, detail="Token exchange failed")

    try:
        provider_sub, email, avatar_url, display_name = await resolve_identity(
            config, token_response, client_id
        )
    except Exception as e:
        log.error("Identity resolution failed: %s", e)
        raise HTTPException(status_code=502, detail="Identity resolution failed")

    user_id = await _map_identity_to_profile(
        provider_name, provider_sub, email, avatar_url, display_name
    )
    token = await create_session(user_id)

    redirect_target = os.environ.get("APP_BASE_URL") or "/"
    response = RedirectResponse(url=redirect_target, status_code=302)
    set_session_cookie(response, token)
    response.delete_cookie(key=OAUTH_STATE_COOKIE_NAME, path="/")
    return response


async def _map_identity_to_profile(
    provider: str,
    provider_sub: str,
    email: str | None,
    avatar_url: str | None = None,
    display_name: str | None = None,
) -> str:
    existing = await pg_fetchone_async(SQL_IDENTITY_LOOKUP, (provider, provider_sub))
    if existing:
        user_id = str(existing["user_id"])
        # Refresh avatar + display name on each login (IdP may have updated them)
        if avatar_url:
            await pg_execute_async(
                SQL_PROFILE_UPDATE_AVATAR,
                (avatar_url, datetime.now(), user_id),
            )
        if display_name:
            from app.db.queries import build_profile_update

            q, params = build_profile_update({"display_name": display_name}) or ("", [])
            if q:
                params.append(user_id)
                await pg_execute_async(f"{q} WHERE id = %s", params)
        return user_id

    unclaimed = await pg_fetchone_async(SQL_PROFILE_UNCLAIMED_LOOKUP)
    if unclaimed:
        user_id = str(unclaimed["id"])
    else:
        row = await pg_fetchone_async(
            SQL_PROFILE_INSERT_DEFAULT_RETURNING,
            (*DEFAULT_PROFILE_PARAMS, datetime.now(), datetime.now()),
        )
        if not row:
            raise HTTPException(status_code=500, detail="Profile creation failed")
        user_id = str(row["id"])

    # Persist avatar + display name for new profiles
    if avatar_url:
        await pg_execute_async(
            SQL_PROFILE_UPDATE_AVATAR,
            (avatar_url, datetime.now(), user_id),
        )
    if display_name:
        from app.db.queries import build_profile_update

        q, params = build_profile_update({"display_name": display_name}) or ("", [])
        if q:
            params.append(user_id)
            await pg_execute_async(f"{q} WHERE id = %s", params)

    await pg_execute_async(
        SQL_IDENTITY_INSERT, (user_id, provider, provider_sub, email)
    )
    return user_id


@router.post("/logout")
async def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        await revoke_session(token)
    response = JSONResponse({"status": "logged out"})
    clear_session_cookie(response)
    return response


@router.get("/me")
async def me(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = await validate_session(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    row = await pg_fetchone_async(SQL_AUTH_ME_LOOKUP, (user_id,))
    if not row:
        return {"user_id": user_id}
    return {
        "user_id": user_id,
        "email": row.get("email"),
        "display_name": row.get("display_name") or "",
        "avatar_url": row.get("avatar_url"),
    }
