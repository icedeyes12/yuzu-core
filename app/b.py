import sqlite3
import psycopg2
import numpy as np
import json

def migrate_vectors():
    print("???? Memulai migrasi memori (Vector 4096 dims) ke PostgreSQL...")
    
    sqlite_conn = sqlite3.connect('yuzu_core.db')
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()

    pg_conn = psycopg2.connect(dbname="yuzuki", host="127.0.0.1", port="5432")
    pg_cursor = pg_conn.cursor()

    print("???? Membersihkan tabel semantic_facts...")
    pg_cursor.execute("TRUNCATE TABLE semantic_facts RESTART IDENTITY;")

    total = 0

    print("???? Memproses semantic_memories...")
    sqlite_cursor.execute("SELECT * FROM semantic_memories")
    for raw_row in sqlite_cursor.fetchall():
        row = dict(raw_row)
        
        if row.get('embedding_vector'):
            vec = np.frombuffer(row['embedding_vector'], dtype=np.float32).tolist()
            content = f"{row.get('entity') or ''} {row.get('relation') or ''} {row.get('target') or ''}".strip()
            
            if not content:
                content = "(Empty Semantic Fact)"
            
            meta = {
                "source_table": "semantic_memories",
                "confidence": row.get('confidence', 1.0),
                "stability": row.get('stability', 24.0)
            }

            pg_cursor.execute("""
                INSERT INTO semantic_facts (fact_type, content, embedding, metadata, created_at) 
                VALUES (%s, %s, %s, %s, %s)
            """, ('static', content, vec, json.dumps(meta), row.get('created_at')))
            total += 1

    for table in ['episodic_memories', 'conversation_segments']:
        print(f"???? Memproses {table}...")
        sqlite_cursor.execute(f"SELECT * FROM {table}")
        for raw_row in sqlite_cursor.fetchall():
            row = dict(raw_row)
            
            if row.get('embedding'):
                vec = np.frombuffer(row['embedding'], dtype=np.float32).tolist()
                content_value = row.get('summary')
                
                if not content_value:
                    content_value = f"(No summary found for {table} id {row.get('id')})"
                
                meta = {
                    "source_table": table,
                    "importance": row.get('importance', 0.5),
                    "session_id": row.get('session_id')
                }

                pg_cursor.execute("""
                    INSERT INTO semantic_facts (fact_type, content, embedding, metadata, created_at) 
                    VALUES (%s, %s, %s, %s, %s)
                """, ('dynamic', content_value, vec, json.dumps(meta), row.get('created_at')))
                total += 1

    pg_conn.commit()
    sqlite_conn.close()
    pg_conn.close()
    print(f"\n??? BERES, BAS! Total {total} memori vector sukses migrasi ke PostgreSQL.")

if __name__ == "__main__":
    migrate_vectors()
