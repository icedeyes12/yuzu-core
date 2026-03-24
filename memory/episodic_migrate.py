# [FILE: memory/episodic_migrate.py]
# [DESCRIPTION: Regenerate episodic summaries with LLM - raw snippets → proper narrative + title]
# [USAGE: python -c "from memory.episodic_migrate import run; run()"]
#
# Converts raw message snippets in episodic.summary into:
#   - metadata["title"]: 5-15 word narrative title
#   - summary: 2-3 sentence third-person narrative summary
#
# Then re-embeds with new summary text.
import os
import json
import time
import struct
import requests
import re
from datetime import datetime
from database import Database, get_db_session, EpisodicMemory


CHUTES_EMBED_ENDPOINT = "https://chutes-qwen-qwen3-embedding-8b.chutes.ai/v1/embeddings"
CHUTES_CHAT_ENDPOINT = "https://llm.chutes.ai/v1/chat/completions"
EXTRACTION_MODEL = "Qwen/Qwen3-Next-80B-A3B-Instruct"
BATCH_SIZE = 30
LLM_TIMEOUT = 90
CHECKPOINT_FILE = os.path.join(os.path.dirname(__file__), 'episodic_migrate_checkpoint.json')

OR_KEY = None


def _get_llm_key():
    global OR_KEY
    if OR_KEY is None:
        OR_KEY = Database.get_api_key("chutes")
    return OR_KEY


def _ts():
    return datetime.now().strftime('%H:%M:%S')


def _log(msg):
    print(f"  [{_ts()}] {msg}")


def _log_phase(title):
    print(f"\n[{_ts()}] === {title} ===")


def _load_cp():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return {"phase": 0, "episodic_summarized": 0, "started_at": None, "last_run": None}


def _save_cp(cp):
    cp["last_run"] = datetime.now().isoformat()
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(cp, f, indent=2)


def _vec_to_blob(vec):
    return struct.pack(f'{len(vec)}f', *vec)


def _summarize_episodes_batch(episodes, retries=5):
    """
    Call LLM to generate narrative title + summary for each episode.
    episodes: list of dicts with 'id' and 'raw_snippets'
    Returns: list of dicts with 'id', 'title', 'summary'
    """
    episodes_text = "\n\n".join([
        f"Episode {i+1}:\n{e['raw_snippets']}"
        for i, e in enumerate(episodes)
    ])

    system_prompt = """You are an expert narrative summarizer. Convert raw conversation snippets into proper episodic memory records.

For each episode below, generate:
1. A "title" (5-15 words): Third-person narrative title describing what happened
2. A "summary" (2-3 sentences): Third-person narrative summary of the event

## Rules:
- Use THIRD PERSON (e.g., "The user asked about...", "Yuzu helped with...")
- Focus on: what topic was discussed, what happened, any decisions/emotions
- Skip: greetings, small talk, generic acknowledgments
- The title should be informative and specific (e.g., "User Requested Help with Supabase Password Recovery")
- The summary should capture the essence in 2-3 sentences

## RESPOND WITH JSON ONLY:
{
  "episodes": [
    {"id": 1, "title": "...", "summary": "..."},
    ...
  ]
}

Quality over quantity. If an episode is just noise, still generate a basic title/summary."""

    user_content = f"Summarize these episodes:\n\n{episodes_text}\n\nRespond with JSON only."

    for attempt in range(retries):
        try:
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
                    "max_tokens": 4096,
                },
                timeout=LLM_TIMEOUT,
            )
            if resp.status_code == 429:
                wait = 2 ** attempt * 15
                _log(f"[RATE LIMIT] LLM hit limit, waiting {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code == 402:
                _log("[BUDGET] Payment required - stopping.")
                return []
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
                if m:
                    parsed = json.loads(m.group(1))
                else:
                    _log(f"[WARN] Could not parse JSON: {content[:200]}")
                    return []

            episodes_out = parsed.get("episodes", [])
            validated = []
            for ep in episodes_out:
                if isinstance(ep, dict) and ep.get("id") and ep.get("title") and ep.get("summary"):
                    validated.append({
                        "id": ep["id"],
                        "title": ep["title"].strip()[:100],
                        "summary": ep["summary"].strip()[:500],
                    })
            return validated

        except Exception as e:
            wait = 2 ** attempt * 10
            _log(f"[RETRY] LLM call failed ({attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(wait)
    return []


def _re_embed_batch(texts, retries=5):
    if not texts:
        return []
    for attempt in range(retries):
        try:
            resp = requests.post(
                CHUTES_EMBED_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {_get_llm_key()}",
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
                _log(f"[RATE LIMIT] Embed hit limit, waiting {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return [item["embedding"] for item in resp.json()["data"]]
        except Exception as e:
            wait = 2 ** attempt * 5
            _log(f"[RETRY] Embed failed ({attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(wait)
    return [None] * len(texts)


def _update_episodic_batch(results):
    """Update episodic records with new summary text, then re-embed."""
    if not results:
        return 0

    # First: update summaries
    with get_db_session() as session:
        for r in results:
            rec = session.query(EpisodicMemory).filter_by(id=r["id"]).first()
            if rec:
                rec.summary = r["summary"]
        session.commit()

    # Second: re-embed new summaries
    texts = [r["summary"] for r in results]
    ids = [r["id"] for r in results]
    vecs = _re_embed_batch(texts)

    with get_db_session() as session:
        for i, eid in enumerate(ids):
            if vecs[i] is not None:
                rec = session.query(EpisodicMemory).filter_by(id=eid).first()
                if rec:
                    rec.embedding = _vec_to_blob(vecs[i])
        session.commit()

    return len(results)


def run():
    print("=" * 60)
    print("EPISODIC MEMORY REGENERATION")
    print("Raw snippets → Narrative title + summary + re-embed")
    print("=" * 60)

    cp = _load_cp()
    if cp.get("started_at") is None:
        cp["started_at"] = datetime.now().isoformat()
        _save_cp(cp)

    t0 = time.time()

    # Load all episodic records — extract fields INSIDE session to avoid DetachedInstanceError
    _log_phase("Loading episodic memories")
    with get_db_session() as session:
        total = session.query(EpisodicMemory).count()
        raw_records = session.query(EpisodicMemory).order_by(EpisodicMemory.id.asc()).all()
        # Convert ORM objects → plain dicts while still attached to session
        all_epi = [{"id": r.id, "summary": r.summary} for r in raw_records]

    _log(f"Total episodic records: {total}")
    _log(f"Checkpoint: phase={cp['phase']}, summarized={cp.get('episodic_summarized', 0)}")

    if cp.get("phase", 0) >= 2:
        _log("Phase 2 already complete. Skipping.")
    else:
        _log_phase("Phase 1: LLM Narrative Summarization")
        start_offset = cp.get("episodic_summarized", 0)
        remaining = all_epi[start_offset:]
        _log(f"Starting from offset {start_offset} ({len(remaining)} to process)")

        summarized = start_offset

        for batch_start in range(0, len(remaining), BATCH_SIZE):
            batch = remaining[batch_start:batch_start + BATCH_SIZE]
            _log(f"Batch {batch_start // BATCH_SIZE + 1}: episodes {batch_start + 1}–{batch_start + len(batch)}")

            batch_dicts = [{"id": r["id"], "raw_snippets": r["summary"]} for r in batch]
            results = _summarize_episodes_batch(batch_dicts)
            if not results:
                _log("No results or budget exhausted. Saving checkpoint and stopping.")
                cp["episodic_summarized"] = summarized
                _save_cp(cp)
                break

            _update_episodic_batch(results)
            summarized += len(batch)
            cp["episodic_summarized"] = summarized
            _save_cp(cp)

            elapsed = time.time() - t0
            rate = summarized / max(elapsed, 0.1)
            remaining_count = len(remaining) - batch_start - BATCH_SIZE
            eta = remaining_count / max(rate, 0.1)
            _log(f"Progress: {summarized}/{total} | {rate:.1f}/s | ETA: {eta:.0f}s")

            time.sleep(2)

        cp["phase"] = 2
        _save_cp(cp)
        _log(f"Phase 1 complete: {summarized} episodic records summarized + re-embedded")

    elapsed = time.time() - t0
    print(f"\n{'=' * 60}")
    print(f"DONE in {elapsed:.1f}s")
    print(f"Episodic summarized: {cp.get('episodic_summarized', 0)}/{total}")
    print("=" * 60)


if __name__ == "__main__":
    run()
