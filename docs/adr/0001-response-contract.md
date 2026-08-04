# ADR 0001: Reusable API Response Contract

- Status: Accepted
- Date: 2026-08-03

## Context

Yuzu's HTTP API has both legacy response shapes and newer typed responses. Repeating ad-hoc Pydantic models makes OpenAPI drift likely and makes clients handle each endpoint differently.

## Decision

Keep legacy success payloads compatible while centralizing reusable response models in `app/api/models.py`. Public endpoints should declare `response_model` and reuse shared error metadata. New list and paginated endpoints use the shared list/pagination models rather than defining equivalent local schemas.

## Consequences

Existing clients keep their current JSON fields. OpenAPI gains stable reusable schemas. A future `/api/v2` contract can change envelopes deliberately without silently changing `/api/v1`.
