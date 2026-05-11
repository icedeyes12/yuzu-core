# PostgreSQL Migration — Completed

Migration dari SQLite ke PostgreSQL selesai pada **2026-04-03**.

## Arsitektur Saat Ini

```
PostgreSQL (yuzuki)
├── db_pg.py              — Connection pool + PgSession context manager
├── db_pg_models.py       — CRUD untuk profiles, sessions, messages, api_keys
└── db_memory.py          — Unified memory layer (semantic_facts + pgvector)
```

## Tabel Utama

| Tabel | Deskripsi |
|-------|-----------|
| `profiles` | User/companion settings, provider config |
| `chat_sessions` | Session tracking |
| `messages` | Conversation log |
| `api_keys` | Encrypted API keys |
| `semantic_facts` | Unified memory dengan `VECTOR(1024)` |

## Memory Types (`semantic_facts.fact_type`)

| fact_type | Scope | Decay |
|-----------|-------|-------|
| `static` | Global | No (uses `invalid_at`) |
| `dynamic` | Per-session | FSRS-style |

## Detail Lengkap

Lihat `app/memory/docs/architecture.md` untuk dokumentasi lengkap.
