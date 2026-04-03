# PostgreSQL Migration Roadmap — Yuzu Companion

## Context

Migrated AI companion database from SQLite (`yuzu_core.db`) to PostgreSQL (`yuzuki`) on Termux.
A migration script (`b.py`) unified three separate memory tables into one vector-enabled table.

### New PostgreSQL Schema

- **Database**: `yuzuki`
- **Primary Table**: `semantic_facts`
- **Columns**: `id (SERIAL PK)`, `fact_type (VARCHAR)`, `content (TEXT)`, `embedding (VECTOR)`, `metadata (JSONB)`, `created_at (TIMESTAMP)`, `last_accessed (TIMESTAMP)`
- **Index**: `ivfflat` on embedding for ANN search

---

## Migration Complete ✅

**All phases completed on 2026-04-03.**

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | ✅ Done | Scaffolding & Connection Layer (`db_pg.py`) |
| 2 | ✅ Done | Hybrid Library: SQLAlchemy + psycopg2 |
| 3 | ✅ Done | `db_memory.py` — unified memory CRUD |
| 4 | ✅ Done | `embedder.py` — removed blob functions |
| 5 | ✅ Done | `vector_store.py` — deprecated, stub to db_memory |
| 6 | ✅ Done | `retrieval.py` — PostgreSQL vector search |
| 7 | ✅ Done | `memory_store.py` — uses db_memory |
| 8 | ✅ Done | `extractor.py`, `segmenter.py`, `review.py` — all use db_memory |
| 9 | ✅ Done | Migration scripts — deprecated (data already migrated) |
| 10 | ✅ Done | Cleanup & Docs — updated README, CHANGELOG |

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────┐
│                    POSTGRESQL (yuzuki)                       │
├─────────────────────────────────────────────────────────────┤
│  SQLAlchemy-style ORM via psycopg2 (db_pg_models.py):       │
│    ✅ profiles, chat_sessions, messages, api_keys            │
├─────────────────────────────────────────────────────────────┤
│  Raw psycopg2 (db_memory.py):                                │
│    ✅ semantic_facts (vector-enabled, pgvector)              │
└─────────────────────────────────────────────────────────────┘

NO SQLite. NO yuzu_core.db. All data in PostgreSQL.
```

---

## Key Design Decisions

1. **Hybrid Library (NOT Hybrid Database)**: SQLAlchemy-style operations via raw psycopg2. All data in PostgreSQL, no SQLite.
2. **Unified `semantic_facts`**: All memory types go into one table. `fact_type` + `metadata` differentiate static vs dynamic vs episodic vs segments.
3. **No ORM for vectors**: psycopg2 handles `list[float]` embeddings natively with pgvector. No serialization/deserialization needed.
4. **Backward compat**: Keep `vector_store.py` as stub to avoid import breakage across the codebase.
5. **Raw SQL preferred for memory ops**: No heavy ORM for memory. Fast, Termux-friendly.
6. **SQLAlchemy URL**: `postgresql://user:pass@host:port/dbname` instead of `sqlite:///path/to/file.db`
