# [FILE: memory/episodic_migrate.py]
# [DESCRIPTION: Regenerate episodic summaries with LLM - raw snippets → proper narrative + title]
# [USAGE: python -c "from memory.episodic_migrate import run; run()"]
#
# Converts raw message snippets in episodic.summary into:
#   - metadata["title"]: 5-15 word narrative title
#   - summary: 2-3 sentence third-person narrative summary
#
# Then re-embeds with new summary text.
import os, json, time, struct, requests
from datetime import datetime
from database import Database, get_db_session, EpisodicMemory
from sqlalchemy import text

CHUTES_EMBED_ENDPOINT = "https://chutes-qwen-qwen3-embedding-8b.chutes.ai/v1/embeddings"
CHUTES_CHAT_ENDPOINT = "https://llm.chutes.ai/v1/chat/completions"
EXTRACTION_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507-TEE"
BATCH_SIZE = 30  # episodes per LLM call
LLM_TIMEOUT = 120
CHECKPOINT_FILE = os.path.join(os.path.dirname(__file__), 'episodic_migrate_checkpoint.json')

OR_KEY = None

def _get_llm_key():
    global OR_KEY
    if OR_KEY is None:
        OR_KEY = Database.get_api_key("chutes")  # Chutes BYOK
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
    return {"phase": 0, "episodic_summarized": 0, "episodic_re_embedded": 0, "started_at": None, "last_run": None}

def _save_cp(cp):
    cp["last_run"] = datetime.now().isoformat()
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(cp, f, indent=2)

def _vec_to_blob(vec):
    return struct.pack(f'{len(vec)}f', *vec)

def _summarize_episodes_batch(episodes, retries=5):
    """
    Call LLM to generate proper narrative title + summary for each episode.
    episodes: list of dicts with 'id' and 'raw_snippets' (current summary text)
    Returns: list of dicts with 'id', 'title', 'narrative_summary'
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
                _log(f"[BUDGET] Payment required - stopping.")
                return []
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

            # Parse JSON
            import re
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
            # Validate
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
    """Update episodic records with new title + summary + re-embed."""
    updated = 0
    texts_to_embed = []
    ids_to_embed = []

    with get_db_session() as session:
        for r in results:
            rec = session.query(EpisodicMemory).filter_by(id=r["id"]).first()
            if rec:
                # Store title in metadata
                existing_meta = {}
                if rec.metadata:
                    try:
                        existing_meta = json.loads(rec.metadata) if isinstance(rec.metadata, str) else (rec.metadata or {})
                    except:
                        existing_meta = {}
                existing_meta["title"] = r["title"]
                rec.metadata = json.dumps(existing_meta)
                # Update summary with narrative
                rec.summary = r["summary"]
                updated += 1
                texts_to_embed.append(r["summary"])
                ids_to_embed.append(r["id"])

    # Re-embed in batch
    if texts_to_embed:
        vecs = _re_embed_batch(texts_to_embed)
        with get_db_session() as session:
            for i, eid in enumerate(ids_to_embed):
                if vecs[i] is not None:
                    rec = session.query(EpisodicMemory).filter_by(id=eid).first()
                    if rec:
                        rec.embedding = _vec_to_blob(vecs[i])
        session.commit()

    return updated

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

    # Load all episodic records
    _log_phase("Loading episodic memories")
    with get_db_session() as session:
        total = session.query(EpisodicMemory).count()
        all_epi = session.query(EpisodicMemory).order_by(EpisodicMemory.id.asc()).all()

    _log(f"Total episodic records: {total}")
    _log(f"Checkpoint: phase={cp['phase']}, summarized={cp['episodic_summarized']}")

    if cp["phase"] >= 2:
        _log("Phase 2 (LLM summarization) already complete. Skipping.")
        phase2_done = total
    else:
        # Phase 1: LLM summarization
        _log_phase("Phase 1: LLM Narrative Summarization")
        start_offset = cp.get("episodic_summarized", 0)
        remaining = all_epi[start_offset:]
        _log(f"Starting from offset {start_offset} ({len(remaining)} to process)")

        summarized = start_offset
        BATCH = BATCH_SIZE

        for batch_start in range(0, len(remaining), BATCH):
            batch_models = remaining[batch_start:batch_start + BATCH]
            episodes_input = [
                {"id": r.id, "raw_snippets": r.summary}
                for r in batch_models
            ]

            _log(f"Processing batch {batch_start//BATCH + 1}: episodes {batch_start + 1}-{batch_start + len(batch_models)}")

            results = _summarize_episodes_batch(episodes_input)
            if not results:
                _log("No results or budget exhausted. Saving checkpoint and stopping.")
                cp["phase"] = 2
                cp["episodic_summarized"] = summarized
                _save_cp(cp)
                break

            # Update DB with new summaries + titles
            updated = _update_episodic_batch(results)
            summarized += len(batch_models)
            cp["episodic_summarized"] = summarized
            _save_cp(cp)

            elapsed = time.time() - t0
            rate = summarized / max(elapsed, 0.1)
            eta = (len(remaining) - batch_start - BATCH) / max(rate, 0.1)
            _log(f"Progress: {summarized}/{total} | {rate:.1f}/s | ETA: {eta:.0f}s")

            time.sleep(2)  # Be nice to the API

        # Mark phase 1 done
        cp["phase"] = 2
        _save_cp(cp)
        _log(f"Phase 1 complete: {summarized} episodic records summarized")

    elapsed = time.time() - t0
    print(f"\n{'=' * 60}")
    print(f"DONE in {elapsed:.1f}s")
    print(f"Episodic summarized: {cp['episodic_summarized']}/{total}")
    print(f"Checkpoint saved to: {CHECKPOINT_FILE}")
    print("=" * 60)

if __name__ == "__main__":
    run()
