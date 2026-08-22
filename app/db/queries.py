"""Single source of truth for SQL strings, schema DDL, row parsers, and shared constants."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from app.providers.openai_protocol import normalize_tool_calls

type DBRow = dict[str, Any]


def encrypt_api_key(api_key: str) -> str:
    """Encrypt an API key with the project-wide encryptor."""
    from app.core.encryption import encryptor

    return encryptor.encrypt(api_key)


def decrypt_api_key(encrypted_key: str, is_encrypted: bool = True) -> str:
    """Decrypt an API key. Returns sentinel on failure."""
    if not is_encrypted:
        return encrypted_key
    from app.core.encryption import encryptor

    try:
        return encryptor.decrypt(encrypted_key)
    except Exception:  # noqa: BLE001 - any failure means "can't decrypt"
        return "[DECRYPTION_ERROR]"


DECRYPTION_ERROR = "[DECRYPTION_ERROR]"

# Schema DDL — multi-tenant: profiles/chat_sessions use UUIDv7 PKs,
# all tenant-scoped tables have user_id FK → profiles(id) ON DELETE CASCADE.
#
# Legacy migration columns (legacy_int_id, legacy_session_id, memory_json)
# are NOT included — they are migration artifacts only and must not exist
# on fresh installs.
# ---------------------------------------------------------------------------

SCHEMA_DDL: tuple[str, ...] = (
    # ── Extensions ──
    "CREATE EXTENSION IF NOT EXISTS pgcrypto",
    "CREATE EXTENSION IF NOT EXISTS vector",
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    # ── UUIDv7 generator (time-ordered, lexicographically sortable) ──
    """
    CREATE OR REPLACE FUNCTION generate_uuidv7()
    RETURNS UUID AS $function$
    DECLARE
      unix_ts_ms BIGINT;
      rand_hex TEXT;
    BEGIN
      unix_ts_ms := (EXTRACT(EPOCH FROM clock_timestamp()) * 1000)::BIGINT;
      rand_hex := replace(gen_random_uuid()::text, '-', '');
      RETURN (
        lpad(to_hex(unix_ts_ms), 12, '0')
        || '7'
        || substring(rand_hex, 14, 3)
        || substring(rand_hex, 17, 4)
        || substring(rand_hex, 21, 12)
      )::UUID;
    END;
    $function$ LANGUAGE plpgsql VOLATILE
    """,
    # ── profiles (tenant root — PK is UUID, referenced by all user_id FKs) ──
    """
    CREATE TABLE IF NOT EXISTS profiles (
        id UUID NOT NULL DEFAULT generate_uuidv7() PRIMARY KEY,
        user_name VARCHAR(255) NOT NULL DEFAULT '',
        partner_name VARCHAR(255) NOT NULL DEFAULT '',
        affection INTEGER NOT NULL DEFAULT 50,
        theme VARCHAR(255) NOT NULL DEFAULT 'default',
        session_history JSONB NOT NULL DEFAULT '{}',
        providers_config JSONB NOT NULL DEFAULT '{}',
        model_parameters JSONB NOT NULL DEFAULT '{}',
        image_model TEXT,
        image_provider TEXT,
        image_endpoint TEXT,
        image_edit_provider TEXT,
        image_edit_endpoint TEXT,
        image_extra_body JSONB,
        image_edit_extra_body JSONB,
        location_lat REAL,
        location_lon REAL,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        timestamp TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'profiles' AND column_name = 'context'
      ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'profiles' AND column_name = 'model_parameters'
      ) THEN
        ALTER TABLE profiles RENAME COLUMN context TO model_parameters;
      END IF;
    END $$
    """,
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS image_endpoint TEXT",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS image_edit_endpoint TEXT",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS image_extra_body JSONB",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS image_edit_extra_body JSONB",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS image_provider TEXT",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS image_edit_provider TEXT",
    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS image_model TEXT",
    # ── global_knowledge_entries (explicit user-managed facts) ──
    """
    CREATE TABLE IF NOT EXISTS global_knowledge_entries (
        id UUID NOT NULL DEFAULT generate_uuidv7() PRIMARY KEY,
        user_id UUID NOT NULL,
        category VARCHAR(255) NOT NULL DEFAULT '',
        content TEXT NOT NULL,
        sort_order INTEGER NOT NULL DEFAULT 0,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
    )
    """,
    """
    DO $migration$
    BEGIN
      IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'profiles' AND column_name = 'global_knowledge'
      ) THEN
        EXECUTE $sql$
          INSERT INTO global_knowledge_entries
            (user_id, category, content, sort_order, enabled)
          SELECT p.id,
                 COALESCE(NULLIF(item->>'category', ''), 'General'),
                 item->>'content',
                 (item_position - 1)::integer,
                 TRUE
          FROM profiles p
          CROSS JOIN LATERAL (
            SELECT item, item_position
            FROM jsonb_array_elements(
              CASE
                WHEN jsonb_typeof(p.global_knowledge->'facts') = 'array'
                THEN p.global_knowledge->'facts'
                ELSE '[]'::jsonb
              END
            ) WITH ORDINALITY AS array_items(item, item_position)
            UNION ALL
            SELECT jsonb_build_object(
                     'category', 'General',
                     'content', p.global_knowledge->>'facts'
                   ),
                   1
            WHERE jsonb_typeof(p.global_knowledge->'facts') = 'string'
          ) legacy_items
          WHERE NULLIF(BTRIM(item->>'content'), '') IS NOT NULL
            AND NOT EXISTS (
              SELECT 1 FROM global_knowledge_entries existing
              WHERE existing.user_id = p.id
            )
        $sql$;
        ALTER TABLE profiles DROP COLUMN global_knowledge;
      END IF;
    END
    $migration$
    """,
    # ── chat_sessions (PK UUID, tenant FK user_id → profiles) ──
    """
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id UUID NOT NULL DEFAULT generate_uuidv7() PRIMARY KEY,
        user_id UUID NOT NULL,
        name VARCHAR(255) NOT NULL DEFAULT 'New Chat',
        is_active BOOLEAN NOT NULL DEFAULT FALSE,
        message_count INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        deleted_at TIMESTAMP DEFAULT NULL,
        timestamp TIMESTAMP DEFAULT NOW(),
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
    )
    """,
    # ── messages (id UUID, session_id + user_id are UUID FKs) ──
    """
    CREATE TABLE IF NOT EXISTS messages (
        id UUID NOT NULL DEFAULT generate_uuidv7() PRIMARY KEY,
        session_id UUID,
        user_id UUID NOT NULL,
        role VARCHAR(50) NOT NULL,
        content TEXT NOT NULL,
        content_encrypted BOOLEAN NOT NULL DEFAULT FALSE,
        attachments JSONB DEFAULT '[]',
        tool_calls JSONB,
        tool_call_id VARCHAR,
        turn_id VARCHAR,
        timestamp VARCHAR NOT NULL,
        FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS file_objects (
        id UUID PRIMARY KEY,
        owner_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        storage_key TEXT NOT NULL UNIQUE,
        original_name TEXT,
        mime_type TEXT NOT NULL,
        size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
        kind TEXT NOT NULL CHECK (kind IN (
            'upload', 'attachment', 'generated_image', 'generated_file',
            'sandbox_artifact', 'export'
        )),
        source TEXT NOT NULL,
        job_id UUID NULL,
        status TEXT NOT NULL CHECK (status IN ('pending', 'ready')),
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
        deleted_at TIMESTAMP NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_file_objects_owner_active ON file_objects (owner_id, status) WHERE deleted_at IS NULL",
    """
    CREATE TABLE IF NOT EXISTS sandbox_jobs (
        id UUID NOT NULL DEFAULT generate_uuidv7() PRIMARY KEY,
        owner_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        status TEXT NOT NULL CHECK (status IN (
            'pending', 'running', 'succeeded', 'failed', 'cancelled', 'timed_out'
        )),
        argv JSONB NOT NULL,
        cwd TEXT NOT NULL DEFAULT '.',
        timeout_ms INTEGER NOT NULL CHECK (timeout_ms > 0),
        workspace_bytes_limit BIGINT NOT NULL CHECK (workspace_bytes_limit > 0),
        output_bytes_limit BIGINT NOT NULL CHECK (output_bytes_limit > 0),
        error_code TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        started_at TIMESTAMPTZ,
        finished_at TIMESTAMPTZ
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sandbox_jobs_owner_status ON sandbox_jobs (owner_id, status, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS sandbox_instances (
        id UUID NOT NULL DEFAULT generate_uuidv7() PRIMARY KEY,
        owner_id UUID NOT NULL UNIQUE REFERENCES profiles(id) ON DELETE CASCADE,
        runtime_name TEXT NOT NULL UNIQUE,
        distribution TEXT NOT NULL CHECK (distribution IN ('debian', 'ubuntu')),
        distribution_version TEXT NOT NULL,
        distribution_codename TEXT NOT NULL DEFAULT '',
        distribution_pretty_name TEXT NOT NULL DEFAULT '',
        generation INTEGER NOT NULL DEFAULT 1,
        state TEXT NOT NULL CHECK (state IN (
            'none', 'provisioning', 'ready', 'busy', 'resetting', 'rebuilding', 'deleting', 'failed'
        )),
        storage_limit_bytes BIGINT NOT NULL DEFAULT 10737418240,
        last_error TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_started_at TIMESTAMPTZ
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sandbox_instances_owner ON sandbox_instances(owner_id, state)",
    "ALTER TABLE sandbox_instances ADD COLUMN IF NOT EXISTS distribution_codename TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE sandbox_instances ADD COLUMN IF NOT EXISTS distribution_pretty_name TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE sandbox_instances ALTER COLUMN id SET DEFAULT generate_uuidv7()",
    "ALTER TABLE sandbox_jobs ALTER COLUMN id SET DEFAULT generate_uuidv7()",
    """
    DO $$ BEGIN
      ALTER TABLE file_objects ADD COLUMN IF NOT EXISTS job_id UUID NULL;
    EXCEPTION WHEN undefined_table THEN NULL;
    END $$;
    """,
    # ── graph memory: episodes, inferred nodes, relationships, evidence ──
    """
    CREATE TABLE IF NOT EXISTS episodes (
        id UUID NOT NULL DEFAULT generate_uuidv7() PRIMARY KEY,
        user_id UUID NOT NULL,
        session_id UUID NOT NULL,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        embedding vector(1536),
        importance REAL NOT NULL DEFAULT 0.5,
        source_start_message_id UUID,
        source_end_message_id UUID,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        archived_at TIMESTAMP NULL,
        CONSTRAINT episodes_source_start_message_fk
            FOREIGN KEY (source_start_message_id) REFERENCES messages(id) ON DELETE SET NULL,
        CONSTRAINT episodes_source_end_message_fk
            FOREIGN KEY (source_end_message_id) REFERENCES messages(id) ON DELETE SET NULL,
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE,
        FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_nodes (
        id UUID NOT NULL DEFAULT generate_uuidv7() PRIMARY KEY,
        user_id UUID NOT NULL,
        node_type TEXT NOT NULL,
        content TEXT NOT NULL,
        embedding vector(1536),
        confidence REAL NOT NULL DEFAULT 0.0 CHECK (confidence >= 0 AND confidence <= 1),
        importance REAL NOT NULL DEFAULT 0.5 CHECK (importance >= 0 AND importance <= 1),
        status TEXT NOT NULL DEFAULT 'active',
        valid_from TIMESTAMP NOT NULL DEFAULT NOW(),
        valid_until TIMESTAMP NULL,
        supersedes_node_id UUID NULL REFERENCES memory_nodes(id) ON DELETE SET NULL,
        embedding_model TEXT NULL,
        embedding_dimensions INTEGER NULL,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
        last_accessed_at TIMESTAMP NULL,
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_edges (
        id UUID NOT NULL DEFAULT generate_uuidv7() PRIMARY KEY,
        user_id UUID NOT NULL,
        from_node_id UUID NOT NULL REFERENCES memory_nodes(id) ON DELETE CASCADE,
        to_node_id UUID NOT NULL REFERENCES memory_nodes(id) ON DELETE CASCADE,
        edge_type TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 0.0 CHECK (confidence >= 0 AND confidence <= 1),
        valid_from TIMESTAMP NOT NULL DEFAULT NOW(),
        valid_until TIMESTAMP NULL,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE (user_id, from_node_id, to_node_id, edge_type),
        CHECK (from_node_id <> to_node_id),
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_evidence (
        id UUID NOT NULL DEFAULT generate_uuidv7() PRIMARY KEY,
        user_id UUID NOT NULL,
        node_id UUID NULL REFERENCES memory_nodes(id) ON DELETE CASCADE,
        edge_id UUID NULL REFERENCES memory_edges(id) ON DELETE CASCADE,
        episode_id UUID NULL REFERENCES episodes(id) ON DELETE CASCADE,
        message_id UUID NULL REFERENCES messages(id) ON DELETE CASCADE,
        evidence_kind TEXT NOT NULL,
        excerpt_hash TEXT NULL,
        observed_at TIMESTAMP NOT NULL DEFAULT NOW(),
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        CHECK (node_id IS NOT NULL OR edge_id IS NOT NULL),
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_episodes_user_session ON episodes(user_id, session_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_episodes_user_active ON episodes(user_id, archived_at, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_memory_nodes_active ON memory_nodes(user_id, status, node_type)",
    "CREATE INDEX IF NOT EXISTS idx_memory_nodes_valid_until ON memory_nodes(user_id, valid_until)",
    "CREATE INDEX IF NOT EXISTS idx_memory_nodes_created ON memory_nodes(user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS memory_nodes_content_idx ON memory_nodes USING gin (content gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_memory_nodes_embedding_dimensions ON memory_nodes(user_id, embedding_dimensions) WHERE embedding IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_memory_edges_from ON memory_edges(user_id, from_node_id, edge_type)",
    "CREATE INDEX IF NOT EXISTS idx_memory_edges_to ON memory_edges(user_id, to_node_id, edge_type)",
    "CREATE INDEX IF NOT EXISTS idx_memory_evidence_node ON memory_evidence(user_id, node_id)",
    "CREATE INDEX IF NOT EXISTS idx_memory_evidence_message ON memory_evidence(user_id, message_id)",
    "CREATE INDEX IF NOT EXISTS idx_memory_evidence_episode ON memory_evidence(user_id, episode_id)",
    """
    CREATE OR REPLACE VIEW relationships AS
    SELECT * FROM memory_edges
    WHERE edge_type IN ('knows', 'works_with', 'related_to', 'belongs_to')
    """,
    # ── user_identities (OAuth provider linkage — Google sub / GitHub id) ──
    """
    CREATE TABLE IF NOT EXISTS user_identities (
        id UUID NOT NULL DEFAULT generate_uuidv7() PRIMARY KEY,
        user_id UUID NOT NULL,
        provider VARCHAR(32) NOT NULL,
        provider_sub TEXT NOT NULL,
        email TEXT,
        created_at TIMESTAMP DEFAULT NOW(),
        UNIQUE (provider, provider_sub),
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
    )
    """,
    # ── user_sessions (opaque server-side session tokens — revocable, not JWT) ──
    """
    CREATE TABLE IF NOT EXISTS user_sessions (
        token TEXT PRIMARY KEY,
        user_id UUID NOT NULL,
        created_at TIMESTAMP DEFAULT NOW(),
        expires_at TIMESTAMP NOT NULL,
        revoked_at TIMESTAMP DEFAULT NULL,
        FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
    )
    """,
    # ── Indexes ──
    "CREATE INDEX IF NOT EXISTS idx_chat_sessions_active ON chat_sessions(is_active)",
    "CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated ON chat_sessions(updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_chat_sessions_deleted ON chat_sessions(deleted_at)",
    "CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id ON chat_sessions(user_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_sessions_active_user ON chat_sessions(user_id) WHERE is_active = TRUE AND deleted_at IS NULL",
    "CREATE INDEX IF NOT EXISTS idx_global_knowledge_entries_user ON global_knowledge_entries(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_global_knowledge_entries_order ON global_knowledge_entries(user_id, sort_order, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_global_knowledge_entries_enabled ON global_knowledge_entries(user_id, enabled)",
    "CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_messages_session_user ON messages(session_id, user_id)",
    "CREATE INDEX IF NOT EXISTS idx_user_identities_user_id ON user_identities(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_user_sessions_expires ON user_sessions(expires_at)",
    """
    DO $$ BEGIN
      ALTER TABLE profiles ADD COLUMN IF NOT EXISTS avatar_url TEXT DEFAULT NULL;
    EXCEPTION WHEN undefined_column THEN NULL;
    END $$;
    """,
    """
    DO $$ BEGIN
      ALTER TABLE profiles DROP COLUMN IF EXISTS memory_state;
      ALTER TABLE chat_sessions DROP COLUMN IF EXISTS memory_state;
      ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS memory_pipeline_state JSONB NOT NULL DEFAULT '{}';
    EXCEPTION WHEN undefined_table THEN NULL;
    END $$;
    """,
    """
    DO $$ BEGIN
      IF to_regclass('public.episodes') IS NOT NULL THEN
        ALTER TABLE episodes
          ALTER COLUMN source_start_message_id TYPE UUID
          USING CASE
            WHEN source_start_message_id IS NULL OR btrim(source_start_message_id::text) = '' THEN NULL
            WHEN source_start_message_id::text ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
              THEN source_start_message_id::text::uuid
            ELSE NULL
          END,
          ALTER COLUMN source_end_message_id TYPE UUID
          USING CASE
            WHEN source_end_message_id IS NULL OR btrim(source_end_message_id::text) = '' THEN NULL
            WHEN source_end_message_id::text ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
              THEN source_end_message_id::text::uuid
            ELSE NULL
          END;
      END IF;
    EXCEPTION WHEN undefined_table OR undefined_column THEN NULL;
    END $$;
    """,
    """
    DO $$ BEGIN
      IF to_regclass('public.episodes') IS NOT NULL
         AND to_regclass('public.messages') IS NOT NULL
         AND (
           SELECT COUNT(*) FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = 'episodes'
             AND column_name IN ('source_start_message_id', 'source_end_message_id')
             AND udt_name = 'uuid'
         ) = 2 THEN
        UPDATE episodes
        SET source_start_message_id = NULL
        WHERE source_start_message_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM messages
            WHERE messages.id = episodes.source_start_message_id
          );
        UPDATE episodes
        SET source_end_message_id = NULL
        WHERE source_end_message_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM messages
            WHERE messages.id = episodes.source_end_message_id
          );
      END IF;
    END $$;
    """,
    """
    DO $$ BEGIN
      IF to_regclass('public.episodes') IS NOT NULL
         AND to_regclass('public.messages') IS NOT NULL
         AND (
           SELECT COUNT(*) FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = 'episodes'
             AND column_name IN ('source_start_message_id', 'source_end_message_id')
             AND udt_name = 'uuid'
         ) = 2
         AND NOT EXISTS (
           SELECT 1 FROM pg_constraint
           WHERE conname = 'episodes_source_start_message_fk'
             AND conrelid = 'public.episodes'::regclass
         ) THEN
        ALTER TABLE episodes
          ADD CONSTRAINT episodes_source_start_message_fk
          FOREIGN KEY (source_start_message_id) REFERENCES messages(id) ON DELETE SET NULL;
      END IF;
      IF to_regclass('public.episodes') IS NOT NULL
         AND to_regclass('public.messages') IS NOT NULL
         AND (
           SELECT COUNT(*) FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = 'episodes'
             AND column_name IN ('source_start_message_id', 'source_end_message_id')
             AND udt_name = 'uuid'
         ) = 2
         AND NOT EXISTS (
           SELECT 1 FROM pg_constraint
           WHERE conname = 'episodes_source_end_message_fk'
             AND conrelid = 'public.episodes'::regclass
         ) THEN
        ALTER TABLE episodes
          ADD CONSTRAINT episodes_source_end_message_fk
          FOREIGN KEY (source_end_message_id) REFERENCES messages(id) ON DELETE SET NULL;
      END IF;
    END $$;
    """,
    """
    DO $$ BEGIN
      DROP INDEX IF EXISTS idx_semantic_facts_user_id;
      DROP INDEX IF EXISTS semantic_facts_content_idx;
      DROP INDEX IF EXISTS semantic_facts_tsv_idx;
      DROP INDEX IF EXISTS semantic_facts_pending_review_idx;
      DROP TABLE IF EXISTS semantic_facts;
    EXCEPTION WHEN undefined_table THEN NULL;
    END $$;
    """,
    # Phase 1.3: add user_id to tenant-scoped tables (already done via migration SQL)
    # Phase 1.7: drop NOT NULL on legacy mapping columns so new UUID rows can omit them
    # Wrapped in DO blocks because legacy_* columns don't exist on fresh installs
    """
    DO $$ BEGIN
      ALTER TABLE chat_sessions ALTER COLUMN legacy_int_id DROP NOT NULL;
    EXCEPTION WHEN undefined_column THEN NULL;
    END $$;
    """,
    """
    DO $$ BEGIN
      ALTER TABLE messages ALTER COLUMN legacy_session_id DROP NOT NULL;
    EXCEPTION WHEN undefined_column THEN NULL;
    END $$;
    """,
    """
    DO $$ BEGIN
      ALTER TABLE messages RENAME COLUMN image_paths TO attachments;
    EXCEPTION WHEN undefined_column THEN NULL;
    END $$;
    """,
    """
    DO $$ BEGIN
      ALTER TABLE profiles ALTER COLUMN legacy_int_id DROP NOT NULL;
    EXCEPTION WHEN undefined_column THEN NULL;
    END $$;
    """,
    """
    DO $$ BEGIN
      ALTER TABLE messages ADD COLUMN IF NOT EXISTS turn_id VARCHAR DEFAULT NULL;
    EXCEPTION WHEN duplicate_column THEN NULL;
    END $$;
    """,
    """
    DO $$
    DECLARE
      dup RECORD;
      canonical_id UUID;
    BEGIN
      FOR dup IN
        SELECT user_id, content, ARRAY_AGG(id ORDER BY id) AS ids
        FROM memory_nodes
        WHERE status = 'active' AND valid_until IS NULL
        GROUP BY user_id, content
        HAVING COUNT(*) > 1
      LOOP
        canonical_id := dup.ids[1];
        -- Process memory_edges before archiving duplicates
        -- Remap source endpoints to canonical node
        UPDATE memory_edges
        SET from_node_id = canonical_id
        WHERE from_node_id = ANY(dup.ids[2:]) AND user_id = dup.user_id;
        -- Remap target endpoints to canonical node
        UPDATE memory_edges
        SET to_node_id = canonical_id
        WHERE to_node_id = ANY(dup.ids[2:]) AND user_id = dup.user_id;
        -- Delete self-loops created by remapping
        DELETE FROM memory_edges
        WHERE from_node_id = to_node_id AND user_id = dup.user_id
          AND (from_node_id = canonical_id OR to_node_id = canonical_id);
        -- Resolve unique-edge conflicts: keep highest confidence, transfer evidence
        WITH conflicts AS (
          SELECT user_id, from_node_id, to_node_id, edge_type,
                 ARRAY_AGG(id ORDER BY confidence DESC, created_at ASC) AS edge_ids
          FROM memory_edges
          WHERE user_id = dup.user_id
            AND (from_node_id = canonical_id OR to_node_id = canonical_id)
          GROUP BY user_id, from_node_id, to_node_id, edge_type
          HAVING COUNT(*) > 1
        )
        UPDATE memory_evidence
        SET edge_id = conflicts.edge_ids[1]
        FROM conflicts
        WHERE memory_evidence.edge_id = ANY(conflicts.edge_ids[2:])
          AND memory_evidence.user_id = dup.user_id;
        -- Delete duplicate edges after transferring evidence
        WITH conflicts AS (
          SELECT user_id, from_node_id, to_node_id, edge_type,
                 ARRAY_AGG(id ORDER BY confidence DESC, created_at ASC) AS edge_ids
          FROM memory_edges
          WHERE user_id = dup.user_id
            AND (from_node_id = canonical_id OR to_node_id = canonical_id)
          GROUP BY user_id, from_node_id, to_node_id, edge_type
          HAVING COUNT(*) > 1
        )
        DELETE FROM memory_edges
        WHERE id IN (
          SELECT UNNEST(edge_ids[2:])
          FROM conflicts
        );
        -- Archive duplicate nodes
        UPDATE memory_nodes
        SET status = 'archived', valid_until = NOW()
        WHERE id = ANY(dup.ids[2:]) AND user_id = dup.user_id;
        -- Transfer node evidence to canonical node
        UPDATE memory_evidence
        SET node_id = canonical_id
        WHERE node_id = ANY(dup.ids[2:]) AND user_id = dup.user_id;
      END LOOP;
    END $$;
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_nodes_active_content ON memory_nodes (user_id, content) WHERE status = 'active' AND valid_until IS NULL",
)

SQL_PROFILE_UNCLAIMED_LOOKUP = """
SELECT p.id
FROM profiles p
LEFT JOIN user_identities ui ON p.id = ui.user_id
WHERE ui.id IS NULL
ORDER BY p.created_at ASC
LIMIT 1
"""

SQL_PROFILE_SELECT_BY_ID = "SELECT * FROM profiles WHERE id = %s"

SQL_PROFILE_LOCK = "SELECT id FROM profiles WHERE id = %s FOR UPDATE"
SQL_FILE_USAGE = """
SELECT COALESCE(SUM(size_bytes), 0)
FROM file_objects
WHERE owner_id = %s
  AND status IN ('pending', 'ready')
  AND deleted_at IS NULL
"""
SQL_FILE_INSERT_PENDING = """
INSERT INTO file_objects
    (id, owner_id, storage_key, original_name, mime_type, size_bytes, kind, source, job_id, status)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
RETURNING *
"""
SQL_FILE_MARK_READY = """
UPDATE file_objects SET status = 'ready', updated_at = NOW()
WHERE id = %s AND owner_id = %s AND status = 'pending' AND deleted_at IS NULL
RETURNING *
"""
SQL_FILE_DELETE_PENDING = """
DELETE FROM file_objects WHERE id = %s AND owner_id = %s AND status = 'pending'
"""
SQL_FILE_SELECT_OWNER = """
SELECT * FROM file_objects
WHERE id = %s AND owner_id = %s AND status = 'ready' AND deleted_at IS NULL
"""
SQL_FILE_MARK_DELETED = """
UPDATE file_objects SET deleted_at = NOW(), updated_at = NOW()
WHERE id = %s AND owner_id = %s AND status = 'ready' AND deleted_at IS NULL
RETURNING *
"""
SQL_SANDBOX_JOB_INSERT = """
INSERT INTO sandbox_jobs
    (owner_id, status, argv, cwd, timeout_ms, workspace_bytes_limit, output_bytes_limit)
VALUES (%s, 'pending', %s, %s, %s, %s, %s)
RETURNING *
"""
SQL_SANDBOX_JOB_SELECT = "SELECT * FROM sandbox_jobs WHERE id = %s"
SQL_SANDBOX_JOB_TRANSITION = """
UPDATE sandbox_jobs
SET status = %s,
    error_code = %s,
    started_at = CASE WHEN %s = 'running' THEN COALESCE(started_at, NOW()) ELSE started_at END,
    finished_at = CASE WHEN %s IN ('succeeded', 'failed', 'cancelled', 'timed_out') THEN NOW() ELSE finished_at END
WHERE id = %s AND status = ANY(%s)
RETURNING *
"""
SQL_SANDBOX_JOBS_TERMINAL_BEFORE = """
SELECT * FROM sandbox_jobs
WHERE status IN ('succeeded', 'failed', 'cancelled', 'timed_out')
  AND finished_at < %s
ORDER BY finished_at
"""

SQL_GLOBAL_KNOWLEDGE_LIST = """
SELECT id, user_id, category, content, sort_order, enabled, created_at, updated_at
FROM global_knowledge_entries
WHERE user_id = %s
ORDER BY sort_order ASC, created_at ASC, id ASC
"""

SQL_GLOBAL_KNOWLEDGE_GET = """
SELECT id, user_id, category, content, sort_order, enabled, created_at, updated_at
FROM global_knowledge_entries
WHERE id = %s AND user_id = %s
"""

SQL_GLOBAL_KNOWLEDGE_INSERT = """
INSERT INTO global_knowledge_entries (user_id, category, content, sort_order, enabled)
VALUES (%s, %s, %s, %s, %s)
RETURNING id, user_id, category, content, sort_order, enabled, created_at, updated_at
"""

SQL_GLOBAL_KNOWLEDGE_UPDATE = """
UPDATE global_knowledge_entries
SET category = %s, content = %s, sort_order = %s, enabled = %s, updated_at = NOW()
WHERE id = %s AND user_id = %s
RETURNING id, user_id, category, content, sort_order, enabled, created_at, updated_at
"""

SQL_GLOBAL_KNOWLEDGE_DELETE = """
DELETE FROM global_knowledge_entries
WHERE id = %s AND user_id = %s
RETURNING id
"""

SQL_GRAPH_EPISODE_INSERT = """
INSERT INTO episodes
    (user_id, session_id, title, summary, embedding, importance,
     source_start_message_id, source_end_message_id)
VALUES (%s, %s, %s, %s, %s::vector, %s, %s, %s)
RETURNING id, user_id, session_id, title, summary, embedding, importance,
          source_start_message_id, source_end_message_id, created_at, archived_at
"""

SQL_GRAPH_NODE_INSERT = """
INSERT INTO memory_nodes
    (user_id, node_type, content, embedding, confidence, importance, status,
     valid_from, valid_until, supersedes_node_id, embedding_model, embedding_dimensions)
VALUES (%s, %s, %s, %s::vector, %s, %s, 'active', %s, NULL, %s, %s, %s)
ON CONFLICT (user_id, content) WHERE status = 'active' AND valid_until IS NULL
DO UPDATE SET
    embedding = COALESCE(memory_nodes.embedding, EXCLUDED.embedding),
    embedding_model = COALESCE(memory_nodes.embedding_model, EXCLUDED.embedding_model),
    embedding_dimensions = COALESCE(memory_nodes.embedding_dimensions, EXCLUDED.embedding_dimensions),
    updated_at = NOW()
RETURNING id, user_id, node_type, content, embedding, confidence, importance, status,
          valid_from, valid_until, supersedes_node_id, embedding_model,
          embedding_dimensions, created_at, updated_at, last_accessed_at
"""

SQL_GRAPH_NODE_BY_CONTENT = """
SELECT id, user_id, node_type, content, embedding, confidence, importance, status,
       valid_from, valid_until, supersedes_node_id, embedding_model,
       embedding_dimensions, created_at, updated_at, last_accessed_at
FROM memory_nodes
WHERE user_id = %s AND content = %s AND status = 'active' AND valid_until IS NULL
LIMIT 1
"""

SQL_GRAPH_NODE_SIMILAR_ACTIVE = """
SELECT id, user_id, node_type, content, confidence, importance, status,
       valid_from, valid_until, supersedes_node_id, embedding_model,
       embedding_dimensions, created_at, updated_at, last_accessed_at,
       similarity(content, %s) AS score
FROM memory_nodes
WHERE user_id = %s AND id <> %s AND node_type = %s
  AND status = 'active' AND valid_until IS NULL
  AND similarity(content, %s) >= %s
ORDER BY score DESC, created_at ASC
LIMIT %s
"""

SQL_GRAPH_NODE_ARCHIVE = """
WITH locked_nodes AS (
    SELECT id, status
    FROM memory_nodes
    WHERE user_id = %s AND id IN (%s, %s)
    ORDER BY id
    FOR UPDATE
)
UPDATE memory_nodes AS candidate
SET status = 'archived', valid_until = NOW(), supersedes_node_id = %s,
    updated_at = NOW()
WHERE candidate.id = %s
  AND candidate.user_id = %s
  AND candidate.status = 'active'
  AND candidate.valid_until IS NULL
  AND EXISTS (
      SELECT 1 FROM locked_nodes
      WHERE id = %s AND status = 'active'
  )
  AND EXISTS (
      SELECT 1 FROM locked_nodes
      WHERE id = %s AND status = 'active'
  )
RETURNING candidate.id
"""

SQL_GRAPH_EVIDENCE_REASSIGN = """
UPDATE memory_evidence
SET node_id = %s
WHERE user_id = %s AND node_id = %s
"""
SQL_GRAPH_NODE_LIST = """
SELECT id, user_id, node_type, content, confidence, importance, status, valid_from,
       valid_until, supersedes_node_id, embedding_model, embedding_dimensions,
       created_at, updated_at, last_accessed_at, 0.0 AS score
FROM memory_nodes
WHERE user_id = %s AND status = 'active' AND valid_until IS NULL
ORDER BY importance DESC, created_at DESC
LIMIT %s
"""

SQL_GRAPH_NODE_PROVENANCE = """
SELECT e.id AS evidence_id, e.node_id, e.episode_id, e.message_id,
       e.evidence_kind, e.observed_at, e.created_at,
       ep.session_id, ep.title AS episode_title, ep.summary AS episode_summary,
       ep.created_at AS episode_created_at
FROM memory_evidence e
LEFT JOIN episodes ep ON ep.id = e.episode_id AND ep.user_id = e.user_id
WHERE e.user_id = %s AND e.node_id = %s
ORDER BY e.created_at ASC, e.id ASC
"""

SQL_GRAPH_EDGE_UPSERT = """
INSERT INTO memory_edges
    (user_id, from_node_id, to_node_id, edge_type, confidence)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (user_id, from_node_id, to_node_id, edge_type)
DO UPDATE SET confidence = GREATEST(memory_edges.confidence, EXCLUDED.confidence),
              valid_until = NULL
RETURNING id, user_id, from_node_id, to_node_id, edge_type, confidence,
          valid_from, valid_until, created_at
"""

SQL_GRAPH_EVIDENCE_INSERT = """
INSERT INTO memory_evidence
    (user_id, node_id, edge_id, episode_id, message_id, evidence_kind, excerpt_hash)
VALUES (%s, %s, %s, %s, %s, %s, %s)
RETURNING id, user_id, node_id, edge_id, episode_id, message_id, evidence_kind,
          excerpt_hash, observed_at, created_at
"""

SQL_GRAPH_NODE_SEARCH_TEXT = """
SELECT id, user_id, node_type, content, confidence, importance, status, valid_from,
       valid_until, supersedes_node_id, embedding_model, embedding_dimensions,
       created_at, updated_at, last_accessed_at,
       similarity(content, %s) AS score
FROM memory_nodes
WHERE user_id = %s AND status = 'active' AND valid_until IS NULL
  AND content %% %s
ORDER BY score DESC, importance DESC, created_at DESC
LIMIT %s
"""

SQL_GRAPH_NODE_EXPAND = """
SELECT e.id, e.user_id, e.from_node_id, e.to_node_id, e.edge_type, e.confidence,
       e.valid_from, e.valid_until, e.created_at,
       n.id AS node_id, n.node_type, n.content, n.confidence AS node_confidence,
       n.importance, n.status, n.valid_from AS node_valid_from,
       n.valid_until AS node_valid_until
FROM memory_edges e
JOIN memory_nodes n ON n.id = CASE
    WHEN e.from_node_id = %s THEN e.to_node_id ELSE e.from_node_id END
WHERE e.user_id = %s
  AND (%s = e.from_node_id OR %s = e.to_node_id)
  AND e.valid_until IS NULL AND n.user_id = %s
  AND n.status = 'active' AND n.valid_until IS NULL
ORDER BY e.confidence DESC, n.importance DESC, n.created_at DESC
LIMIT %s
"""

SQL_GRAPH_NODE_SEARCH_VECTOR = """
SELECT n.id, n.user_id, n.node_type, n.content, n.confidence, n.importance,
       n.status, n.valid_from, n.valid_until, n.supersedes_node_id,
       n.embedding_model, n.embedding_dimensions, n.created_at, n.updated_at,
       n.last_accessed_at, 1 - (n.embedding <=> %s::vector) AS score
FROM memory_nodes n
WHERE n.user_id = %s AND n.status = 'active' AND n.valid_until IS NULL
  AND n.embedding IS NOT NULL AND n.embedding_dimensions = %s
  AND (1 - (n.embedding <=> %s::vector)) >= %s
ORDER BY score DESC, n.importance DESC, n.created_at DESC
LIMIT %s
"""

SQL_AUTH_ME_LOOKUP = """
SELECT p.user_name, p.avatar_url, ui.email
FROM profiles p
LEFT JOIN LATERAL (
  SELECT email FROM user_identities ui
  WHERE ui.user_id = p.id
  ORDER BY created_at DESC
  LIMIT 1
) ui ON true
WHERE p.id = %s
"""

SQL_PROFILE_UPDATE_AVATAR = (
    "UPDATE profiles SET avatar_url = %s, updated_at = %s WHERE id = %s"
)

SQL_PROFILE_UPDATE_DISPLAY_NAME = (
    "UPDATE profiles SET user_name = %s, updated_at = %s WHERE id = %s"
)

SQL_PROFILE_INSERT_DEFAULT = """
INSERT INTO profiles (user_name, partner_name, affection, theme,
                      session_history, providers_config, model_parameters, timestamp, updated_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

DEFAULT_PROFILE_PARAMS = (
    "",
    "",
    50,
    "default",
    "{}",
    "{}",
    "{}",
)

_PROFILE_TEXT_FIELDS = (
    "user_name",
    "partner_name",
    "theme",
    "image_model",
    "image_provider",
    "image_edit_provider",
    "image_endpoint",
    "image_edit_endpoint",
)
_PROFILE_JSON_FIELDS = (
    "session_history",
    "providers_config",
    "model_parameters",
    "image_extra_body",
    "image_edit_extra_body",
)
_PROFILE_LOCATION_FIELDS = {
    "location_lat": ("REAL", float),
    "location_lon": ("REAL", float),
}


def build_profile_update(updates: dict[str, Any]) -> tuple[str, list[Any]] | None:
    """Build (query, params) for a UPDATE profiles statement.

    Returns None when there are no recognized fields to update. Always
    appends `updated_at` to the SET clause when at least one field changes.

    Note: All JSON fields are JSONB columns (no _json suffix).
    """
    set_parts: list[str] = []
    params: list[Any] = []

    for key, value in updates.items():
        if key in _PROFILE_JSON_FIELDS:
            set_parts.append(f"{key} = %s")
            params.append(json.dumps(value) if isinstance(value, dict) else value)
        elif key in _PROFILE_TEXT_FIELDS:
            set_parts.append(f"{key} = %s")
            params.append(str(value))
        elif key in _PROFILE_LOCATION_FIELDS:
            sql_type, value_type = _PROFILE_LOCATION_FIELDS[key]
            set_parts.append(f"{key} = %s::{sql_type}")
            params.append(None if value is None else value_type(value))
        elif key == "affection":
            set_parts.append("affection = %s")
            params.append(int(value))

    if not set_parts:
        return None

    set_parts.append("updated_at = %s")
    params.append(datetime.now())
    return f"UPDATE profiles SET {', '.join(set_parts)}", params


def parse_global_knowledge_row(row: DBRow | None) -> DBRow:
    if not row:
        return {}
    return {
        "id": str(row["id"]),
        "category": row.get("category", ""),
        "content": row.get("content", ""),
        "sort_order": int(row.get("sort_order", 0)),
        "enabled": bool(row.get("enabled", True)),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def parse_profile_row(row: DBRow | None) -> DBRow:
    """Convert a raw profile row into the public dict shape."""
    if not row:
        return {}
    import json

    def _parse_json(val: Any) -> DBRow:
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                return {}
        return val or {}

    model_parameters = _parse_json(row.get("model_parameters"))
    return {
        "id": str(row.get("id")) if row.get("id") is not None else "",
        "user_name": row.get("user_name", ""),
        "partner_name": row.get("partner_name", ""),
        "affection": row.get("affection", 50),
        "theme": row.get("theme", "default"),
        "session_history": _parse_json(row.get("session_history")),
        "providers_config": _parse_json(row.get("providers_config")),
        "model_parameters": model_parameters,
        "image_model": row.get("image_model"),
        "image_provider": row.get("image_provider"),
        "image_endpoint": row.get("image_endpoint"),
        "image_edit_provider": row.get("image_edit_provider"),
        "image_edit_endpoint": row.get("image_edit_endpoint"),
        "image_extra_body": _parse_json(row.get("image_extra_body")),
        "image_edit_extra_body": _parse_json(row.get("image_edit_extra_body")),
        "location_lat": row.get("location_lat"),
        "location_lon": row.get("location_lon"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "personality_preset": model_parameters.get("personality_preset") or "helpful",
        "personality_custom": model_parameters.get("personality_custom") or "",
        "character_profile": model_parameters.get("character_profile") or "",
        "temperature": model_parameters.get("temperature"),
        "top_p": model_parameters.get("top_p"),
        "max_tokens": model_parameters.get("max_tokens"),
        "top_k": model_parameters.get("top_k"),
        "additional_instructions": model_parameters.get("additional_instructions")
        or "",
        "presets": model_parameters.get("presets") or [],
        "active_preset": model_parameters.get("active_preset"),
        "history_limit": model_parameters.get("history_limit"),
        "enable_reasoning": model_parameters.get("enable_reasoning"),
        "enable_vision": model_parameters.get("enable_vision"),
    }


SQL_SESSION_SELECT_ACTIVE_FOR_USER = "SELECT * FROM chat_sessions WHERE user_id = %s AND is_active = TRUE AND deleted_at IS NULL LIMIT 1"

SQL_SESSION_INSERT = """
INSERT INTO chat_sessions (user_id, name, is_active, message_count, created_at, updated_at)
VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
"""

SQL_SESSION_SELECT_ALL_FOR_USER = "SELECT * FROM chat_sessions WHERE user_id = %s AND deleted_at IS NULL ORDER BY updated_at DESC"

SQL_SESSION_DEACTIVATE_FOR_USER = "UPDATE chat_sessions SET is_active = FALSE WHERE user_id = %s AND deleted_at IS NULL"

SQL_SESSION_ACTIVATE_ONE_SCOPED = "UPDATE chat_sessions SET is_active = TRUE, updated_at = %s WHERE id = %s AND user_id = %s AND deleted_at IS NULL RETURNING id"

SQL_SESSION_RENAME_SCOPED = """
UPDATE chat_sessions
SET name = %s, updated_at = %s
WHERE id = %s AND user_id = %s AND deleted_at IS NULL
RETURNING id
"""

SQL_SESSION_RENAME_PLACEHOLDER_SCOPED = """
UPDATE chat_sessions
SET name = %s, updated_at = %s
WHERE id = %s
  AND user_id = %s
  AND deleted_at IS NULL
  AND (name IS NULL OR BTRIM(name) = '' OR name = 'New Chat')
RETURNING id
"""

SQL_SESSION_DELETE_SCOPED = (
    "UPDATE chat_sessions SET deleted_at = NOW() WHERE id = %s AND user_id = %s"
)

SQL_SESSIONS_RECENT_ACTIVE = """
SELECT id, name, updated_at, message_count, is_active
FROM chat_sessions
WHERE deleted_at IS NULL AND id != %s AND user_id = %s
ORDER BY updated_at DESC
LIMIT %s
"""

SQL_SESSION_INCREMENT_COUNT = (
    "UPDATE chat_sessions SET message_count = message_count + 1, "
    "updated_at = %s WHERE id = %s"
)

SQL_SESSION_RESET_COUNT = (
    "UPDATE chat_sessions SET message_count = 0, memory_pipeline_state = '{}', "
    "updated_at = %s WHERE id = %s"
)

SQL_PIPELINE_STATE_SELECT = (
    "SELECT memory_pipeline_state FROM chat_sessions WHERE id = %s AND user_id = %s"
)

SQL_PIPELINE_STATE_UPDATE = (
    "UPDATE chat_sessions SET memory_pipeline_state = %s, updated_at = %s "
    "WHERE id = %s AND user_id = %s"
)

SQL_PIPELINE_STATE_CLAIM = """
UPDATE chat_sessions
SET memory_pipeline_state = jsonb_set(
    jsonb_set(
        COALESCE(memory_pipeline_state, '{}'::jsonb),
        '{in_progress_fence_count}',
        to_jsonb(%s::integer),
        true
    ),
    '{in_progress_fence_since}',
    to_jsonb(%s::text),
    true
),
updated_at = %s
WHERE id = %s
  AND user_id = %s
  AND (
      NULLIF(memory_pipeline_state->>'in_progress_fence_since', '') IS NULL
      OR NULLIF(memory_pipeline_state->>'in_progress_fence_since', '')::timestamp < %s::timestamp
  )
RETURNING memory_pipeline_state
"""

SQL_PIPELINE_STATE_CLEAR = """
UPDATE chat_sessions
SET memory_pipeline_state = memory_pipeline_state - 'in_progress_fence_count' - 'in_progress_fence_since',
    updated_at = %s
WHERE id = %s
  AND user_id = %s
RETURNING memory_pipeline_state
"""


def parse_session_row(row: DBRow | None) -> DBRow:
    """Parse session row into canonical DB dictionary representation."""
    if not row:
        return {}
    raw_id = str(row.get("id")) if row.get("id") is not None else ""
    return {
        "id": raw_id,
        "name": str(row.get("name", "Unnamed Session")),
        "is_active": bool(row.get("is_active", False)),
        "message_count": int(row.get("message_count", 0)),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "timestamp": row.get("timestamp"),
    }


# ---------------------------------------------------------------------------
# Message SQL
# ---------------------------------------------------------------------------

SQL_MESSAGE_INSERT = """
INSERT INTO messages (session_id, user_id, role, content, attachments, tool_calls, tool_call_id, turn_id, timestamp, content_encrypted)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), FALSE) RETURNING id, timestamp
"""

SQL_MESSAGE_SELECT_ASC_LIMIT = """
SELECT id, session_id, role, content, attachments, tool_calls, tool_call_id, turn_id, timestamp
FROM messages
WHERE session_id = %s AND user_id = %s
ORDER BY timestamp ASC, id ASC
LIMIT %s
"""

SQL_MESSAGE_SELECT_DESC_LIMIT = """
SELECT id, session_id, role, content, attachments, tool_calls, tool_call_id, turn_id, timestamp
FROM messages
WHERE session_id = %s AND user_id = %s
ORDER BY timestamp DESC, id DESC
LIMIT %s
"""

SQL_MESSAGE_SELECT_ASC_ALL = """
SELECT id, session_id, role, content, attachments, tool_calls, tool_call_id, turn_id, timestamp
FROM messages
WHERE session_id = %s AND user_id = %s
ORDER BY timestamp ASC, id ASC
"""

SQL_MESSAGE_SELECT_CONVERSATIONAL_ASC_ALL = """
SELECT id, session_id, role, content, attachments, tool_calls, tool_call_id, turn_id, timestamp
FROM messages
WHERE session_id = %s AND user_id = %s
  AND role IN ('user', 'assistant')
ORDER BY timestamp ASC, id ASC
"""

SQL_MESSAGE_SELECT_ASC_OFFSET_LIMIT = """
SELECT id, session_id, role, content, attachments, tool_calls, tool_call_id, turn_id, timestamp
FROM messages
WHERE session_id = %s AND user_id = %s
  AND role IN ('user', 'assistant')
ORDER BY timestamp ASC, id ASC
LIMIT %s OFFSET %s
"""

# Query messages after a specific ID (for memory pipeline ID-based tracking)
SQL_MESSAGE_SELECT_AFTER_ID = """
SELECT id, session_id, role, content, attachments, tool_calls, tool_call_id, turn_id, timestamp
FROM messages
WHERE session_id = %s AND user_id = %s AND id > %s
  AND role IN ('user', 'assistant')
ORDER BY id ASC
LIMIT %s
"""

# Query messages before a specific timestamp (for upward infinite scroll pagination)
SQL_MESSAGE_SELECT_BEFORE_TS = """
SELECT id, session_id, role, content, attachments, tool_calls, tool_call_id, turn_id, timestamp
FROM messages
WHERE session_id = %s AND user_id = %s AND timestamp < %s
ORDER BY timestamp DESC, id DESC
LIMIT %s
"""

SQL_MESSAGE_UPDATE = "UPDATE messages SET content = %s, attachments = %s WHERE id = %s"

SQL_MESSAGE_DELETE_FOR_SESSION = (
    "DELETE FROM messages WHERE session_id = %s AND user_id = %s"
)

SQL_MESSAGE_COUNT_CONVERSATIONAL = (
    "SELECT COUNT(*) as cnt FROM messages "
    "WHERE session_id = %s AND role IN ('user', 'assistant')"
)

SQL_MESSAGE_RECENT_SYSTEM_GLOBAL = """
SELECT content, timestamp
FROM messages
WHERE role = 'system'
ORDER BY timestamp DESC, id DESC
LIMIT %s
"""

SQL_MESSAGE_RECENT_SYSTEM_FOR_SESSION = """
SELECT content, timestamp
FROM messages
WHERE role = 'system' AND session_id = %s
ORDER BY timestamp DESC, id DESC
LIMIT %s
"""

SQL_MESSAGE_CONVERSATION_SUMMARY = """
SELECT role, content
FROM messages
WHERE session_id = %s AND user_id = %s AND role IN ('user', 'assistant')
ORDER BY timestamp ASC, id ASC
LIMIT %s
"""

SQL_MESSAGE_HISTORY_FOR_AI_ASC_LIMIT = """
SELECT id, role, content, attachments, tool_calls, tool_call_id, turn_id, timestamp
FROM messages
WHERE session_id = %s AND user_id = %s AND role IN ('user', 'assistant', 'tool')
ORDER BY timestamp ASC, id ASC
LIMIT %s
"""

SQL_MESSAGE_HISTORY_FOR_AI_DESC_LIMIT = """
SELECT id, role, content, attachments, tool_calls, tool_call_id, turn_id, timestamp
FROM messages
WHERE session_id = %s AND user_id = %s AND role IN ('user', 'assistant', 'tool')
ORDER BY timestamp DESC, id DESC
LIMIT %s
"""

SQL_MESSAGE_HISTORY_FOR_AI_ASC_ALL = """
SELECT id, role, content, attachments, tool_calls, tool_call_id, turn_id, timestamp
FROM messages
WHERE session_id = %s AND user_id = %s AND role IN ('user', 'assistant', 'tool')
ORDER BY timestamp ASC, id ASC
"""

SQL_MESSAGE_SELECT_ENCRYPTED = """
SELECT id, session_id, role, content, timestamp
FROM messages
WHERE content_encrypted = TRUE
"""

SQL_MESSAGE_SELECT_CONTENT_BY_ID = "SELECT content FROM messages WHERE id = %s"

SQL_MESSAGE_UPDATE_DECRYPTED = (
    "UPDATE messages SET content = %s, content_encrypted = FALSE WHERE id = %s"
)


def _iso_timestamp(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="milliseconds") + (
            "Z" if value.tzinfo is None else ""
        )
    return str(value)


def parse_message_row(row: DBRow) -> DBRow:
    """Convert a raw messages row into the public dict shape."""
    return {
        "id": str(row.get("id")) if row.get("id") is not None else "",
        "session_id": str(row.get("session_id"))
        if row.get("session_id") is not None
        else "",
        "role": row.get("role"),
        "content": row.get("content"),
        "attachments": parse_json(row.get("attachments", "[]")),
        "tool_calls": parse_json(row.get("tool_calls", "null")),
        "tool_call_id": row.get("tool_call_id"),
        "turn_id": row.get("turn_id"),
        "timestamp": _iso_timestamp(row.get("timestamp")),
    }


def parse_event_row(row: DBRow) -> DBRow:
    """Convert a raw event row (system messages list)."""
    return {
        "content": row.get("content", ""),
        "timestamp": _iso_timestamp(row.get("timestamp")),
    }


def format_conversation_summary(rows: list[DBRow]) -> str:
    """Render a brief 'User: ... / AI: ...' summary from message rows."""
    lines: list[str] = []
    for r in rows:
        speaker = "User" if r.get("role") == "user" else "AI"
        content = r.get("content", "")
        if len(content) > 100:
            content = content[:100] + "..."
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines)


TOOL_ROLES: dict[str, str] = {
    "image_generate": "image_tools",
    "imagine": "image_tools",
    "http_request": "request_tools",
    "request": "request_tools",
    "memory_store": "memory_tools",
    "memory_search": "memory_tools",
    "read": "fs_tools",
    "write": "fs_tools",
    "ls": "fs_tools",
    "mkdir": "fs_tools",
    "rm": "fs_tools",
    "bash": "shell_tools",
    "python": "python_tools",
    "sql": "sql_tools",
    "ask_rei": "ask_rei_tools",
    "fs_tools": "fs_tools",
    "image_tools": "image_tools",
    "request_tools": "request_tools",
    "memory_tools": "memory_tools",
    "memory_search_tools": "memory_search_tools",
    "memory_store_tools": "memory_store_tools",
    "python_tools": "python_tools",
    "shell_tools": "shell_tools",
    "sql_tools": "sql_tools",
}
ALL_TOOL_ROLES: list[str] = sorted(set(TOOL_ROLES.values()))


def tool_role_for(tool_name: str) -> str:
    return TOOL_ROLES.get(tool_name, f"{tool_name}_tools")


# ---------------------------------------------------------------------------
# AI history formatting (tool-contract parsing for chat_history_for_ai)
# ---------------------------------------------------------------------------

_RX_BASH_COMMAND = re.compile(r"```bash\n\S+\$\s*(/[^\n]{1,500})\n```")
_RX_DETAILS_OPEN = re.compile(r"<details>\s*<summary>[^<]{0,500}</summary>", re.DOTALL)
_RX_DETAILS_CLOSE = re.compile(r"</details>", re.DOTALL)
_RX_BASH_BLOCK = re.compile(r"```bash\n[^`]{0,5000}\n```", re.DOTALL)
_RX_FENCE_OPEN = re.compile(r"```[\w]{0,20}\n?")
_RX_FENCE_CLOSE = re.compile(r"```")
_RX_BLOCKQUOTE = re.compile(r"^>\s*", re.MULTILINE)
_RX_HTML_TAGS = re.compile(r"<[^>]{1,500}>")
_RX_LEADING_NL = re.compile(r"^\n+")
_RX_TRAILING_NL = re.compile(r"\n+$")


def extract_command_from_markdown_contract(content: str) -> str:
    """Pull the /command line out of a tool-contract markdown blob."""
    if not content:
        return content
    m = _RX_BASH_COMMAND.search(content)
    return m.group(1).strip() if m else content


def extract_raw_result_from_markdown_contract(content: str) -> str:
    """Strip tool-contract formatting and return only the raw result text."""
    if not content:
        return content
    result = content
    result = _RX_DETAILS_OPEN.sub("", result)
    result = _RX_DETAILS_CLOSE.sub("", result)
    result = _RX_BASH_BLOCK.sub("", result)
    result = _RX_FENCE_OPEN.sub("", result)
    result = _RX_FENCE_CLOSE.sub("", result)
    result = _RX_BLOCKQUOTE.sub("", result)
    result = _RX_HTML_TAGS.sub("", result)
    result = _RX_LEADING_NL.sub("", result)
    result = _RX_TRAILING_NL.sub("", result)
    return result.strip()


def _format_user_timestamp(ts: Any) -> str:
    try:
        if isinstance(ts, str):
            dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
        else:
            dt = ts
        return dt.strftime("[%Y-%m-%d %H:%M:%S]")
    except Exception:  # noqa: BLE001
        return f"[{ts}]"


def format_ai_history_rows(
    rows: list[DBRow], include_attachments: bool = False
) -> list[DBRow]:
    """Format message rows for AI consumption.

    Filters out system messages to prevent log/context pollution.
    """
    if not rows:
        return []

    # Defensive filter: exclude system messages
    filtered_rows = [r for r in rows if r.get("role") != "system"]

    if not filtered_rows:
        return []

    formatted: list[dict[str, Any]] = []
    for msg in filtered_rows:
        role = msg.get("role", "")
        content = msg.get("content", "")
        attachments = parse_json(msg.get("attachments", "[]"))
        tool_calls_raw = msg.get("tool_calls")
        if isinstance(tool_calls_raw, str):
            tool_calls_raw = parse_json(tool_calls_raw)
        tool_call_id = msg.get("tool_call_id")

        if role == "event_log":
            continue

        # Normalize to OpenAI chat completion format
        if tool_call_id:
            entry: dict[str, Any] = {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": content,
            }
            formatted.append(entry)
            continue

        # tool_calls present → this is an assistant message with tool calls
        if tool_calls_raw and role == "assistant":
            normalized_tool_calls = normalize_tool_calls(tool_calls_raw)
            if not normalized_tool_calls:
                continue
            entry = {
                "role": "assistant",
                "content": content or None,
                "tool_calls": normalized_tool_calls,
            }
            if include_attachments and attachments:
                entry["attachments"] = attachments
            formatted.append(entry)
            continue

        if role == "user":
            ts = _format_user_timestamp(msg.get("timestamp", ""))
            entry = {
                "role": role,
                "content": f"{content} {ts}",
            }
        elif role in ("assistant", "system"):
            entry = {"role": role, "content": content}
        elif role in ALL_TOOL_ROLES:
            entry = {"role": "tool", "content": content}
        else:
            entry = {"role": role, "content": content}

        if include_attachments and attachments:
            entry["attachments"] = attachments

        formatted.append(entry)

    return formatted


def format_public_history_rows(rows: list[DBRow]) -> list[DBRow]:
    """(｡•̀ᴗ-)✧"""
    formatted: list[dict[str, Any]] = []
    for row in rows:
        role = row.get("role")
        if role not in {"user", "assistant", "tool", "system"}:
            continue
        entry: dict[str, Any] = {
            "id": str(row.get("id")) if row.get("id") is not None else "",
            "role": role,
            "content": row.get("content") or "",
            "attachments": parse_json(row.get("attachments", "[]")),
            "timestamp": str(row.get("timestamp", "")),
        }
        tool_calls = row.get("tool_calls")
        if isinstance(tool_calls, str):
            tool_calls = parse_json(tool_calls)
        if role == "assistant" and isinstance(tool_calls, list) and tool_calls:
            normalized = normalize_tool_calls(tool_calls)
            if normalized:
                entry["tool_calls"] = normalized
        if role == "tool" and row.get("tool_call_id"):
            entry["tool_call_id"] = str(row["tool_call_id"])
        formatted.append(entry)
    return formatted


# ---------------------------------------------------------------------------
# Encryption status SQL
# ---------------------------------------------------------------------------

SQL_ENC_TOTAL_MESSAGES = "SELECT COUNT(*) as cnt FROM messages"
SQL_ENC_ENCRYPTED_MESSAGES = (
    "SELECT COUNT(*) as cnt FROM messages WHERE content_encrypted = TRUE"
)


def build_encryption_status(
    total_msg: DBRow | None,
    encrypted_msg: DBRow | None,
) -> DBRow:
    """Assemble the encryption-status response from message count rows."""

    def cnt(row: DBRow | None) -> int:
        return row.get("cnt", 0) if row else 0

    return {
        "messages": {
            "total": cnt(total_msg),
            "encrypted": cnt(encrypted_msg),
            "policy": "NO_ENCRYPTION",
        },
    }


# ---------------------------------------------------------------------------
# Auth — identity mapping + server-side sessions (Phase 2)
# ---------------------------------------------------------------------------

SQL_IDENTITY_LOOKUP = """
SELECT user_id FROM user_identities
WHERE provider = %s AND provider_sub = %s
"""

SQL_IDENTITY_INSERT = """
INSERT INTO user_identities (user_id, provider, provider_sub, email)
VALUES (%s, %s, %s, %s)
"""

SQL_PROFILE_INSERT_DEFAULT_RETURNING = """
INSERT INTO profiles (user_name, partner_name, affection, theme,
                      session_history, providers_config, model_parameters, timestamp, updated_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
RETURNING id
"""

SQL_SESSION_TOKEN_CREATE = """
INSERT INTO user_sessions (token, user_id, created_at, expires_at)
VALUES (%s, %s, %s, %s)
"""

SQL_SESSION_TOKEN_VALIDATE = """
SELECT user_id FROM user_sessions
WHERE token = %s
  AND expires_at > NOW()
  AND revoked_at IS NULL
"""

SQL_SESSION_TOKEN_REVOKE = """
UPDATE user_sessions SET revoked_at = %s WHERE token = %s
"""

# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------


def parse_json(s: str | None) -> Any:
    """Safe JSON parse: returns {} on None / parse failure."""
    if not s:
        return {}
    if not isinstance(s, str):
        return s
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return {}


def format_session_event(content: str, interface: str) -> str:
    """Render the canonical 'connection event' message body."""
    return f"*{content} on {interface}*"


__all__ = [
    # Encryption
    "encrypt_api_key",
    "decrypt_api_key",
    "DECRYPTION_ERROR",
    # Schema
    "SCHEMA_DDL",
    # Profile
    "SQL_PROFILE_SELECT_BY_ID",
    "SQL_SESSION_SELECT_ACTIVE_FOR_USER",
    "SQL_SESSION_SELECT_ALL_FOR_USER",
    "SQL_SESSION_DEACTIVATE_FOR_USER",
    "SQL_SESSION_ACTIVATE_ONE_SCOPED",
    "SQL_SESSION_RENAME_SCOPED",
    "SQL_SESSION_RENAME_PLACEHOLDER_SCOPED",
    "SQL_SESSION_DELETE_SCOPED",
    "SQL_PROFILE_INSERT_DEFAULT",
    "DEFAULT_PROFILE_PARAMS",
    "build_profile_update",
    "parse_profile_row",
    "SQL_GLOBAL_KNOWLEDGE_LIST",
    "SQL_GLOBAL_KNOWLEDGE_GET",
    "SQL_GLOBAL_KNOWLEDGE_INSERT",
    "SQL_GLOBAL_KNOWLEDGE_UPDATE",
    "SQL_GLOBAL_KNOWLEDGE_DELETE",
    "parse_global_knowledge_row",
    # Sessions
    "SQL_SESSION_INSERT",
    "SQL_SESSIONS_RECENT_ACTIVE",
    "SQL_SESSION_INCREMENT_COUNT",
    "SQL_SESSION_RESET_COUNT",
    "SQL_PIPELINE_STATE_SELECT",
    "SQL_PIPELINE_STATE_UPDATE",
    "SQL_PIPELINE_STATE_CLAIM",
    "SQL_PIPELINE_STATE_CLEAR",
    "parse_session_row",
    # Messages
    "SQL_MESSAGE_INSERT",
    "SQL_MESSAGE_SELECT_ASC_LIMIT",
    "SQL_MESSAGE_SELECT_ASC_ALL",
    "SQL_MESSAGE_SELECT_CONVERSATIONAL_ASC_ALL",
    "SQL_MESSAGE_SELECT_AFTER_ID",
    "SQL_MESSAGE_SELECT_BEFORE_TS",
    "SQL_MESSAGE_DELETE_FOR_SESSION",
    "SQL_MESSAGE_COUNT_CONVERSATIONAL",
    "SQL_MESSAGE_RECENT_SYSTEM_GLOBAL",
    "SQL_MESSAGE_RECENT_SYSTEM_FOR_SESSION",
    "SQL_MESSAGE_CONVERSATION_SUMMARY",
    "SQL_MESSAGE_HISTORY_FOR_AI_ASC_LIMIT",
    "SQL_MESSAGE_HISTORY_FOR_AI_DESC_LIMIT",
    "SQL_MESSAGE_HISTORY_FOR_AI_ASC_ALL",
    "SQL_MESSAGE_SELECT_ENCRYPTED",
    "SQL_MESSAGE_SELECT_CONTENT_BY_ID",
    "SQL_MESSAGE_UPDATE_DECRYPTED",
    "parse_message_row",
    "parse_event_row",
    "format_conversation_summary",
    "format_ai_history_rows",
    "format_public_history_rows",
    # Encryption status
    "SQL_ENC_TOTAL_MESSAGES",
    "SQL_ENC_ENCRYPTED_MESSAGES",
    "build_encryption_status",
    # Graph memory
    "SQL_GRAPH_EPISODE_INSERT",
    "SQL_GRAPH_NODE_INSERT",
    "SQL_GRAPH_NODE_BY_CONTENT",
    "SQL_GRAPH_NODE_SIMILAR_ACTIVE",
    "SQL_GRAPH_NODE_ARCHIVE",
    "SQL_GRAPH_EVIDENCE_REASSIGN",
    "SQL_GRAPH_NODE_LIST",
    "SQL_GRAPH_NODE_PROVENANCE",
    "SQL_GRAPH_EDGE_UPSERT",
    "SQL_GRAPH_EVIDENCE_INSERT",
    "SQL_GRAPH_NODE_SEARCH_TEXT",
    "SQL_GRAPH_NODE_SEARCH_VECTOR",
    "SQL_GRAPH_NODE_EXPAND",
    # Auth
    "SQL_IDENTITY_LOOKUP",
    "SQL_IDENTITY_INSERT",
    "SQL_PROFILE_INSERT_DEFAULT_RETURNING",
    "SQL_SESSION_TOKEN_CREATE",
    "SQL_SESSION_TOKEN_VALIDATE",
    "SQL_SESSION_TOKEN_REVOKE",
    "SQL_AUTH_ME_LOOKUP",
    "SQL_PROFILE_UPDATE_AVATAR",
    "SQL_PROFILE_UPDATE_DISPLAY_NAME",
    "SQL_PROFILE_UNCLAIMED_LOOKUP",
    # Misc
    "parse_json",
    "format_session_event",
]
