# ADR 0002: RFC 9457 Problem Details for Errors

- Status: Accepted
- Date: 2026-08-03

## Context

Previously, errors were emitted as a mixture of `detail`, `message`, and endpoint-specific objects. This makes generic client error handling unreliable.

## Decision

Centralize FastAPI, validation, authentication, authorization, rate-limit, database, and unexpected-error handling in `app/api/errors.py`. Responses use `application/problem+json` and include `type`, `title`, `status`, `detail`, and a request correlation ID. Endpoint-level handlers remain only where they add domain-specific behavior.

## Consequences

Clients can parse all failures through one contract. Legacy success responses are unaffected. Error details must remain safe for public responses; server logs carry diagnostic context.
