#!/usr/bin/env python3
"""
Migration script: SQLite yuzu_core.db -> PostgreSQL

CRITICAL: All connection details must be provided via environment variables.
Set these before running:
  - PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD

Run from yuzu-companion/ directory.
"""

import sqlite3
import psycopg2
import json
import os

SQLITE_DB = "app/yuzu_core.db"

# PostgreSQL connection from environment
PG_DBNAME = os.getenv("PGDATABASE", "")
PG_HOST = os.getenv("PGHOST", "")
PG_PORT = os.getenv("PGPORT", "")
PG_USER = os.getenv("PGUSER", "")
PG_PASS = os.getenv("PGPASSWORD", "")


def _validate_pg_config():
    """Validate PostgreSQL configuration is set."""
    missing = [
        k
        for k, v in {
            "PGHOST": PG_HOST,
            "PGPORT": PG_PORT,
            "PGDATABASE": PG_DBNAME,
            "PGUSER": PG_USER,
            "PGPASSWORD": PG_PASS,
        }.items()
        if not v
    ]
    if missing:
        print(f"[ERR] Missing required environment variables: {', '.join(missing)}")
        print("Set them before running this migration.")
        return False
    return True


def safe_json(val):
    if not val:
        return {}
    try:
        return json.loads(val)
    except Exception:
        return {}


def migrate_relational():
    if not _validate_pg_config():
        return

    if not os.path.exists(SQLITE_DB):
        print(f"[ERR] SQLite DB not found: {SQLITE_DB}")
        return

    print(f"[1/4] Connecting to SQLite: {SQLITE_DB}")
    sqlite_conn = sqlite3.connect(SQLITE_DB)
    sqlite_conn.row_factory = sqlite3.Row
    sc = sqlite_conn.cursor()

    print("[2/4] Connecting to PostgreSQL...")
    pg_conn = psycopg2.connect(
        dbname=PG_DBNAME, host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASS
    )
    pc = pg_conn.cursor()

    # ── profiles ──────────────────────────────────────────────────────────────
    print("[3/4] Migrating profiles...")
    sc.execute("SELECT * FROM profiles")
    profiles = 0
    for row in map(dict, sc.fetchall()):
        pc.execute(
            """
            INSERT INTO profiles (id, display_name, partner_name, affection, theme,
                memory_json, session_history_json, global_knowledge_json,
                providers_config_json, context, image_model, vision_model,
                timestamp, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
                display_name=EXCLUDED.display_name,
                partner_name=EXCLUDED.partner_name,
                affection=EXCLUDED.affection,
                memory_json=EXCLUDED.memory_json,
                updated_at=EXCLUDED.updated_at
        """,
            (
                row["id"],
                row["display_name"],
                row["partner_name"],
                row["affection"],
                row["theme"],
                row["memory_json"],
                row["session_history_json"],
                row["global_knowledge_json"],
                row["providers_config_json"],
                row["context"],
                row["image_model"],
                row["vision_model"],
                row.get("created_at"),
                row.get("updated_at"),
            ),
        )
        profiles += 1
    print(f"  -> {profiles} profiles upserted")

    # ── chat_sessions ────────────────────────────────────────────────────────
    print("  Migrating chat_sessions...")
    sc.execute("SELECT * FROM chat_sessions")
    sessions = 0
    for row in map(dict, sc.fetchall()):
        pc.execute(
            """
            INSERT INTO chat_sessions (id, name, is_active, message_count, memory_json,
                timestamp, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
                name=EXCLUDED.name,
                is_active=EXCLUDED.is_active,
                message_count=EXCLUDED.message_count,
                updated_at=EXCLUDED.updated_at
        """,
            (
                row["id"],
                row["name"],
                bool(row["is_active"]),
                row["message_count"],
                row["memory_json"],
                row.get("created_at"),
                row.get("updated_at"),
            ),
        )
        sessions += 1
    print(f"  -> {sessions} chat_sessions upserted")

    # ── messages ──────────────────────────────────────────────────────────────
    print("  Migrating messages...")
    sc.execute("SELECT * FROM messages")
    messages = 0
    for row in map(dict, sc.fetchall()):
        pc.execute(
            """
            INSERT INTO messages (id, session_id, role, content,
                content_encrypted, image_paths, timestamp)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
                content=EXCLUDED.content,
                role=EXCLUDED.role
        """,
            (
                row["id"],
                row["session_id"],
                row["role"],
                row["content"],
                bool(row["content_encrypted"]),
                row.get("image_paths", "{}"),
                row.get("timestamp"),
            ),
        )
        messages += 1
    print(f"  -> {messages} messages upserted")

    # ── api_keys ─────────────────────────────────────────────────────────────
    print("  Migrating api_keys...")
    sc.execute("SELECT * FROM api_keys")
    keys = 0
    for row in map(dict, sc.fetchall()):
        pc.execute(
            """
            INSERT INTO api_keys (id, key_name, key_value, key_encrypted, timestamp)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
                key_value=EXCLUDED.key_value
        """,
            (
                row["id"],
                row["key_name"],
                row["key_value"],
                bool(row["key_encrypted"]),
                row.get("created_at"),
            ),
        )
        keys += 1
    print(f"  -> {keys} api_keys upserted")

    # ── Reset sequences ──────────────────────────────────────────────────────
    print("[4/4] Resetting serial sequences...")
    for table in ["chat_sessions", "profiles", "messages", "api_keys"]:
        pc.execute(f"""
            SELECT setval(pg_get_serial_sequence('{table}', 'id'),
                coalesce(max(id), 1), true) FROM {table}
        """)

    pg_conn.commit()
    sqlite_conn.close()
    pg_conn.close()

    print("\n✅ DONE. Relational migration complete:")
    print(
        f"   {profiles} profiles, {sessions} sessions, {messages} messages, {keys} keys"
    )


if __name__ == "__main__":
    migrate_relational()
