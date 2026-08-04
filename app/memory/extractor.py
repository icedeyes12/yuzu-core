from __future__ import annotations

import json
import logging
from typing import Any

from app.core.memory_llm import memory_llm_call
from app.providers import get_ai_manager

__all__ = [
    "extract_batch_async",
    "normalize_extraction",
    "build_extraction_prompt",
    "estimate_message_tokens",
    "build_adaptive_batches",
]


logger = logging.getLogger(__name__)


_EXTRACTION_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "memory_batch_extraction",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "episodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "start_index": {"type": "integer"},
                            "end_index": {"type": "integer"},
                            "title": {"type": "string"},
                            "summary": {"type": "string"},
                            "importance": {"type": "number"},
                        },
                        "required": [
                            "start_index",
                            "end_index",
                            "title",
                            "summary",
                            "importance",
                        ],
                    },
                },
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "entity": {"type": "string"},
                            "relation": {"type": "string"},
                            "target": {"type": "string"},
                            "confidence": {"type": "number"},
                            "evidence_start_index": {"type": "integer"},
                            "evidence_end_index": {"type": "integer"},
                        },
                        "required": [
                            "entity",
                            "relation",
                            "target",
                            "confidence",
                            "evidence_start_index",
                            "evidence_end_index",
                        ],
                    },
                },
            },
            "required": ["episodes", "claims"],
        },
    },
}

_EXTRACTION_SYSTEM_PROMPT = """Extract durable inferred memory from one conversation batch.
Return one JSON object only with keys episodes and claims. Episodes are concise summaries of meaningful interactions. Claims are objective, user-specific facts that may remain useful across sessions. Do not extract assistant behavior, temporary task state, instructions, roleplay, emotional performance, or facts about the assistant. Do not invent. Every claim needs a contiguous message-index evidence range directly supporting it. Global Knowledge and application configuration are never memory claims. Prefer no claim over a weak inference."""

_CHARS_PER_TOKEN = 4


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """Cheap conservative estimate; avoids sending an unbounded backlog."""
    return max(1, (len(_content_text(message)) + 3) // _CHARS_PER_TOKEN) + 8


def build_adaptive_batches(
    messages: list[dict[str, Any]], *, token_budget: int = 6000, max_messages: int = 100
) -> list[list[dict[str, Any]]]:
    """Split chronological messages on a token budget, keeping turns intact when possible."""
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_tokens = 0
    for message in messages:
        cost = estimate_message_tokens(message)
        if cost > token_budget:
            if current:
                batches.append(current)
                current, current_tokens = [], 0
            truncated = dict(message)
            max_chars = max(1, (token_budget - 8) * _CHARS_PER_TOKEN)
            truncated["content"] = _content_text(message)[:max_chars]
            batches.append([truncated])
            continue
        if current and (
            current_tokens + cost > token_budget or len(current) >= max_messages
        ):
            batches.append(current)
            current, current_tokens = [], 0
        current.append(message)
        current_tokens += cost
    if current:
        batches.append(current)
    return batches


def _content_text(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, list):
        return " ".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return str(content)


def _parse_extraction_response(response: str | None) -> dict[str, Any]:
    if not response:
        return {"episodes": [], "claims": []}
    text = response.strip()
    if text.startswith("```"):
        text = (
            text.removeprefix("```json")
            .removeprefix("```")
            .strip()
            .removesuffix("```")
            .strip()
        )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Single-pass memory extraction returned invalid JSON")
        return {"episodes": [], "claims": []}
    return payload if isinstance(payload, dict) else {"episodes": [], "claims": []}


def _clamp_index(value: Any, upper: int) -> int:
    try:
        return max(0, min(int(value), upper))
    except (TypeError, ValueError):
        return 0


def normalize_extraction(
    payload: dict[str, Any] | None, message_count: int
) -> dict[str, list[dict[str, Any]]]:
    normalized: dict[str, list[dict[str, Any]]] = {"episodes": [], "claims": []}
    if not isinstance(payload, dict):
        return normalized
    for raw in payload.get("episodes", []):
        if not isinstance(raw, dict):
            continue
        start, end = (
            _clamp_index(raw.get("start_index"), message_count),
            _clamp_index(raw.get("end_index"), message_count),
        )
        summary = str(raw.get("summary", "")).strip()
        if end <= start or not summary:
            continue
        try:
            importance = max(0.0, min(float(raw.get("importance", 0.5)), 1.0))
        except (TypeError, ValueError):
            importance = 0.5
        normalized["episodes"].append(
            {
                "start_index": start,
                "end_index": end,
                "title": str(raw.get("title", "")).strip()[:120],
                "summary": summary[:1000],
                "importance": importance,
            }
        )
    for raw in payload.get("claims", []):
        if not isinstance(raw, dict):
            continue
        entity, relation, target = (
            str(raw.get(key, "")).strip() for key in ("entity", "relation", "target")
        )
        start, end = (
            _clamp_index(raw.get("evidence_start_index"), message_count),
            _clamp_index(raw.get("evidence_end_index"), message_count),
        )
        if not entity or not relation or not target or end <= start:
            continue
        try:
            confidence = max(0.0, min(float(raw.get("confidence", 0.0)), 1.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence <= 0:
            continue
        normalized["claims"].append(
            {
                "entity": entity[:120],
                "relation": relation[:120],
                "target": target[:500],
                "confidence": confidence,
                "evidence_start_index": start,
                "evidence_end_index": end,
            }
        )
    return normalized


def build_extraction_prompt(messages: list[dict[str, Any]]) -> tuple[str, str]:
    conversation = "\n".join(
        f"[{index}] {message.get('role', 'unknown')}: {_content_text(message)[:1200]}"
        for index, message in enumerate(messages)
    )
    return (
        _EXTRACTION_SYSTEM_PROMPT,
        "Conversation batch:\n\n" + conversation + "\n\nReturn the JSON object now.",
    )


async def extract_batch_async(
    messages: list[dict[str, Any]],
    profile: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    system_prompt, user_prompt = build_extraction_prompt(messages)
    response = await memory_llm_call(
        await get_ai_manager(),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        timeout=90,
        response_format=_EXTRACTION_SCHEMA,
        profile=profile,
    )
    if response is None:
        raise RuntimeError("Memory LLM call failed (returned None)")

    return normalize_extraction(_parse_extraction_response(response), len(messages))
