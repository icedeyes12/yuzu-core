# ADR 0005: Proxy-Friendly SSE Lifecycle

- Status: Accepted
- Date: 2026-08-03

## Context

Long-running streams can be closed by proxies during periods with no data, and abandoned clients can leave work and slots allocated.

## Decision

Use the shared stream lifecycle in `app/services/conversation_service.py`: periodic SSE comment heartbeats, an idle timeout, disconnect detection, no-buffer headers, and one cleanup path that releases stream capacity. Stream metadata is advertised through response headers and the shared model.

## Consequences

Idle connections remain proxy-friendly and abandoned streams are bounded. Clients must tolerate comment frames and reconnect when the idle timeout is reached.
