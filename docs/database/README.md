# Database architecture

**Status:** Active reference. SQL/DDL authority: `app/db/queries.py`.

Yuzu Companion uses PostgreSQL through psycopg v3 pools. The schema enables `pgcrypto`, `vector`, and `pg_trgm`. There is no ORM.

## Ownership

- `app/db/connection.py` owns sync/async pool lifecycle.
- `app/db/queries.py` owns SQL constants, DDL, row parsers, encryption helpers, and schema bootstrap statements.
- `app/db/facade.py` exposes the high-level database API used by services.
- `app/db/models_async.py` implements the async persistence operations.

## Core tables

| Table | Role |
|---|---|
| `profiles` | Tenant root and profile/configuration data |
| `chat_sessions` | User-owned conversation sessions |
| `messages` | Raw conversation, tool-call, attachment, timestamp, and encryption-state records |
| `episodes` | Structured summaries of eligible conversation batches |
| `memory_nodes` | Inferred claims/entities with confidence, importance, status, validity, and optional embeddings |
| `memory_edges` | Typed relationships between graph nodes |
| `memory_evidence` | Provenance linking graph records to source messages/episodes |
| `global_knowledge_entries` | Explicit user-managed knowledge kept separate from inferred graph memory |
| `user_identities` / `user_sessions` | OAuth identity links and authenticated session state |

Graph embeddings use `vector(1536)`, matching `app/memory/embedder.py` and `app/memory/graph.py`.

## Invariants

- Tenant-scoped reads and writes include `user_id`.
- Tenant foreign keys preserve ownership and cascade from the profile.
- Graph confidence and importance are constrained to `0..1`.
- Edges reject self-loops and duplicate tenant/endpoint/type combinations.
- Evidence targets a node or edge and retains provenance.
- Validity uses explicit time bounds and node status.
- Provider keys are not stored in an `api_keys` table. They arrive through request-scoped BYOK configuration.
- Conversation content can be encrypted with ChaCha20-Poly1305 and marked through `messages.content_encrypted`.
- Legacy columns may exist as migration artifacts; they are not part of the fresh `SCHEMA_DDL` contract.

## Memory relationship

```text
messages
  -> eligible batch
  -> episodes + memory_nodes + memory_edges + memory_evidence
  -> vector/trigram retrieval
  -> prompt context
```

The Memory Guardian skill is an operational maintenance tool, not part of application startup or extraction. Its repair behavior must remain conservative and tenant-scoped.

## Safe schema changes

Inspect `SCHEMA_DDL` and relevant queries before modifying persistence. Keep schema ownership in `app/db/queries.py`; do not add a second DDL source to services, tools, or documentation. Validate database changes with the database tests and, where available, an isolated PostgreSQL integration run.
