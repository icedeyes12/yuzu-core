# [FILE: memory/quality_migrate.py]
# [DESCRIPTION: High-quality semantic memory extraction via LLM from existing episodic records]
# [USAGE: python -c "from memory.quality_migrate import run_migration; run_migration()"]
#
# Phases:
#   1. Embed unvectored episodic memories (Chutes embedding API)
#   2. Delete ALL existing low-quality semantic records (regex-extracted garbage)
#   3. LLM extract high-value facts from episodic summaries (Chutes chat API, batched)
#   4. Embed new semantic facts
#   5. Store new facts
#
# Resumable + rate-limit safe. Checkpoint saved after every batch.

import os
import json
import time
import struct
import requests
from datetime import datetime
from database import Database, get_db_session, SemanticMemory, EpisodicMemory
from sqlalchemy import text


# ─────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────

CHUTES_EMBED_ENDPOINT = "https://chutes-qwen-qwen3-embedding-8b.chutes.ai/v1/embeddings"
CHUTES_CHAT_ENDPOINT = "https://llm.chutes.ai/v1/chat/completions"

# Cost control: smaller model = cheaper + faster for extraction
EXTRACTION_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507-TEE"  # 262k context window
BATCH_SIZE = 200            # episodes per LLM call (fits ~262k context)
EMBED_BATCH_SIZE = 32      # embed calls
LLM_TIMEOUT = 180           # seconds (was timing out at 120)
WAIT_BETWEEN_BATCHES = 5    # seconds (avoid rate limit)
MAX_RETRIES = 5
CHECKPOINT_FILE = os.path.join(os.path.dirname(__file__), 'quality_migrate_checkpoint.json')

_start_time = None

# ─────────────────────────────────────────────────────────────
# Timestamped logging
# ─────────────────────────────────────────────────────────────

def _ts():
    return datetime.now().strftime('%H:%M:%S')

def _log(msg):
    elapsed = time.time() - (_start_time or time.time())
    print(f"  [{_ts()}] {msg}")

def _log_phase(phase_num, title):
    print(f"\n[{_ts()}] === Phase {phase_num}: {title} ===")

# ─────────────────────────────────────────────────────────────
# Checkpoint
# ─────────────────────────────────────────────────────────────

def _load_cp():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return {
        "phase": 0,
        "episodic_embedded": 0,
        "episodic_extracted": 0,
        "semantic_embedded": 0,
        "started_at": None,
        "last_run": None,
    }

def _save_cp(cp):
    cp["last_run"] = datetime.now().isoformat()
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(cp, f, indent=2)

# ─────────────────────────────────────────────────────────────
# Chutes API helpers
# ─────────────────────────────────────────────────────────────

def _get_llm_key():
    """Get Chutes key for LLM extraction calls."""
    return Database.get_api_key("chutes")

def _embed_batch(texts, retries=MAX_RETRIES):
    """Embed texts via Chutes embedding API."""
    if not texts:
        return []
    for attempt in range(retries):
        try:
            
            resp = requests.post(
                CHUTES_EMBED_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {_get_llm_key()}",
                    "HTTP-Referer": "https://github.com/icedeyes12/yuzu-companion",
                    "X-Title": "Yuzu-Migration",
                    "Content-Type": "application/json",
                },
                json={
                    "input": texts,
                    "model": "Qwen/Qwen3-Embedding-8B",
                    "encoding_format": "float",
                },
                timeout=60,
            )
            if resp.status_code == 429:
                wait = 2 ** attempt * 10
                _log(f"[RATE LIMIT] Embed batch hit limit, waiting {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return [item["embedding"] for item in resp.json()["data"]]
        except Exception as e:
            wait = 2 ** attempt * 5
            _log(f"[RETRY] Embed batch failed ({attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(wait)
    return [None] * len(texts)

def _vec_to_blob(vec):
    return struct.pack(f'{len(vec)}f', *vec)

# ─────────────────────────────────────────────────────────────
# OpenRouter LLM (used for extraction — bypasses Chutes rate limit)
# ─────────────────────────────────────────────────────────────

OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
OR_KEY = None  # lazy-loaded

def _extract_facts_via_llm(episodes, retries=MAX_RETRIES):
    """
    Call Chutes chat API to extract high-value semantic facts from episode summaries.
    episodes: list of dicts with 'id' and 'summary' only
    Returns: list of dicts with 'fact', 'category'
    """
    # Build the prompt — only use 'summary' (no 'title' field exists)
    episodes_text = "\n\n".join([
        f"Episode {i+1}:\n{e['summary']}"
        for i, e in enumerate(episodes)
    ])

    system_prompt = """You are a HIGH-QUALITY knowledge extraction specialist.

Extract ONLY persistent, high-value facts from the conversation episodes below.

## CRITICAL: Extract ONLY facts that pass ALL FOUR tests:

1. **Persistence Test**: Will this still be true in 6 months? (not a temporary reaction)
2. **Specificity Test**: Does it contain concrete, searchable information? (not vague)
3. **Utility Test**: Can this help predict future user needs or preferences?
4. **Independence Test**: Can this be understood WITHOUT the conversation context?

## EXTRACT THESE CATEGORIES:
- identity: name, profession, location, company, education
- preference: likes, dislikes, favorites, stylistic choices
- interest: topics, hobbies, domains they engage with
- personality: communication style, emotional tendencies
- relationship: how they treat you, shared routines, inside jokes
- experience: skills, past events, professional background
- goal: plans, aspirations, things they're working toward
- guideline: how you (assistant) should behave around them

## SKIP THESE:
- single-emotion reactions (happy, sad, frustrated in one moment)
- acknowledgments or greetings
- vague statements without specifics
- context-dependent information

## RESPOND WITH JSON ONLY:
{
  "facts": [
    {"fact": "the exact fact statement in present tense", "category": "preference"},
    ...
  ]
}

Quality over quantity. If an episode has no valuable facts, return empty facts array."""

    user_content = f"""Extract knowledge from these episodes:

{episodes_text}

Respond with JSON only."""

    for attempt in range(retries):
        try:
            print("[DEBUG] LLM URL: " + CHUTES_CHAT_ENDPOINT)
            print("[DEBUG] LLM Model: " + EXTRACTION_MODEL)
            llm_key = _get_llm_key()
            print("[DEBUG] LLM Key prefix: " + (llm_key[:10] if llm_key else "None"))
            print("[DEBUG] Episode count: " + str(len(episodes)))

            resp = requests.post(
                CHUTES_CHAT_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {_get_llm_key()}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": EXTRACTION_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 2048,
                },
                timeout=LLM_TIMEOUT,
            )
            if resp.status_code == 429:
                wait = 2 ** attempt * 15
                _log(f"[RATE LIMIT] LLM batch hit limit, waiting {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code == 402:
                _log(f"[RATE LIMIT] Payment required - budget exhausted. Will retry later.")
                wait = 2 ** attempt * 60
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

            # Extract JSON from response
            try:
                # Try direct JSON parse first
                parsed = json.loads(content)
            except json.JSONDecodeError:
                # Try extracting from markdown code blocks
                import re
                m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
                if m:
                    parsed = json.loads(m.group(1))
                else:
                    _log(f"[WARN] Could not parse JSON from LLM response: {content[:200]}")
                    return []

            facts = parsed.get("facts", [])
            # Validate
            validated = []
            for f in facts:
                if isinstance(f, dict) and f.get("fact") and f.get("category"):
                    fact_text = f["fact"].strip()
                    if 5 < len(fact_text) < 300:  # Reasonable length
                        validated.append({
                            "fact": fact_text,
                            "category": f["category"],
                        })
            return validated

        except Exception as e:
            wait = 2 ** attempt * 10
            _log(f"[RETRY] LLM extraction failed ({attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(wait)
    return []

# ─────────────────────────────────────────────────────────────
# Phase 1: Embed unvectored episodic memories
# ─────────────────────────────────────────────────────────────

def phase1_embed_episodic(cp):
    _log_phase(1, "Embedding unvectored episodic memories")

    with get_db_session() as session:
        total = session.query(EpisodicMemory).count()
        unembedded = session.query(EpisodicMemory).filter(
            EpisodicMemory.embedding == None
        ).order_by(EpisodicMemory.id.asc()).all()

    if not unembedded:
        _log("All episodic memories already have vectors — skip")
        cp["phase"] = 1
        _save_cp(cp)
        return 0

    _log(f"Embedding {len(unembedded)} records (batch_size={EMBED_BATCH_SIZE})...")

    # Load IDs + texts inside session
    items = []
    for rec in unembedded:
        items.append({"id": rec.id, "text": rec.summary or ""})

    start_offset = cp.get("episodic_embedded", 0)
    items = items[start_offset:]
    migrated = 0

    for batch_start in range(0, len(items), EMBED_BATCH_SIZE):
        batch = items[batch_start:batch_start + EMBED_BATCH_SIZE]
        vecs = _embed_batch([item["text"] for item in batch])

        with get_db_session() as session:
            for j, item in enumerate(batch):
                rec = session.query(EpisodicMemory).filter_by(id=item["id"]).first()
                if rec and vecs[j] is not None:
                    rec.embedding = _vec_to_blob(vecs[j])
                    session.commit()

        migrated += len(batch)
        cp["episodic_embedded"] = start_offset + migrated
        _save_cp(cp)

        rate = migrated / max(time.time() - _start_time, 0.1)
        _log(f"  {migrated}/{len(items)} | {rate:.1f}/s")

    cp["phase"] = 1
    _save_cp(cp)
    _log(f"Done: {migrated} episodic memories embedded")
    return migrated

# ─────────────────────────────────────────────────────────────
# Phase 2: Delete all existing semantic records
# ─────────────────────────────────────────────────────────────

def phase2_delete_old_semantic(cp):
    _log_phase(2, "Deleting low-quality semantic memories")

    with get_db_session() as session:
        count = session.query(SemanticMemory).delete()
        session.commit()
        _log(f"Deleted {count} semantic records")
        session.execute(text("VACUUM"))

    cp["phase"] = 2
    _save_cp(cp)
    return count

# ─────────────────────────────────────────────────────────────
# Phase 3: LLM extract facts from episodic summaries (batched)
# ─────────────────────────────────────────────────────────────

def phase3_extract_facts(cp):
    _log_phase(3, "LLM extraction of high-value facts from episodic memories")

    with get_db_session() as session:
        episodic_records = session.query(EpisodicMemory).order_by(
            EpisodicMemory.id.asc()
        ).all()
        # Load inside session to avoid detach
        episodic_data = [
            {"id": r.id, "summary": r.summary or ""}
            for r in episodic_records
        ]

    if not episodic_data:
        _log("No episodic records found")
        cp["phase"] = 3
        _save_cp(cp)
        return 0

    _log(f"Processing {len(episodic_data)} episodic records (batch_size={BATCH_SIZE})...")

    start_offset = cp.get("episodic_extracted", 0)
    episodic_data = episodic_data[start_offset:]
    extracted_facts = []  # list of {"fact": ..., "category": ...}

    for batch_start in range(0, len(episodic_data), BATCH_SIZE):
        batch = episodic_data[batch_start:batch_start + BATCH_SIZE]
        facts = _extract_facts_via_llm(batch)

        for f in facts:
            f["source_episode_id"] = batch[0]["id"]  # associate with first episode in batch

        extracted_facts.extend(facts)
        cp["episodic_extracted"] = start_offset + batch_start + len(batch)
        _save_cp(cp)

        # Progress log
        total_done = cp["episodic_extracted"]
        _log(f"  {total_done}/{len(episodic_data) + start_offset} episodes | {len(extracted_facts)} facts extracted so far")

    cp["phase"] = 3
    cp["extracted_facts"] = extracted_facts  # Store in checkpoint for resumability
    _save_cp(cp)
    _log(f"Done: {len(extracted_facts)} facts extracted from episodic memories")
    return len(extracted_facts)

# ─────────────────────────────────────────────────────────────
# Phase 4: Embed new semantic facts
# ─────────────────────────────────────────────────────────────

def phase4_embed_and_store_facts(cp):
    _log_phase(4, "Embedding and storing new semantic facts")

    facts = cp.get("extracted_facts", [])
    if not facts:
        _log("No facts to store — skip")
        cp["phase"] = 4
        _save_cp(cp)
        return 0

    _log(f"Embedding {len(facts)} facts...")

    # Build search text for each fact (category prefix helps embedding)
    texts_to_embed = [f"{f['category']}: {f['fact']}" for f in facts]
    vecs = _embed_batch(texts_to_embed)

    now = datetime.now()
    stored = 0

    with get_db_session() as session:
        for j, f in enumerate(facts):
            if vecs[j] is None:
                continue
            mem = SemanticMemory(
                session_id=1,  # default session
                entity="User",
                relation=f["category"].title(),
                target=f["fact"],
                confidence=0.7,
                importance=0.7,
                embedding_vector=_vec_to_blob(vecs[j]),
                last_accessed=now,
                access_count=0,
            )
            session.add(mem)
            stored += 1

            if stored % 100 == 0:
                session.commit()
                _log(f"  {stored}/{len(facts)} stored...")

        session.commit()

    # Clear extracted_facts from checkpoint (done)
    cp["extracted_facts"] = []
    cp["phase"] = 4
    _save_cp(cp)
    _log(f"Done: {stored} high-quality semantic facts stored")
    return stored

# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def run_migration():
    global _start_time
    _start_time = time.time()

    print("=" * 60)
    print("[QUALITY MIGRATION] LLM-Based Semantic Memory Rebuild")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 60)

    cp = _load_cp()
    if cp.get("started_at") is None:
        cp["started_at"] = datetime.now().isoformat()
        _save_cp(cp)

    # Phase 1: Embed unvectored episodic records
    if cp.get("phase", 0) < 1:
        phase1_embed_episodic(cp)
    else:
        _log_phase(1, "Embedding unvectored episodic memories — SKIPPED (already done)")

    # Phase 2: Delete old bad semantic records
    if cp.get("phase", 0) < 2:
        phase2_delete_old_semantic(cp)
    else:
        _log_phase(2, "Deleting low-quality semantic records — SKIPPED (already done)")

    # Phase 3: LLM extract facts
    if cp.get("phase", 0) < 3:
        phase3_extract_facts(cp)
    else:
        _log_phase(3, "LLM fact extraction — SKIPPED (already done)")

    # Phase 4: Embed + store new facts
    if cp.get("phase", 0) < 4:
        phase4_embed_and_store_facts(cp)
    else:
        _log_phase(4, "Embedding and storing facts — SKIPPED (already done)")

    elapsed = time.time() - _start_time
    print("\n" + "=" * 60)
    print("[QUALITY MIGRATION] COMPLETE")
    print("=" * 60)
    print(f"  Time: {elapsed:.0f}s")
    print(f"  Checkpoint: {CHECKPOINT_FILE}")
    print("  Resume anytime by running the same command")
    print("=" * 60)


if __name__ == "__main__":
    run_migration()
