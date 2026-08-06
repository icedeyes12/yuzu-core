from __future__ import annotations

import os
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.models import ERROR_RESPONSES, AuthMeResponse, StatusResponse
from app.api.rate_limits import rate_limit_ip
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
    _COOKIE_SECURE,
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    create_session,
    revoke_session,
    set_session_cookie,
    validate_session,
)
from app.core.logging_config import get_logger
from app.db.facade import Database
from app.db.queries import DEFAULT_PROFILE_PARAMS

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _require_env(name: str) -> str:
    """Retrieve mandatory environment variable or raise 500."""
    val = os.environ.get(name)
    if not val:
        log.error("Missing required environment variable")
        raise HTTPException(status_code=500, detail="Server configuration error")
    return val.strip()


_OAUTH_CALLBACK_PATH = "/api/v1/auth/callback"


def _rewrite_redirect_uri(request: Request, original_uri: str) -> str:
    """Build the registered callback for the origin used by this request."""
    configured_origins = {
        origin.strip().rstrip("/")
        for origin in os.environ.get("OAUTH_REDIRECT_ORIGINS", "").split(",")
        if origin.strip()
    }
    forwarded_host = request.headers.get("x-forwarded-host")
    forwarded_proto = request.headers.get("x-forwarded-proto")
    if forwarded_host:
        scheme = (forwarded_proto or "https").split(",", 1)[0].strip()
        host = forwarded_host.split(",", 1)[0].strip()
    else:
        scheme = request.url.scheme
        host = request.url.netloc

    candidate_origin = f"{scheme}://{host}".rstrip("/")
    parsed = urlsplit(original_uri)
    original_origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip(
        "/"
    )
    if configured_origins and candidate_origin not in configured_origins:
        candidate_origin = original_origin

    return f"{candidate_origin}{_OAUTH_CALLBACK_PATH}"


@router.get("/login", response_model=None, responses=ERROR_RESPONSES)
async def login(request: Request, provider: str = "google"):
    rate_limit_ip(request, 10, "auth-login-ip")
    config = get_provider(provider)
    if not config:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    client_id = _require_env(config.client_id_env)
    redirect_uri = _require_env(config.redirect_uri_env)

    # Rewrite redirect_uri if behind Cloudflare
    redirect_uri = _rewrite_redirect_uri(request, redirect_uri)

    session_secret = _require_env("SESSION_SECRET")
    code_verifier, code_challenge = generate_pkce()

    # Capture the origin (where the login request came from) to redirect back to it after callback
    origin = request.headers.get("referer", "")
    state = sign_state(config.name, code_verifier, session_secret, origin)
    auth_url = build_auth_url(config, client_id, redirect_uri, code_challenge, state)

    # Allow cross-domain OAuth state cookie in development / proxy environments
    is_secure = (
        _COOKIE_SECURE
        or request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto") == "https"
    )

    # Cloudflare drops cookies without samesite="none" in cross-origin redirects
    samesite_policy = "none" if is_secure else "lax"

    log.info(
        "OAuth login: provider=%s redirect_uri='%s' origin='%s' is_secure=%s",
        provider,
        redirect_uri,
        origin,
        is_secure,
    )

    response = RedirectResponse(url=auth_url, status_code=302)
    response.set_cookie(
        key=OAUTH_STATE_COOKIE_NAME,
        value=state,
        max_age=600,
        httponly=True,
        secure=is_secure,
        samesite=samesite_policy,
        path="/",
    )

    return response


@router.get("/callback", include_in_schema=False, response_model=None)
async def callback(request: Request):
    rate_limit_ip(request, 30, "auth-callback-ip")
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        log.warning("OAuth Callback missing code or state")
        raise HTTPException(status_code=400, detail="Missing code or state")

    state_cookie = request.cookies.get(OAUTH_STATE_COOKIE_NAME)
    session_secret = _require_env("SESSION_SECRET")

    log.info(
        "OAuth Callback: state_present=%s, state_cookie_present=%s, request_cookie_names=%s",
        bool(state),
        bool(state_cookie),
        list(request.cookies.keys()),
    )

    if not state_cookie:
        log.error("OAuth State mismatch: state cookie is missing")
        raise HTTPException(status_code=400, detail="State mismatch")

    if state_cookie != state:
        log.error("OAuth State mismatch: cookie and query state differ")
        raise HTTPException(status_code=400, detail="State mismatch")

    verified = verify_state(state, session_secret)
    if not verified:
        log.error("OAuth State invalid or expired")
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    provider_name, code_verifier, origin = verified
    config = get_provider(provider_name)
    if not config:
        raise HTTPException(status_code=400, detail="Unknown provider in state")

    client_id = _require_env(config.client_id_env)
    client_secret = _require_env(config.client_secret_env)
    redirect_uri = _require_env(config.redirect_uri_env)

    # Rewrite redirect_uri for the token exchange to match what was sent in the login step
    redirect_uri = _rewrite_redirect_uri(request, redirect_uri)

    try:
        token_response = await exchange_code(
            config, client_id, client_secret, redirect_uri, code, code_verifier
        )
    except Exception as e:
        log.error(f"OAuth token exchange failed: {e}")
        raise HTTPException(status_code=502, detail="Token exchange failed")

    try:
        provider_sub, email, avatar_url, user_name = await resolve_identity(
            config, token_response, client_id
        )
    except Exception as e:
        log.error(f"Identity resolution failed: {e}")
        raise HTTPException(status_code=502, detail="Identity resolution failed")

    user_id = await _map_identity_to_profile(
        provider_name, provider_sub, email, avatar_url, user_name
    )
    token = await create_session(user_id)

    # Determine redirection target: if login originated from somewhere else (e.g. localhost:5000), redirect back to it
    redirect_target = "/chat"
    if origin:
        parsed_origin = urlsplit(origin)
        if parsed_origin.scheme in {"http", "https"} and parsed_origin.netloc:
            redirect_target = urlunsplit(
                (parsed_origin.scheme, parsed_origin.netloc, "/chat", "", "")
            )

    log.info(f"OAuth successful. Redirecting user to: {redirect_target}")
    response = RedirectResponse(url=redirect_target, status_code=302)
    set_session_cookie(response, token)
    response.delete_cookie(key=OAUTH_STATE_COOKIE_NAME, path="/")
    return response


async def _map_identity_to_profile(
    provider: str,
    provider_sub: str,
    email: str | None,
    avatar_url: str | None = None,
    user_name: str | None = None,
) -> str:
    existing = await Database.lookup_identity(provider, provider_sub)
    if existing:
        user_id = str(existing["user_id"])
        # Refresh avatar on each login (IdP may have updated it)
        if avatar_url:
            await Database.update_profile_avatar(user_id, avatar_url, datetime.now())
        return user_id

    unclaimed = await Database.lookup_unclaimed_profile()
    if unclaimed:
        user_id = str(unclaimed["id"])
    else:
        row = await Database.insert_default_profile_returning(
            DEFAULT_PROFILE_PARAMS, datetime.now(), datetime.now()
        )
        if not row:
            raise HTTPException(status_code=500, detail="Profile creation failed")
        user_id = str(row["id"])

    # Persist avatar + display name for new profiles
    if avatar_url:
        await Database.update_profile_avatar(user_id, avatar_url, datetime.now())
    if user_name:
        await Database.update_profile_user_name(user_id, user_name, datetime.now())

    await Database.insert_identity(user_id, provider, provider_sub, email)
    return user_id


@router.post("/logout", response_model=StatusResponse, responses=ERROR_RESPONSES)
async def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        _ = await revoke_session(token)
    response = JSONResponse({"status": "logged out"})
    response.headers["Cache-Control"] = "no-store"
    clear_session_cookie(response)
    return response


@router.get("/me", response_model=AuthMeResponse, responses=ERROR_RESPONSES)
async def me(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = await validate_session(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    row = await Database.lookup_auth_me(user_id)
    if not row:
        return {"user_id": user_id}
    return {
        "user_id": user_id,
        "email": row.get("email"),
        "user_name": row.get("user_name") or "",
        "avatar_url": row.get("avatar_url"),
    }
