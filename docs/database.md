# Database Architecture

Yuzu-Companion uses a PostgreSQL database with the `pgvector` extension. The database architecture is designed for direct SQL access using `psycopg` (v3) rather than an ORM, prioritizing performance and explicit control over queries.

## Connection Management

The database uses connection pooling managed in `app/db/connection.py`. Both synchronous and asynchronous connection pools are maintained to serve different parts of the application:
- **Synchronous Pool:** Used by background processes, CLI tasks, and the memory pipeline.
- **Asynchronous Pool:** Used by FastAPI endpoints to serve web requests without blocking the ASGI event loop.

## Schema Overview

The single source of truth for all SQL queries and Data Definition Language (DDL) is `app/db/queries.py`.

### Core Tables

1. **`profiles`**
   - Stores user and companion settings.
   - Key fields: `display_name`, `partner_name`, `affection`, `memory_json`, `providers_config_json`.

2. **`chat_sessions`**
   - Tracks individual conversation threads.
   - Key fields: `name`, `is_active`, `message_count`.

3. **`messages`**
   - The primary conversation log.
   - Key fields: `session_id`, `role`, `content`, `image_paths`.

4. **`api_keys`**
   - Stores encrypted API keys at rest using ChaCha20-Poly1305.
   - Key fields: `provider`, `encrypted_key`.

5. **`semantic_facts`**
   - The unified memory store for both episodic and semantic facts.
   - Key fields: `fact_type`, `content`, `embedding` (VECTOR(1024)), `metadata` (JSONB).

## CRUD Operations

To separate concerns, the database layer provides identical sets of operations for both sync and async contexts:
- **`app/db/models.py`**: Synchronous functions for querying and mutating data.
- **`app/db/models_async.py`**: Asynchronous counterparts using `AsyncPgSession`.

## The Database Facade

`app/db/facade.py` exposes a stable `Database` class that provides a unified interface. It handles default `session_id` routing and acts as a central proxy for the underlying model functions.