from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt

from app.logging_config import get_logger

log = get_logger(__name__)

OAUTH_STATE_COOKIE_NAME = "_oauth_state"
_OAUTH_STATE_MAX_AGE = 600


@dataclass(frozen=True)
class OAuthProviderConfig:
    name: str
    auth_url: str
    token_url: str
    scopes: list[str]
    redirect_uri_env: str
    client_id_env: str
    client_secret_env: str
    has_id_token: bool


_GOOGLE = OAuthProviderConfig(
    name="google",
    auth_url="https://accounts.google.com/o/oauth2/v2/auth",
    token_url="https://oauth2.googleapis.com/token",
    scopes=["openid", "email", "profile"],
    redirect_uri_env="OAUTH_GOOGLE_REDIRECT_URI",
    client_id_env="OAUTH_GOOGLE_CLIENT_ID",
    client_secret_env="OAUTH_GOOGLE_CLIENT_SECRET",
    has_id_token=True,
)

_GITHUB = OAuthProviderConfig(
    name="github",
    auth_url="https://github.com/login/oauth/authorize",
    token_url="https://github.com/login/oauth/access_token",
    scopes=["read:user", "user:email"],
    redirect_uri_env="OAUTH_GITHUB_REDIRECT_URI",
    client_id_env="OAUTH_GITHUB_CLIENT_ID",
    client_secret_env="OAUTH_GITHUB_CLIENT_SECRET",
    has_id_token=False,
)

_PROVIDERS: dict[str, OAuthProviderConfig] = {
    "google": _GOOGLE,
    "github": _GITHUB,
}

_GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_GOOGLE_ISSUER = "https://accounts.google.com"


def get_provider(name: str) -> OAuthProviderConfig | None:
    return _PROVIDERS.get(name)


def generate_pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def sign_state(provider: str, verifier: str, secret: str) -> str:
    payload = json.dumps({"p": provider, "v": verifier, "t": int(time.time())})
    token = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()
    return f"{token}.{sig}"


def verify_state(state: str, secret: str) -> tuple[str, str] | None:
    try:
        token_b64, sig = state.rsplit(".", 1)
        expected = hmac.new(secret.encode(), token_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(token_b64))
        if int(time.time()) - payload["t"] > _OAUTH_STATE_MAX_AGE:
            return None
        return payload["p"], payload["v"]
    except Exception:
        return None


def build_auth_url(
    config: OAuthProviderConfig,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    state: str,
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(config.scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{config.auth_url}?{urlencode(params)}"


async def exchange_code(
    config: OAuthProviderConfig,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    code_verifier: str,
) -> dict:
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
    }
    headers = {"Accept": "application/json"}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(config.token_url, data=data, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _verify_google_id_token(id_token: str, client_id: str) -> dict:
    jwks_client = jwt.PyJWKClient(_GOOGLE_JWKS_URL)
    signing_key = jwks_client.get_signing_key_from_jwt(id_token)
    return jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=client_id,
        issuer=_GOOGLE_ISSUER,
    )


async def _get_github_identity(access_token: str) -> tuple[str, str | None]:
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get("https://api.github.com/user", headers=headers)
        resp.raise_for_status()
        data = resp.json()
        provider_sub = str(data["id"])
        email = data.get("email")
        if not email:
            emails_resp = await client.get(
                "https://api.github.com/user/emails", headers=headers
            )
            emails_resp.raise_for_status()
            for entry in emails_resp.json():
                if entry.get("primary") and entry.get("verified"):
                    email = entry["email"]
                    break
        return provider_sub, email


async def resolve_identity(
    config: OAuthProviderConfig,
    token_response: dict,
    client_id: str,
) -> tuple[str, str | None]:
    if config.has_id_token:
        id_token = token_response.get("id_token")
        if not id_token:
            raise ValueError("Token response missing id_token")
        claims = await _verify_google_id_token(id_token, client_id)
        return claims["sub"], claims.get("email")
    access_token = token_response.get("access_token")
    if not access_token:
        raise ValueError("Token response missing access_token")
    return await _get_github_identity(access_token)
