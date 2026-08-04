# ADR 0004: Modular Prometheus Metrics Foundation

- Status: Accepted
- Date: 2026-08-03

## Context

The service needs operational visibility without coupling application code to a complete monitoring stack.

## Decision

Use the small abstraction in `app/metrics.py` for request count, active requests, response status, and duration. Expose Prometheus text at `/metrics`. Instrumentation is middleware-based; business metrics can be added to the abstraction without changing routers.

## Consequences

Metrics remain scrape-compatible and low overhead. Label cardinality must stay bounded; user IDs, URLs with unbounded parameters, and request bodies must not become labels.
