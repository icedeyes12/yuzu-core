import sqlite3
import psycopg2
import json

def migrate_relational():
    # Koneksi SQLite
    sqlite_conn = sqlite3.connect('yuzu_core.db')
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()

    # Koneksi PostgreSQL
    pg_conn = psycopg2.connect(dbname="yuzuki", host="127.0.0.1", port="5432")
    pg_cursor = pg_conn.cursor()

    def safe_json(val):
        if not val:
            return {}
        try:
            return json.loads(val)
        except Exception:
            return {}

    # --- 1. Migrasi Chat Sessions ---
    print("???? Memproses chat_sessions...")
    sqlite_cursor.execute("SELECT * FROM chat_sessions")
    for row in sqlite_cursor.fetchall():
        row = dict(row)
        pg_cursor.execute(
            "INSERT INTO chat_sessions (id, title, created_at, updated_at) VALUES (%s, %s, %s, %s)",
            (row['id'], row['title'], row['created_at'], row['updated_at'])
        )

    # --- 2. Migrasi Profiles ---
    print("???? Memproses profiles...")
    sqlite_cursor.execute("SELECT * FROM profiles")
    for row in sqlite_cursor.fetchall():
        row = dict(row)
        pg_cursor.execute(
            "INSERT INTO profiles (id, name, bio, context, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (row['id'], row['name'], row['bio'], row['context'], row['created_at'], row['updated_at'])
        )

    # --- 3. Migrasi Messages ---
    print("???? Memproses messages...")
    sqlite_cursor.execute("SELECT * FROM messages")
    for row in sqlite_cursor.fetchall():
        row = dict(row)
        pg_cursor.execute(
            "INSERT INTO messages (id, session_id, role, content, tokens, metadata, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (row['id'], row['session_id'], row['role'], row['content'], row['tokens'], json.dumps(safe_json(row['metadata'])), row['created_at'])
        )

    # --- 4. Migrasi API Keys ---
    print("???? Memproses api_keys...")
    sqlite_cursor.execute("SELECT * FROM api_keys")
    for row in sqlite_cursor.fetchall():
        row = dict(row)
        pg_cursor.execute(
            "INSERT INTO api_keys (id, provider, key_value, is_active, created_at) VALUES (%s, %s, %s, %s, %s)",
            (row['id'], row['provider'], row['key_value'], row['is_active'], row['created_at'])
        )

    # Menyelaraskan ulang Sequence ID agar tidak bentrok saat insert data baru
    print("???? Menyelaraskan ulang Primary Key Sequences...")
    tables = ['chat_sessions', 'profiles', 'messages', 'api_keys']
    for table in tables:
        pg_cursor.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), coalesce(max(id), 1)) FROM {table}")

    pg_conn.commit()
    sqlite_conn.close()
    pg_conn.close()
    print("??? Beres, Bas! Semua data relasional udah nangkring di PostgreSQL.")

if __name__ == "__main__":
    migrate_relational()
