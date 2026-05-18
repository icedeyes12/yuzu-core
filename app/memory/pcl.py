# FILE: app/memory/pcl.py
# DESCRIPTION: Predict-Calibrate Learning (PCL) pipeline.
#              Aligns with plast-mem's PredictCalibrateJob.
#
# Flow:
#   1. PREDICT — generate prediction of episode content from existing semantic knowledge
#   2. CALIBRATE — compare prediction with actual messages, extract knowledge gaps
#   3. CONSOLIDATE — apply new/reinforce/update/invalidate actions to DB
#
# Reference: Nemori Predict-Calibrate Learning (arXiv:2508.03341)

from __future__ import annotations

import logging

__all__ = [
    "run_predict_calibrate",
    "load_relevant_semantic_facts",
    "predict_episode_content",
    "calibrate_and_extract",
    "consolidate_facts",
]

from datetime import datetime
from psycopg.types.json import Json
from app.memory.db_memory import (
    invalidate_fact,
    get_fact_by_id,
    FACT_TYPE_STATIC,
)
from app.memory.extractor import upsert_semantic_memory

logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

DEDUPE_THRESHOLD = 0.03  # cosine distance — lower = stricter dedup (was 0.05)
MAX_FACTS_FOR_PREDICTION = 10

# Per-category caps: prevent any single category from dominating the memory store.
# When a category is at cap, new facts in that category are skipped during consolidation.
_CATEGORY_CAPS = {
    "Identity": 20,
    "Preference": 30,
    "Interest": 20,
    "Personality": 15,
    "Experience": 50,
    "Goal": 10,
    "Guideline": 10,
    "Relationship": 20,
}


# ── 1. Load relevant facts ────────────────────────────────────────────────────


def load_relevant_semantic_facts(
    session_id: int, limit: int = MAX_FACTS_FOR_PREDICTION
):
    """Fetch top semantic facts for a session to use in PREDICT phase."""
    from app.memory.db_memory import get_facts_by_session

    facts = get_facts_by_session(session_id, fact_type=FACT_TYPE_STATIC, limit=limit)
    # Filter out invalidated ones
    active = [f for f in facts if not f.get("invalid_at")]
    return active


# ── 2. PREDICT phase ──────────────────────────────────────────────────────────


def _build_facts_context(facts: list[dict]) -> str:
    """Format facts for the prediction prompt."""
    if not facts:
        return "No existing semantic knowledge."
    lines = []
    for f in facts:
        meta = f.get("metadata", {})
        content = f.get("content", "")
        category = meta.get("category", meta.get("relation", "unknown"))
        lines.append(f"- [{category}] {content}")
    return "\n".join(lines)


def predict_episode_content(
    existing_facts: list[dict],
    episode_summary: str,
    segment_messages: list[dict] = None,
) -> str | None:
    """PREDICT: Generate a prediction of what the episode contains, based on known facts.

    Returns predicted episode content as a string, or None on failure.
    """
    try:
        from app import get_ai_manager

        ai_manager = get_ai_manager()
    except Exception as e:
        logger.warning(f"AI manager unavailable: {e}")
        return None

    facts_context = _build_facts_context(existing_facts)

    system_prompt = """You are a topic mapper. Given a set of known facts, produce a JSON array of likely discussion topics derived DIRECTLY from those facts.

## OUTPUT FORMAT (JSON array ONLY, no other text)
Return exactly a JSON array of strings. Each string is a topic.

## FORMAT ILLUSTRATION (placeholders only, never copy these values)
["<topic1>", "<topic2>"]

## RULES
- Derive topics ONLY from the provided facts. Do not invent.
- If a fact says 'User works as chef', the topic can be 'User occupation'. Never invent 'User is a sushi chef at Restaurant X'.
- If no facts are provided, output: ["No prior knowledge — cold start"]
- Output the JSON array ONLY. No markdown, no explanation."""

    user_prompt = f"""Existing knowledge:
{facts_context}

Episode summary to predict:
\"\"\"{episode_summary}\"\"\"

Based on the existing knowledge and episode summary, list the topics that are likely to appear in this episode. Return ONLY a JSON array of topic strings."""

    try:
        response = ai_manager._internal_llm_call(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=30,
            max_tokens=600,
        )
        if response and isinstance(response, str) and response.strip():
            return response.strip()
    except Exception as e:
        logger.warning(f"PREDICT phase failed: {e}")

    return None


# ── 3. CALIBRATE phase ────────────────────────────────────────────────────────


def _build_messages_context(messages: list[dict]) -> str:
    """Format messages for the calibration prompt."""
    lines = []
    for m in messages:
        role = m.get("role", "unknown")
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                c.get("text", "") for c in content if c.get("type") == "text"
            )
        label = "User" if role == "user" else "AI"
        lines.append(f"{label}: {content[:300]}")
    return "\n".join(lines)


_CATEGORY_MAP = {
    "identity": "Identity",
    "name": "Identity",
    "profession": "Identity",
    "location": "Identity",
    "company": "Identity",
    "education": "Identity",
    "preference": "Preference",
    "likes": "Preference",
    "dislikes": "Preference",
    "favorites": "Preference",
    "interest": "Interest",
    "hobby": "Interest",
    "personality": "Personality",
    "communication_style": "Personality",
    "experience": "Experience",
    "skill": "Experience",
    "past_event": "Experience",
    "goal": "Goal",
    "aspiration": "Goal",
    "plan": "Goal",
    "guideline": "Guideline",
    "relationship": "Relationship",
}


def calibrate_and_extract(
    predicted_content: str | None,
    actual_messages: list[dict],
    existing_facts: list[dict],
) -> list[dict]:
    """CALIBRATE: Compare prediction with actual messages to identify knowledge gaps.

    Returns list of extracted knowledge statements as dicts:
        {fact, category, action: "new"|"reinforce"|"update"|"invalidate", source_id?}
    """
    try:
        from app import get_ai_manager

        ai_manager = get_ai_manager()
    except Exception as e:
        logger.warning(f"AI manager unavailable: {e}")
        return []

    messages_context = _build_messages_context(actual_messages)
    prediction_text = predicted_content or "No prediction (cold start)."
    facts_context = _build_facts_context(existing_facts)

    system_prompt = """You are a deterministic knowledge auditor. Compare a topic prediction, existing facts, and an actual conversation log. Output a JSON array of audit actions ONLY.

## OUTPUT FORMAT (JSON array ONLY, no other text)
Return exactly a JSON array of objects. Each object has the keys: fact, category, action, source_id.

## FORMAT ILLUSTRATION (placeholders only, never copy these values)
[
  {"fact": "<fact statement>", "category": "<Category>", "action": "<action>", "source_id": <integer or null>},
  ...
]

## DETERMINISTIC ACTION RULES (apply the FIRST matching rule)
1. **invalidate**: If a fact in EXISTING knowledge directly contradicts a statement in ACTUAL conversation. MUST set "source_id" to the contradicted fact's ID.
2. **update**: If a statement provides more specific/different detail for an EXISTING fact. Example pattern: existing="User likes music", actual="User likes jazz" → update. MUST set "source_id" to the refined fact's ID.
3. **reinforce**: If a fact appears in BOTH prediction topics AND actual conversation, AND matches an EXISTING fact. MUST set "source_id" to the confirmed fact's ID.
4. **new**: If a statement appears in ACTUAL conversation, is NOT in prediction topics, AND NOT in EXISTING facts. "source_id" must be null.

## STRICT OPERATIONAL RULES
- "category" MUST be one of: Identity, Preference, Interest, Personality, Relationship, Experience, Goal, Guideline.
- The "fact" field must be a self-contained, standalone statement of truth that passes: persistent, specific, useful, independent.
- Extract ONLY facts that trigger one of the four actions. Ignore trivial statements.
- If NO rules are triggered, output: []
- Output the JSON array ONLY. No markdown, no explanation, no surrounding text."""

    user_prompt = f"""Prediction (topics we expected):
{prediction_text}

Existing knowledge:
{facts_context}

Actual conversation:
{messages_context}

Apply the deterministic action rules to extract any new, updated, reinforced, or invalidated facts. Return a JSON array of actions."""

    try:
        response = ai_manager._internal_llm_call(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=30,
            max_tokens=800,
        )
        if not response:
            return []

        import json

        try:
            actions = json.loads(response)
        except json.JSONDecodeError:
            actions = []
            for i in range(len(response), 0, -1):
                try:
                    actions = json.loads(response[:i])
                    if isinstance(actions, list):
                        break
                except json.JSONDecodeError:
                    continue

        if not isinstance(actions, list):
            return []

        # Validate and normalize categories
        valid_categories = {
            "Identity",
            "Preference",
            "Interest",
            "Personality",
            "Relationship",
            "Experience",
            "Goal",
            "Guideline",
        }
        cleaned = []
        for a in actions:
            if not isinstance(a, dict):
                continue
            cat = a.get("category", "Experience")
            if cat not in valid_categories:
                # Try mapping
                cat = _CATEGORY_MAP.get(cat.lower(), "Experience")
            action = a.get("action", "new")
            if action not in ("new", "reinforce", "update", "invalidate"):
                action = "new"
            cleaned.append(
                {
                    "fact": str(a.get("fact", "")).strip(),
                    "category": cat,
                    "action": action,
                    "source_id": a.get("source_id"),
                }
            )
        return cleaned

    except Exception as e:
        logger.warning(f"CALIBRATE phase failed: {e}")
        return []


# ── 4. CONSOLIDATE phase ──────────────────────────────────────────────────────


def _map_category_to_relation(category: str) -> str:
    """Map category back to relation/triple format."""
    mapping = {
        "Identity": "identity",
        "Preference": "preference",
        "Interest": "interest",
        "Personality": "personality",
        "Relationship": "relationship",
        "Experience": "experience",
        "Goal": "goal",
        "Guideline": "guideline",
    }
    return mapping.get(category, "experience")


def _get_category_counts(session_id: int) -> dict[str, int]:
    """Count existing facts per category for the session (global static facts)."""
    from app.memory.db_memory import get_facts_by_session, FACT_TYPE_STATIC

    facts = get_facts_by_session(session_id=None, fact_type=FACT_TYPE_STATIC, limit=500)
    counts: dict[str, int] = {}
    for f in facts:
        cat = f.get("metadata", {}).get("category", "Experience")
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def consolidate_facts(extracted: list[dict], session_id: int, episode_id=None) -> dict:
    """Apply extracted knowledge actions to the DB.

    Per-category caps (_CATEGORY_CAPS) are enforced: facts in categories
    already at their cap are skipped (not inserted but reinforce/update/invalidate
    actions on existing facts still proceed).

    Returns summary: {new: n, reinforced: n, updated: n, invalidated: n}
    """
    counts = {"new": 0, "reinforced": 0, "updated": 0, "invalidated": 0}

    # Pre-count existing facts per category to enforce caps
    category_counts = _get_category_counts(session_id)

    for item in extracted:
        fact_text = item.get("fact", "")
        category = item.get("category", "Experience")
        action = item.get("action", "new")
        source_id = item.get("source_id")

        if not fact_text or len(fact_text) < 3:
            continue

        # Enforce category cap for new facts only
        if action == "new":
            cap = _CATEGORY_CAPS.get(category, 20)
            if category_counts.get(category, 0) >= cap:
                logger.debug(
                    f"Skipping new '{category}' fact (at cap {cap}): {fact_text[:50]}"
                )
                continue
            category_counts[category] = category_counts.get(category, 0) + 1

        relation = _map_category_to_relation(category)
        entity = "User"

        if action == "invalidate" and source_id:
            try:
                invalidate_fact(source_id)
                counts["invalidated"] += 1
            except Exception as e:
                logger.warning(f"Invalidate failed id={source_id}: {e}")

        elif action == "update" and source_id:
            try:
                # Invalidate old, insert new
                invalidate_fact(source_id)
                upsert_semantic_memory(
                    session_id, entity, relation, fact_text, episode_id=episode_id
                )
                counts["updated"] += 1
            except Exception as e:
                logger.warning(f"Update failed id={source_id}: {e}")

        elif action == "reinforce" and source_id:
            try:
                # Append source_episodic_ids and bump confidence
                fact = get_fact_by_id(source_id)
                if fact:
                    from app.memory.db_memory import pg_execute

                    meta = fact.get("metadata") or {}
                    ids = meta.get("source_episodic_ids", [])
                    if episode_id and episode_id not in ids:
                        ids.append(episode_id)
                    elif not ids:
                        ids = [episode_id] if episode_id else []
                    meta["source_episodic_ids"] = ids
                    meta["confidence"] = min((meta.get("confidence", 0.7) + 0.1), 1.0)
                    pg_execute(
                        "UPDATE semantic_facts SET last_accessed=%s, metadata=%s WHERE id=%s",
                        (datetime.now(), Json(meta), source_id),
                    )
                    counts["reinforced"] += 1
            except Exception as e:
                logger.warning(f"Reinforce failed id={source_id}: {e}")

        else:  # action == "new"
            try:
                upsert_semantic_memory(
                    session_id, entity, relation, fact_text, episode_id=episode_id
                )
                counts["new"] += 1
            except Exception as e:
                logger.warning(f"New fact failed: {e}")

    return counts


# ── 5. Main entry point ───────────────────────────────────────────────────────


def run_predict_calibrate(
    session_id: int,
    episode_summary: str,
    messages: list[dict],
    episode_id=None,
) -> dict | None:
    """Run the full PCL pipeline: PREDICT → CALIBRATE → CONSOLIDATE.

    Returns a summary dict or None if skipped.
    """
    if not messages:
        return None

    try:
        # 1. Load existing semantic facts
        existing = load_relevant_semantic_facts(session_id)

        # 2. PREDICT
        predicted = predict_episode_content(
            existing, episode_summary, segment_messages=messages
        )

        # 3. CALIBRATE
        extracted = calibrate_and_extract(predicted, messages, existing)

        if not extracted:
            logger.info(
                f"No knowledge gaps found — session {session_id} already aligned."
            )
            return {"new": 0, "reinforced": 0, "updated": 0, "invalidated": 0}

        # 4. CONSOLIDATE
        result = consolidate_facts(extracted, session_id, episode_id=episode_id)

        # 5. Mark episode consolidated
        if episode_id:
            try:
                from app.memory.db_memory import pg_execute

                ep = get_fact_by_id(episode_id)
                if ep:
                    meta = ep.get("metadata") or {}
                    meta["consolidated_at"] = datetime.now().isoformat()
                    pg_execute(
                        "UPDATE semantic_facts SET metadata=%s, last_accessed=%s WHERE id=%s",
                        (Json(meta), datetime.now(), episode_id),
                    )
            except Exception as e:
                logger.warning(f"Failed to mark episode {episode_id} consolidated: {e}")

        logger.info(f"session={session_id} result={result}")
        return result

    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        return None
