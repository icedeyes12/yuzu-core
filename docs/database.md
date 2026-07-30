# Yuzu Companion Database Architecture

Yuzu Companion uses PostgreSQL with `pgcrypto`, `vector`, and `pg_trgm`. Database access uses raw `psycopg` v3; there is no ORM. The schema and shared SQL are defined in `app/db/queries.py`.

## Connection and ownership

- `app/db/connection.py` owns pooled synchronous/asynchronous access.
- `app/db/queries.py` is the SQL and DDL source of truth.
- Tenant-scoped tables reference `profiles(id)` through `user_id`.
- Application queries must include the owning `user_id` for every tenant-scoped read or write.
- Migrations are additive and must not introduce an alternate schema in business logic.

## Core tables

### `profiles`

User and companion settings. Location coordinates remain here and are not injected into the LLM prompt.

### `chat_sessions`

Conversation sessions owned by a profile. Sessions carry `user_id`, names, active/deleted state, message counts, and pipeline state.

### `messages`

Original conversation records. Messages have UUID identifiers in the current schema, `session_id`, `user_id`, role, content, attachments, tool fields, and timestamp. Memory maintenance treats them as source history and does not rewrite them.

### `episodes`

Summaries of eligible conversation batches. Each episode is tenant-scoped and tied to a session, with optional source message range and 1536-dimensional embedding.

### `memory_nodes`

Inferred claims/entities. Nodes contain `node_type`, content, optional 1536-dimensional embedding, confidence, importance, status, validity interval, and embedding metadata.

### `memory_edges`

Typed relationships between nodes. The schema enforces same-tenant ownership, unique endpoint/type tuples per tenant, and no self-loops.

### `memory_evidence`

Provenance for graph nodes and edges. It can point to an episode and/or source message. The target must be a node or edge.

### `global_knowledge_entries`

Explicit user-managed knowledge. It is separate from inferred graph memory and is read/written through its own API operations.

## Graph constraints

The graph schema includes:

- tenant foreign keys through `user_id`;
- confidence and importance checks between `0` and `1`;
- temporal validity columns;
- foreign keys from edges/evidence to graph objects;
- unique edge identity per tenant, endpoint pair, and type;
- self-loop prevention;
- indexes for active nodes, validity, creation time, edge endpoints, evidence targets, source messages, and episodes;
- trigram indexing for node content;
- native pgvector columns using dimension `1536`.

## Memory flow

```text
messages
  -> batch extraction
  -> episodes + memory_nodes + memory_edges + memory_evidence
  -> vector/trigram graph retrieval
  -> prompt presentation
```

`global_knowledge_entries` enters prompt construction as a separate explicit context source. It is never silently merged into inferred graph memory.

## Security and configuration

Provider keys use the BYOK browser flow described in `AGENTS.md`; do not recreate the retired `api_keys` persistence path. User location stays in the database and is resolved by the weather tool when needed. Memory queries and graph maintenance must never leak data across tenants.

## Maintenance

Run the graph-only maintenance helper from the Memory Guardian skill:

```bash
python3 /home/workspace/Skills/memory-guardian/scripts/memory_review.py \
  --format markdown --report /home/workspace/MemoryGuardian-report.md
```

The helper is read-only by default. Its opt-in repair path is limited to high-confidence exact duplicate-node merges and never hard-deletes graph rows or evidence.

## Maintenance boundary

Legacy semantic-memory schema and review workflows are outside the current architecture. Do not introduce an alternate memory table, review queue, or decay workflow into current SQL or maintenance code.
