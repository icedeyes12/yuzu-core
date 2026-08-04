# API Routing Package

FastAPI API package for the Yuzu Companion web interface. HTTP API endpoints are served under `/api/v1`; `/health` and `/health/ready` remain unversioned for infrastructure probes.

## Current contract

- `POST /api/v1/send_message` — synchronous message handling
- `POST /api/v1/send_message_stream` — authenticated SSE message handling
- `GET /api/v1/profile` and `POST /api/v1/update_profile` — profile read/update
- `GET /api/v1/chat_history` — authenticated history, with `limit` constrained to 1–1000
- `GET /api/v1/chat_history/before` — ISO-8601 cursor pagination
- `DELETE /api/v1/sessions/{session_id}` — delete a session
- `DELETE /api/v1/presets/{name}` — delete a preset
- `PUT /api/v1/global-knowledge/{entry_id}` — replace a knowledge entry
- `GET /health` — liveness probe
- `GET /health/ready` — readiness probe with a PostgreSQL `SELECT 1` check

Uploaded and generated images are served only through authenticated `/api/v1/static/...` routes. BYOK configuration remains client-side and is sent in the bounded `X-BYOK-Config` header; provider base URLs must be public HTTPS hosts.

The old POST deletion routes remain hidden compatibility aliases and are not included in the OpenAPI schema.
