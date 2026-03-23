# [FILE: memory/extractor.py]
# [DESCRIPTION: Memory extraction layer - semantic + episodic writers with embeddings]

import re
from datetime import datetime
from database import (
    get_db_session, SemanticMemory, EpisodicMemory
)
from memory.embedder import embed_text, vec_to_blob


# Keywords that indicate preference or identity facts
_PREFERENCE_PATTERNS = [
    (r'\b(?:i prefer|i like|i love|i enjoy|i want|i need)\b(.+)', 'Prefers'),
    (r'\b(?:i hate|i dislike|i don\'t like|i can\'t stand)\b(.+)', 'Dislikes'),
    (r'\b(?:i am|i\'m|my name is)\b(.+)', 'Is'),
    (r'\b(?:i use|i work with|i code in|i develop in)\b(.+)', 'Uses'),
    (r'\b(?:i always|i usually|i often|i tend to)\b(.+)', 'Often'),
    (r'\b(?:aku suka|aku lebih suka|gue suka)\b(.+)', 'Prefers'),
    (r'\b(?:aku benci|aku nggak suka|gue nggak suka)\b(.+)', 'Dislikes'),
    (r'\b(?:aku pakai|aku pake)\b(.+)', 'Uses'),
]

_EMOTIONAL_KEYWORDS = [
    'angry', 'frustrated', 'sad', 'happy', 'excited', 'love',
    'hate', 'cry', 'laugh', 'upset', 'worried', 'scared',
    'marah', 'kesal', 'sedih', 'senang', 'sayang', 'benci',
    'takut', 'khawatir', 'kecewa',
]


def extract_semantic_facts(messages):
    """Extract semantic triples from a list of messages."""
    facts = []
    for msg in messages:
        if msg.get('role') != 'user':
            continue
        content = msg.get('content', '')
        for pattern, relation in _PREFERENCE_PATTERNS:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                target = match.group(1).strip()
                target = re.sub(r'[.,!?;:]+$', '', target).strip()
                if target and len(target) < 200:
                    facts.append({
                        'entity': 'User',
                        'relation': relation,
                        'target': target,
                    })
    return facts


def calculate_emotional_weight(messages):
    """Calculate emotional intensity from a list of messages. Returns 0.0–1.0."""
    if not messages:
        return 0.0
    total_hits = 0
    for msg in messages:
        content = msg.get('content', '').lower()
        for keyword in _EMOTIONAL_KEYWORDS:
            if keyword in content:
                total_hits += 1
    return min(total_hits / max(len(messages), 1) * 0.3, 1.0)


def should_create_episodic(messages, affection_delta=0):
    """Determine if an episodic memory should be created."""
    if not messages:
        return False
    emotional_weight = calculate_emotional_weight(messages)
    if emotional_weight >= 0.3:
        return True
    if len(messages) >= 10:
        return True
    if abs(affection_delta) >= 20:
        return True
    return False


def generate_episodic_summary(messages):
    """Generate a simple text summary from a list of messages (no LLM)."""
    if not messages:
        return ""
    parts = []
    for msg in messages:
        role = msg.get('role', 'unknown')
        content = msg.get('content', '')
        if len(content) > 150:
            content = content[:150] + '...'
        if role in ('user', 'assistant'):
            label = 'User' if role == 'user' else 'AI'
            parts.append(f"{label}: {content}")
    if len(parts) > 6:
        summary_parts = parts[:3] + ['...'] + parts[-3:]
    else:
        summary_parts = parts
    return '\n'.join(summary_parts)


def _embed_text(text: str) -> list[float] | None:
    """Embed a single text via Chutes API. Returns None on failure."""
    try:
        return embed_text(text)
    except Exception as e:
        print(f"[WARNING] Embedding failed: {e}")
        return None


def _build_semantic_text(entity, relation, target):
    """Build a searchable text from a semantic triple."""
    return f"{entity} {relation} {target}"


def upsert_semantic_memory(session_id, entity, relation, target):
    """Insert or update a semantic memory triple with embedding."""
    text = _build_semantic_text(entity, relation, target)
    vector = _embed_text(text)

    with get_db_session() as session:
        existing = session.query(SemanticMemory).filter(
            SemanticMemory.session_id == session_id,
            SemanticMemory.entity == entity,
            SemanticMemory.relation == relation,
            SemanticMemory.target == target,
        ).first()

        if existing:
            existing.confidence = min(existing.confidence + 0.1, 1.0)
            existing.access_count += 1
            existing.last_accessed = datetime.now()
            if vector:
                existing.embedding_vector = vec_to_blob(vector)
        else:
            new_mem = SemanticMemory(
                session_id=session_id,
                entity=entity,
                relation=relation,
                target=target,
                confidence=0.5,
                importance=0.5,
                embedding_vector=vec_to_blob(vector) if vector else None,
                last_accessed=datetime.now(),
                access_count=1,
            )
            session.add(new_mem)
        session.commit()


def create_episodic_memory(session_id, summary, emotional_weight=0.0, importance=0.5):
    """Create a new episodic memory record with embedding."""
    vector = _embed_text(summary)

    with get_db_session() as session:
        mem = EpisodicMemory(
            session_id=session_id,
            summary=summary,
            embedding=vec_to_blob(vector) if vector else None,
            importance=importance,
            emotional_weight=emotional_weight,
            last_accessed=datetime.now(),
            access_count=0,
        )
        session.add(mem)
        session.commit()


def process_messages_for_memory(session_id, messages, affection_delta=0):
    """Main entry point: analyze messages and extract memories."""
    if not messages:
        return

    # 1. Extract semantic facts
    facts = extract_semantic_facts(messages)
    for fact in facts:
        try:
            upsert_semantic_memory(
                session_id,
                fact['entity'],
                fact['relation'],
                fact['target'],
            )
        except Exception as e:
            print(f"[WARNING] Semantic memory extraction failed: {e}")

    # 2. Check if episodic memory should be created
    if should_create_episodic(messages, affection_delta):
        emotional_weight = calculate_emotional_weight(messages)
        summary = generate_episodic_summary(messages)
        if summary:
            try:
                importance = 0.5 + emotional_weight * 0.3
                create_episodic_memory(
                    session_id, summary, emotional_weight, importance
                )
            except Exception as e:
                print(f"[WARNING] Episodic memory creation failed: {e}")
