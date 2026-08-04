# ADR 0003: Version the HTTP API at `/api/v1`

- Status: Accepted
- Date: 2026-08-03

## Context

The API needs room for contract evolution without breaking the browser client or external integrations.

## Decision

Serve the public router under `/api/v1`. The frontend uses the versioned paths. Compatibility aliases that existed before the migration remain where practical but are hidden from OpenAPI. Future incompatible changes require a new version rather than silently changing `/api/v1`.

## Consequences

Generated clients receive a stable namespace. The compatibility aliases add a small maintenance cost and can be removed only after a deprecation period.
