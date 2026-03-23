import struct
import requests
from datetime import datetime
from database import Database, get_db_session, SemanticMemory
from tools.registry import build_markdown_contract

CHUTES_EMBED_ENDPOINT = "https://chutes-qwen-qwen3-embedding-8b.chutes.ai/v1/embeddings"
_CACHED_KEY = None

def _get_chutes_key():
    global _CACHED_KEY
    if _CACHED_KEY is None:
        _CACHED_KEY = Database.get_api_key("chutes")
    return _CACHED_KEY

def _embed_single(text):
    try:
        resp = requests.post(
            CHUTES_EMBED_ENDPOINT,
            headers={"Authorization": f"Bearer {_get_chutes_key()}", "Content-Type": "application/json"},
            json={"input": [text], "model": "Qwen/Qwen3-Embedding-8B", "encoding_format": "float"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
    except Exception as e:
        print(f"[memory_store] Embed failed: {e}")
        return None

def _vec_to_blob(vec):
    return struct.pack(f'{len(vec)}f', *vec)

def _infer_category(fact):
    s = fact.lower()
    if any(w in s for w in ["prefer", "like", "love", "hate", "dislike", "favorit"]): return "Preference"
    if any(w in s for w in ["name", "live", "work", "job", "career", "company", "city"]): return "Identity"
    if any(w in s for w in ["interest", "hobby", "learn", "study"]): return "Interest"
    if any(w in s for w in ["should", "avoid", "never", "always", "tone", "behave"]): return "Guideline"
    if any(w in s for w in ["goal", "plan", "want", "aspire"]): return "Goal"
    if any(w in s for w in ["family", "friend", "relationship", "partner"]): return "Relationship"
    if any(w in s for w in ["skill", "experience", "past"]): return "Experience"
    if any(w in s for w in ["personality", "style", "tend", "usually"]): return "Personality"
    return "Identity"

def execute(arguments, **kwargs):
    session_id = kwargs.get("session_id")
    profile = Database.get_profile() or {}
    partner_name = profile.get("partner_name", "Yuzu")

    fact = arguments.get("fact", "").strip()
    if not fact:
        return build_markdown_contract("memory_store_tools", "/memory_store", ["Error: 'fact' is required"], partner_name)

    if len(fact) < 5:
        return build_markdown_contract("memory_store_tools", "/memory_store", ["Error: Fact too short"], partner_name)
    if len(fact) > 500:
        return build_markdown_contract("memory_store_tools", "/memory_store", ["Error: Fact too long (max 500 chars)"], partner_name)

    entity = arguments.get("entity", "User")
    relation = arguments.get("relation", "Identity")
    category = arguments.get("category", _infer_category(fact))
    full_command = f"/memory_store fact={fact[:80]}..."

    vector = _embed_single(f"{entity} {relation} {fact}")
    if vector is None:
        return build_markdown_contract("memory_store_tools", full_command, ["Error: Embedding service unavailable"], partner_name)

    with get_db_session() as session:
        existing = session.query(SemanticMemory).filter(
            SemanticMemory.session_id == session_id,
            SemanticMemory.entity == entity,
            SemanticMemory.relation == relation,
            SemanticMemory.target == fact,
        ).first()

        if existing:
            existing.confidence = min((existing.confidence or 0.5) + 0.1, 1.0)
            existing.access_count = (existing.access_count or 0) + 1
            existing.last_accessed = datetime.now()
            session.commit()
            return build_markdown_contract("memory_store_tools", full_command, [f"Already remembered (confidence {existing.confidence:.2f})"], partner_name)

        new_mem = SemanticMemory(
            session_id=session_id,
            entity=entity, relation=relation, target=fact,
            confidence=0.7, importance=0.6,
            embedding_vector=_vec_to_blob(vector),
            last_accessed=datetime.now(), access_count=1,
        )
        session.add(new_mem)
        session.commit()

    return build_markdown_contract("memory_store_tools", full_command, [f"Stored: [{category}] {entity} {relation} {fact}"], partner_name)
