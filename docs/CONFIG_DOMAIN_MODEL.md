# Configuration Domain Model

This document defines the contracts for the four configuration domains. It is behavior-preserving by design.

## Non-Negotiable Boundaries

- `ApplicationConfig` is server-owned and `.env`-backed. No field from this domain reaches the user config page payload.
- `UserPreferences` is user-owned and DB-backed.
- `RuntimeContext` is request-scoped and ephemeral.
- `CredentialProvider` is user-owned and must remain out of server-side persistence.

## Domain Interfaces

### ApplicationConfig

Responsibility: describe how the process should run.

Fields:
- database.dsn, database.pool_*
- auth.session_secret, auth.cookie_secure
- auth.oauth_providers[].client_id, client_secret, redirect_uri, issuer, jwks_url
- server.app_base_url, server.log_level
- runtime.termux_bash, runtime.default_cwd
- feature flags: enable_signup, enable_*

Lifecycle:
- Loaded once at startup from `.env` and sealed.
- Can expose `is_defined(key)` / `require(key)` helpers.
- No hot reload; changes require restart.

Observability rule:
- Never include these values in API responses, logs shown to users, or config-page payloads.

### UserPreferences

Responsibility: describe the user’s non-secret choices.

Fields:
- identity: assistant_name, user_name, persona, theme, affection
- provider: preferred_provider, preferred_model, vision_model_preferences
- behavior: generation.*, reasoning.*, ui.*
- profile: display_name, partner_name

Storage target:
- `profiles.providers_config`
- `profiles.theme`, `profiles.affection`, `profiles.image_model`, `profiles.vision_model`
- `profiles.context` only for non-secret client-provided state such as location.

Contract:
- Read/write operations go through `get_profile_async`, `update_profile_async`.
- Frontend reads via `/api/config` and `/api/profile`.
- Frontend writes via typed endpoints; generic dict update paths are allowed only when the contract explicitly supports them.

### RuntimeContext

Responsibility: package everything a provider needs for a single LLM call.

Fields:
- provider: name
- model: model_id
- credential: api_key or sentinel indicating unavailable
- routing: base_url, retry, timeout
- runtime: request metadata

Precedence:
1. Request header / client-provided value
2. User preference from `UserPreferences`
3. Provider default

Lifecycle:
- Created per request.
- Destroyed after response.
- Never persisted.

### CredentialProvider

Responsibility: supply credentials for the current request only.

Methods:
- `for_request(req) -> CredentialHandle`
- `is_available(provider) -> bool`

Allowed sources:
- Browser keyring via request header
- Operator-injected system secret via current runtime envelope

Prohibited sources after Phase 3:
- `api_keys` table
- decrypted credential fields in DB
- `.env` for user-provided credentials

## Contract Rules

- Every provider decision must flow through `RuntimeContext`.
- Every preference read must flow through `UserPreferences`.
- Every application setting read must flow through `ApplicationConfig`.
- No module should reach into raw profile dict keys outside a defined mapping.
- Config page must not infer credential state by probing raw DB rows.
