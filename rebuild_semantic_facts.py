#!/usr/bin/env python3
"""
Rebuild semantic_facts from message history.
Reads messages from PostgreSQL, extracts facts via LLM, embeds, and stores in semantic_facts.
"""
import os
import sys
import json
import time

# Add app to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db_pg import PgSession, pg_fetchall, pg_execute


def get_all_sessions():
    """Get all chat sessions."""
    return pg_fetchall("SELECT id FROM chat_sessions ORDER BY id")


def get_session_messages(session_id: int, limit: int = 100):
    """Get messages for a session."""
    return pg_fetchall(
        "SELECT id, role, content, timestamp FROM messages WHERE session_id = %s AND role IN ('user', 'assistant') ORDER BY id LIMIT %s",
        (session_id, limit)
    )


def extract_facts_from_messages(messages: list[dict]) -> list[dict]:
    """Extract semantic facts from messages using LLM."""
    if not messages:
        return []
    
    # Format messages for LLM
    conversation = "\n".join([
        f"{m['role']}: {m['content'][:200]}"
        for m in messages[-20:]  # Last 20 messages
        if m.get('content')
    ])
    
    if not conversation.strip():
        return []
    
    prompt = f"""Extract persistent facts from this conversation. Focus on:
- User preferences and habits
- Facts about the user or assistant
- Relationship dynamics
- Important decisions or topics discussed

Conversation:
{conversation}

Return JSON array of facts:
[
  {{"fact": "fact text", "category": "preference|behavior|identity|relationship"}},
  ...
]
Return empty array if no valuable facts."""
    
    try:
        from app.providers import AIProviderManager
        
        manager = AIProviderManager()
        resp = manager.send_message(
            provider_name="chutes",
            message=prompt,
            model="Qwen/Qwen3-Next-80B-A3B-Instruct",
            system_prompt="You are a fact extraction assistant. Return ONLY JSON.",
            max_tokens=500,
            temperature=0.3
        )
        
        content = resp.get("content", "") if isinstance(resp, dict) else str(resp)
        
        # Parse JSON
        try:
            facts = json.loads(content)
            if isinstance(facts, dict) and "facts" in facts:
                facts = facts["facts"]
        except json.JSONDecodeError:
            return []
        
        validated = []
        for f in facts:
            if isinstance(f, dict) and f.get("fact"):
                validated.append({
                    "fact": f["fact"][:300],
                    "category": f.get("category", "behavior")
                })
        return validated
        
    except Exception as e:
        print(f"  [WARN] LLM extraction failed: {e}")
        return []


def embed_fact(fact_text: str) -> list[float] | None:
    """Embed a fact text."""
    try:
        from app.memory.embedder import embed_text
        result = embed_text(fact_text)
        return result  # Returns list[float] or None
    except Exception as e:
        print(f"  [WARN] Embedding failed: {e}")
        return None


def store_fact(session_id: int, content: str, embedding: list[float], category: str, fact_type: str = "static"):
    """Store a fact in semantic_facts."""
    import json as json_lib
    
    # embedding is already a list[float], psycopg2 handles it directly for TEXT column
    metadata = json_lib.dumps({
        "category": category,
        "session_id": session_id,
        "importance": 0.7,
        "confidence": 0.7
    })
    
    try:
        with PgSession() as s:
            cur = s.conn.cursor()
            cur.execute(
                """
                INSERT INTO semantic_facts (fact_type, content, embedding, metadata, created_at, last_accessed)
                VALUES (%s, %s, %s, %s, NOW(), NOW())
                """,
                (fact_type, content, embedding, metadata)
            )
            s.conn.commit()
        return True
    except Exception as e:
        print(f"  [WARN] Store failed: {e}")
        return False


def truncate_semantic_facts():
    """Clear all semantic_facts before rebuild."""
    try:
        pg_execute("TRUNCATE semantic_facts RESTART IDENTITY CASCADE")
        print("[OK] semantic_facts truncated")
    except Exception as e:
        print(f"[WARN] TRUNCATE failed (may not exist): {e}")


def main():
    print("=" * 60)
    print("[REBUILD] Semantic Facts from Message History")
    print("=" * 60)
    
    # Step 1: Clear existing semantic_facts
    print("\n[1] Clearing existing semantic_facts...")
    truncate_semantic_facts()
    
    # Step 2: Get all sessions
    print("\n[2] Reading sessions...")
    sessions = get_all_sessions()
    print(f"    Found {len(sessions)} sessions")
    
    total_facts = 0
    
    for i, sess in enumerate(sessions):
        session_id = sess.get("id")
        print(f"\n[3.{i+1}] Processing session {session_id}...")
        
        # Get messages
        messages = get_session_messages(session_id, limit=200)
        print(f"    Got {len(messages)} messages")
        
        if not messages:
            continue
        
        # Extract facts
        facts = extract_facts_from_messages(messages)
        print(f"    Extracted {len(facts)} facts")
        
        for fact in facts:
            # Embed
            embedding = embed_fact(fact["fact"])
            if embedding is None:
                continue
            
            # Store
            if store_fact(session_id, fact["fact"], embedding, fact["category"]):
                total_facts += 1
                print(f"    + Stored: {fact['fact'][:50]}...")
        
        time.sleep(1)  # Rate limit
    
    print("\n" + "=" * 60)
    print(f"[DONE] Total facts stored: {total_facts}")
    print("=" * 60)


if __name__ == "__main__":
    main()
