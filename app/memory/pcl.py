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

import json
import logging
import re
from datetime import datetime
from psycopg.types.json import Json
from app.memory.db_memory import (
    invalidate_fact_async,
    get_fact_by_id_async,
    get_facts_by_session_async,
    FACT_TYPE_STATIC,
)
from app.memory.extractor import upsert_semantic_memory_async
from app.memory.memory import _memory_llm_call

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Enable debug logging for PCL


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


# ── JSON Extraction Utilities ─────────────────────────────────────────────────


def _extract_json_from_markdown(text: str) -> str:
    """Extract JSON payload from markdown-wrapped or plain text response.

    Handles:
    - Markdown code blocks: ```json ... ``` or ``` ... ```
    - Plain JSON arrays/objects
    - Mixed content with JSON embedded

    Returns:
        Cleaned JSON string ready for json.loads()

    Raises:
        ValueError: If no valid JSON structure found
    """
    if not text or not text.strip():
        raise ValueError("Empty response")

    cleaned = text.strip()

    # Try to extract from markdown code blocks first
    # Pattern: ```json ... ``` or ``` ... ```
    markdown_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    match = re.search(markdown_pattern, cleaned)

    if match:
        # Found markdown block, extract contents
        extracted = match.group(1).strip()
        if extracted:
            return extracted

    # Fallback: Find first [ and last ] for arrays
    if "[" in cleaned and "]" in cleaned:
        start = cleaned.find("[")
        end = cleaned.rfind("]") + 1
        return cleaned[start:end]

    # Fallback: Find first { and last } for objects
    if "{" in cleaned and "}" in cleaned:
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        return cleaned[start:end]

    # No JSON structure found
    raise ValueError(f"No JSON structure found in response: {cleaned[:200]}")


# ── 1. Load relevant facts ────────────────────────────────────────────────────


async def load_relevant_semantic_facts_async(
    session_id: int, limit: int = MAX_FACTS_FOR_PREDICTION
):
    """Fetch top semantic facts for a session (async)."""
    facts = await get_facts_by_session_async(
        session_id, fact_type=FACT_TYPE_STATIC, limit=limit
    )
    return [f for f in facts if not f.get("invalid_at")]


# ── 2. PREDICT phase ──────────────────────────────────────────────────────────


def _build_facts_context(facts: list[dict]) -> str:
    """Format facts for the calibration prompt with stable fact IDs"""
    if not facts:
        return "No existing semantic knowledge."
    lines = []
    for f in facts:
        fact_id = f.get("id", "unknown")
        meta = f.get("metadata", {})
        content = f.get("content", "")
        category = meta.get("category", meta.get("relation", "unknown"))
        lines.append(f"- [ID: {fact_id}] [Category: {category}] {content}")
    return "\n".join(lines)


async def predict_episode_content_async(
    existing_facts: list[dict],
    episode_summary: str,
    segment_messages: list[dict] = None,
) -> str | None:
    """PREDICT (async)."""
    try:
        from app.providers import get_ai_manager

        ai_manager = await get_ai_manager()
    except Exception as e:
        logger.warning(f"AI manager unavailable: {e}")
        return None

    facts_context = _build_facts_context(existing_facts)

    system_prompt = """You are a predictive memory system. Given a set of known facts and an episode summary, produce a JSON array of detailed predictions about what specific information or context the episode should contain.

## OUTPUT FORMAT (JSON array ONLY, no other text)
Return exactly a JSON array of strings. Each string is a detailed prediction sentence.

## FORMAT ILLUSTRATION (placeholders only, never copy these values)
["<User will discuss their current project involving Simulacra initialization>", "<User will mention encounter data persistence and memory bank architecture>", "<User will ask about tracking pushed/not-pushed API status>"]

## RULES
- Produce detailed, specific predictions derived from the known facts and episode context.
- Each prediction should be a full sentence describing what information or context the episode should contain.
- Base predictions on fact patterns: if a fact mentions "Simulacra initialization", predict discussion about "Simulacra initialization process, timestamps, or error states".
- If facts mention technical work, predict specific technical details, error messages, or configuration values.
- Do NOT invent new entities, products, or topics not grounded in the facts.
- If no facts are provided, output: ["No prior knowledge — cold start"]
- Output the JSON array ONLY. No markdown, no explanation."""

    user_prompt = f"""Existing knowledge:
{facts_context}

Episode summary to predict:
\"\"\"{episode_summary}\"\"\"

Based on the existing knowledge and episode summary, produce detailed predictions of what specific information or context the episode should contain. Return ONLY a JSON array of detailed prediction sentences."""

    try:
        response = await _memory_llm_call(
            ai_manager,
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
        logger.warning(f"PREDICT phase async failed: {e}")

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
        lines.append(f"{label}: {content}")
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


async def calibrate_and_extract_async(
    predicted_content: str | None,
    actual_messages: list[dict],
    existing_facts: list[dict],
    episode_summary: str | None = None,
) -> list[dict]:
    """CALIBRATE (async)."""
    try:
        from app.providers import get_ai_manager

        ai_manager = await get_ai_manager()
    except Exception as e:
        logger.warning(f"AI manager unavailable: {e}")
        return []

    messages_context = _build_messages_context(actual_messages)
    prediction_text = predicted_content or "No prediction (cold start)."
    facts_context = _build_facts_context(existing_facts)

    logger.debug(
        f"CALIBRATE: {len(actual_messages)} messages, {len(existing_facts)} existing facts"
    )
    logger.debug(f"PREDICTION: {prediction_text[:200]}...")

    system_prompt = """You are a deterministic knowledge auditor. Compare a topic prediction, existing facts, and an actual conversation log. Output a JSON array of audit actions ONLY.

## OUTPUT FORMAT (JSON array ONLY, no other text)
Return exactly a JSON array of objects. Each object has the keys: fact, category, action, source_id.

## FORMAT ILLUSTRATION (placeholders only, never copy these values)
[
  {"fact": "<fact statement>", "category": "<Category>", "action": "<action>", "source_id": <integer or null>},
  ...
]

## DETERMINISTIC ACTION RULES (apply the FIRST matching rule)
1. **invalidate**: If a fact in EXISTING knowledge directly contradicts a statement in ACTUAL conversation. MUST set "source_id" to the EXACT fact ID from the Existing Knowledge list (e.g., if you see "[ID: 42]", source_id must be 42). Never invent a fact ID.
2. **update**: If a statement provides more specific/different detail for an EXISTING fact. Example pattern: existing="User likes music", actual="User likes jazz" → update. MUST set "source_id" to the EXACT fact ID from the Existing Knowledge list. Never invent a fact ID.
3. **reinforce**: If a fact appears in BOTH prediction topics AND actual conversation, AND matches an EXISTING fact. MUST set "source_id" to the EXACT fact ID from the Existing Knowledge list. Never invent a fact ID.
4. **new**: If a statement appears in ACTUAL conversation, is NOT in prediction topics, AND NOT in EXISTING facts. "source_id" must be null.

## STRICT OPERATIONAL RULES
- "category" MUST be one of: Identity, Preference, Interest, Personality, Relationship, Experience, Goal, Guideline.
- The "fact" field must be a self-contained, standalone statement of truth that passes: persistent, specific, useful, independent.
- Extract ONLY facts that trigger one of the four actions. Ignore trivial statements.
- If NO rules are triggered, output: []
- Output the JSON array ONLY. No markdown, no explanation, no surrounding text.
- CRITICAL: For reinforce, update, or invalidate actions, you MUST use the EXACT fact ID from the Existing Knowledge list (the number after "[ID:"). Never invent or guess a fact ID.
"""

    user_prompt = f"""Episode summary:
\"\"\"{episode_summary}\"\"\"

Prediction (topics we expected):
{prediction_text}

Existing knowledge:
{facts_context}

Actual conversation:
{messages_context}

Apply the deterministic action rules to extract any new, updated, reinforced, or invalidated facts. Return a JSON array of actions."""

    try:
        response = await _memory_llm_call(
            ai_manager,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=30,
            max_tokens=800,
        )
        if not response:
            logger.warning("CALIBRATE: _memory_llm_call returned None")
            return []

        logger.debug(
            f"CALIBRATE LLM response ({len(response)} chars): {response[:500]}..."
        )

        # Extract JSON from markdown or plain text
        try:
            cleaned_json = _extract_json_from_markdown(response)
            actions = json.loads(cleaned_json)
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning(f"CALIBRATE: JSON extraction failed: {e}")
            logger.debug(f"CALIBRATE: Raw response: {response}")
            return []

        if not isinstance(actions, list):
            logger.warning(f"CALIBRATE: parsed actions is not a list: {type(actions)}")
            return []

        logger.info(f"CALIBRATE: extracted {len(actions)} raw actions")

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


async def _get_category_counts_async(session_id: int) -> dict[str, int]:
    """Count existing facts per category (async)."""
    facts = await get_facts_by_session_async(
        session_id=None, fact_type=FACT_TYPE_STATIC, limit=500
    )
    counts: dict[str, int] = {}
    for f in facts:
        cat = f.get("metadata", {}).get("category", "Experience")
        counts[cat] = counts.get(cat, 0) + 1
    return counts


async def consolidate_facts_async(
    extracted: list[dict], session_id: int, episode_id=None
) -> dict:
    """Apply extracted knowledge actions (async)."""
    counts = {"new": 0, "reinforced": 0, "updated": 0, "invalidated": 0}

    logger.info(f"CONSOLIDATE: {len(extracted)} actions to process")

    # Pre-count existing facts per category to enforce caps
    category_counts = await _get_category_counts_async(session_id)
    logger.debug(f"CONSOLIDATE: category counts: {category_counts}")

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
                await invalidate_fact_async(source_id)
                counts["invalidated"] += 1
            except Exception:
                pass

        elif action == "update" and source_id:
            try:
                # Invalidate old, insert new
                await invalidate_fact_async(source_id)
                await upsert_semantic_memory_async(
                    session_id, entity, relation, fact_text, episode_id=episode_id
                )
                counts["updated"] += 1
            except Exception as e:
                # DUPLICATE FIX: Log and continue instead of silently passing
                logger.warning(
                    f"CONSOLIDATE update failed for source_id={source_id}: {e}"
                )
                continue

        elif action == "reinforce" and source_id:
            try:
                # Append source_episodic_ids and bump confidence
                fact = await get_fact_by_id_async(source_id)
                if fact:
                    from app.memory.db_memory import pg_execute_async

                    meta = fact.get("metadata") or {}
                    ids = meta.get("source_episodic_ids", [])
                    if episode_id and episode_id not in ids:
                        ids.append(episode_id)
                    elif not ids:
                        ids = [episode_id] if episode_id else []
                    meta["source_episodic_ids"] = ids
                    meta["confidence"] = min((meta.get("confidence", 0.7) + 0.1), 1.0)
                    await pg_execute_async(
                        "UPDATE semantic_facts SET last_accessed=%s, metadata=%s WHERE id=%s",
                        (datetime.now(), Json(meta), source_id),
                    )
                    counts["reinforced"] += 1
            except Exception as e:
                # DUPLICATE FIX: Log and continue instead of silently passing
                logger.warning(
                    f"CONSOLIDATE reinforce failed for source_id={source_id}: {e}"
                )
                continue

        else:  # action == "new"
            try:
                await upsert_semantic_memory_async(
                    session_id, entity, relation, fact_text, episode_id=episode_id
                )
                counts["new"] += 1
            except Exception as e:
                # DUPLICATE FIX: Log and continue instead of silently passing
                logger.warning(
                    f"CONSOLIDATE new failed for fact: {fact_text[:50]}: {e}"
                )
                continue

    return counts


# ── 5. Main entry point ───────────────────────────────────────────────────────


async def run_predict_calibrate_async(
    session_id: int,
    episode_summary: str,
    messages: list[dict],
    episode_id=None,
) -> dict | None:
    """Run full PCL pipeline (async)."""
    if not messages:
        logger.warning("PCL: No messages provided, skipping")
        return None

    logger.info(f"PCL: Starting for session {session_id}, episode {episode_id}")

    try:
        # 1. Load existing semantic facts
        existing = await load_relevant_semantic_facts_async(session_id)
        logger.debug(f"PCL: Loaded {len(existing)} existing facts")

        # 2. PREDICT
        predicted = await predict_episode_content_async(
            existing, episode_summary, segment_messages=messages
        )
        logger.debug(
            f"PCL: Prediction result: {predicted[:100] if predicted else 'None'}..."
        )

        # 3. CALIBRATE
        extracted = await calibrate_and_extract_async(
            predicted, messages, existing, episode_summary=episode_summary
        )

        if not extracted:
            logger.info(
                f"No knowledge gaps found — session {session_id} already aligned."
            )
            return {"new": 0, "reinforced": 0, "updated": 0, "invalidated": 0}

        # 4. CONSOLIDATE
        result = await consolidate_facts_async(
            extracted, session_id, episode_id=episode_id
        )

        # 5. Mark episode consolidated
        if episode_id:
            try:
                from app.memory.db_memory import pg_execute_async

                ep = await get_fact_by_id_async(episode_id)
                if ep:
                    meta = ep.get("metadata") or {}
                    meta["consolidated_at"] = datetime.now().isoformat()
                    await pg_execute_async(
                        "UPDATE semantic_facts SET metadata=%s, last_accessed=%s WHERE id=%s",
                        (Json(meta), datetime.now(), episode_id),
                    )
            except Exception:
                pass

        logger.info(f"session={session_id} result={result}")
        return result

    except Exception as e:
        logger.error(f"PCL async failed: {e}")
        return None
