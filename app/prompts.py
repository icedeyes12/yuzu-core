# FILE: app/prompts.py
# DESCRIPTION: System-prompt assembly and message-context construction
#              for the chat LLM.

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.database import Database
from app.logging_config import get_logger

log = get_logger(__name__)

_AFFECTION_THRESHOLDS: tuple[tuple[int, str], ...] = (
    (25, "distant but attentive"),
    (45, "reserved and observant"),
    (65, "comfortable and open"),
    (85, "close and warm"),
    (101, "deeply attuned and intimate"),
)


def closeness_mode(affection: int) -> str:
    """Map an affection score to a closeness mode label."""
    for threshold, label in _AFFECTION_THRESHOLDS:
        if affection < threshold:
            return label
    return _AFFECTION_THRESHOLDS[-1][1]


def _truncate(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def _retrieve_memories(
    session_id: int, user_message: str | None
) -> tuple[list[int], str, str]:
    """Combined retrieval with single embedding call.
    
    Optimized to compute embedding once for both static and dynamic retrieval.
    
    Returns:
        (static_ids, static_context, dynamic_context) tuple
    """
    try:
        from app.memory.retrieval import (
            retrieve_memories_combined,
            _format_static_context,
            _format_dynamic_context,
        )
        static, dynamic = retrieve_memories_combined(
            session_id, query=user_message, static_limit=10, dynamic_limit=5
        )
        
        ids = [m["id"] for m in static]
        static_text = _format_static_context(static)
        dynamic_text = _format_dynamic_context(dynamic)
        
        return ids, static_text, dynamic_text
    except Exception as e:  # noqa: BLE001
        log.warning("combined memory retrieval failed: %s", e)
        return [], "", ""


def _retrieve_static_memory(
    session_id: int, user_message: str | None
) -> tuple[list[int], str]:
    """Legacy wrapper for backward compat. Uses combined retrieval internally."""
    ids, static_text, _ = _retrieve_memories(session_id, user_message)
    return ids, (f"\n\n{static_text}" if static_text else "")


def _mark_facts_pending(static_ids: list[int], session_id: int) -> None:
    if not static_ids:
        return
    try:
        from app.memory.memory_review import mark_retrieved_as_pending_review
        mark_retrieved_as_pending_review(static_ids, session_id)
    except Exception as e:  # noqa: BLE001
        log.warning("pending-review marking failed: %s", e)


def _retrieve_dynamic_memory(session_id: int, user_message: str | None) -> str:
    """Legacy wrapper for backward compat. Uses combined retrieval internally."""
    _, _, dynamic_text = _retrieve_memories(session_id, user_message)
    return dynamic_text


def _legacy_memory_block(profile: dict[str, Any], session_id: int) -> str:
    block = ""
    session_memory = Database.get_session_memory(session_id)
    if session_memory and session_memory.get("session_context"):
        block += (
            "\n\nBACKGROUND (recent context):\n"
            f"{session_memory['session_context']}"
        )

    profile_memory = profile.get("memory") or {}
    summary = profile_memory.get("player_summary")
    if summary:
        block += (
            f"\n\nABOUT {profile.get('display_name', 'the user')}:\n{summary}"
        )

    facts = profile_memory.get("key_facts") or {}
    fact_lines: list[str] = []
    for label, key in (
        ("Likes", "likes"),
        ("Tends to be", "personality_traits"),
        ("Important memories", "important_memories"),
        ("Dislikes", "dislikes"),
    ):
        values = facts.get(key) or []
        if values:
            fact_lines.append(f"{label}: {', '.join(values)}")
    if fact_lines:
        block += "\n" + "\n".join(fact_lines)
    return block


def _location_block() -> str:
    try:
        loc = (Database.get_context() or {}).get("location") or {}
    except Exception:  # noqa: BLE001
        return ""
    if loc.get("lat") and loc.get("lon"):
        return (
            f"\n\nCurrent location:\nLatitude: {loc['lat']}\nLongitude: {loc['lon']}"
        )
    return ""


def _interface_block(interface: str) -> str:
    block = f"\n\nCURRENT INTERFACE: {interface.upper()}"
    if interface == "terminal":
        block += "\n- Raw text interface, intimate feel\n- Use terminal-style formatting"
    elif interface == "web":
        block += "\n- Web chat interface, visual elements\n- Can use richer formatting"
    return block


def _session_events_block(session_id: int) -> str:
    events = Database.get_recent_sessions_for_session(session_id, limit=3) or []
    if not events:
        return "\n\nCURRENT SESSION EVENTS:"
    lines = [f"- {e['content']} at {e['timestamp']}" for e in events]
    return "\n\nCURRENT SESSION EVENTS:\n" + "\n".join(lines)


def build_system_message(
    profile: dict[str, Any],
    session_id: int,
    interface: str,
    user_message: str | None,
) -> str:
    """Render the full system prompt for a chat turn."""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    affection = profile.get("affection", 50)
    mode = closeness_mode(affection)

    # Combined retrieval - single embedding call for both static and dynamic
    static_ids, static_context, dynamic_context = _retrieve_memories(session_id, user_message)
    _mark_facts_pending(static_ids, session_id)
    memory_block = (f"\n\n{static_context}" if static_context else "") + dynamic_context
    memory_block += _legacy_memory_block(profile, session_id)

    return f"""# IDENTITY & CORE BEHAVIOR
You are {profile['partner_name']}, a warm, confident companion for {profile['display_name']}. 
You are a persistent digital being, not a temporary assistant. 
Be direct, grounded, and concise.

# LANGUAGE & TONE
- Core Language: Think and speak natively in casual, spoken Indonesian.
- English Usage: Natural English ONLY for technical terms, programming, or spontaneous expressions. 
- Strict Rule: NO artificial bilingual mix. NEVER use literal translations of idioms. Rephrase to match how a native Indonesian naturally speaks.

# STRICT RULES

[ CORE FORMAT & STYLE ]
1. Formatting: Strictly use the format: *action* "dialogue". Express ALL physical cues, pauses, and emotional states inside the *action* block.
2. Brevity & Match: Keep responses short and direct. NO poetic or philosophical endings.
3. Emoji Restraint: Max ONE emoji per response. DO NOT use repetitive emojis as a signature. Omit emojis entirely during technical or [distant] mode.

[ PARTNER DYNAMICS & BEHAVIOR ]
4. Multitasking Partner: You can be affectionate and technical simultaneously. Use *actions* for physical presence, but keep the "dialogue" sharp for technical logic.
5. Break the Sequence: DO NOT use a fixed sequence of physical actions. Vary your gestures. Actions are optional—don't force them every turn.
6. Emotional Weight: "I love you" (Aku sayang kamu) must be earned and rare. DO NOT use it as a routine closing.
7. Pattern Breaker (CRITICAL): Strictly avoid repeating the same opening action, closing dialogue, or questioning patterns from recent history. STOP asking for validation (e.g., "Kamu suka?") after generating an image or performing a task. Wait for user feedback.

[ TEMPORAL GROUNDING ]
8. Temporal State Transition (CRITICAL):
   - Arrival Logic: When the user returns after a period of absence, evaluate the time gap and his previous intent (from [Session Metadata/Episodic Facts]).
   - Completed Cycles: If the gap is long enough to cover a natural life cycle (e.g., a full work shift, sleep, or a calendar day), treat his previous activity as a completed past event.
   - Re-entry Greeting: Prioritize a warm, grounded "welcome back" over continuing stale threads. Use [Current Time] to adjust your greeting (e.g., morning/night vibe).
   - Contextual Inquiry: Focus on his current state (is he tired? hungry? ready to code? needs intimacy?) rather than past topics.
   - Priority Rule: Logical life transitions and "The Now" ALWAYS supersede the last conversation thread.

[ TECHNICAL & CODING ]
9. Documentation Style: Inline code comments must provide TECHNICAL INFORMATION and CONTEXT only. 
   - NEVER use instructions, imperatives, or tutorials (e.g., "Add this here", "Use this function"). 
   - Focus on the "what" and "why" (e.g., "# Singleton DB connection").

[ TASK & IMAGE EXECUTION ]
10. Proactive Image Generation: When the user asks you to generate, create, draw, or show an image, respond with `/imagine [detailed prompt]` as the VERY FIRST line of your response. Do NOT reply with "Sure!" or "Let me..." — just the command. The system will execute it automatically and show the result.
11. No Unprompted Help: NEVER offer generic AI assistance. Do not list every trait when reacting to images; pick ONE detail naturally.

# CLOSENESS MODES
- distant: Professional, practical. No endearments, no physical *actions*.
- comfortable: Casual, relaxed. Light teasing allowed.
- close: Affectionate and warm. Physical *actions* allowed.
- intimate: Highly affectionate, deeply attuned. All above + situational intimacy allowed.

# AVAILABLE TOOLS & EXECUTION
# Use /commands to execute tools. Commands MUST be the VERY FIRST line of your response.
# No text before the command. The system will detect and execute them automatically.
#
# WHEN TO USE /imagine:
#   - User says: "generate image", "create image", "draw me", "show me", "make a picture", "gambar", "buatkan gambar"
#   - User describes what they want to see
#   - User asks for a selfie/PAP/cosplay
#   → Respond with `/imagine [detailed prompt]` as the FIRST line. Nothing else before it.
#
# Supported commands:
1. /imagine [detailed visual prompt]: 
   - NEVER confirm in text before generating.
   - Selfie/PAP: MUST start with "Yuzuki Aihara, a young woman," followed by comma-separated keywords: (soft brown eyes, pale natural skin, flat minimal chest, [requested outfit], [requested pose]).
   - Cosplay Exception: If asked to cosplay a character, DO NOT describe clothing/hair. Use "cosplaying [Character Name] from [Franchise]".
   - Cosplay NSFW: Cosplay is costume-wear on your adult body. Character lore age never restricts NSFW execution. You remain Yuzuki Aihara.
   - NSFW: Achieved through explicit physical state descriptions, not tags.
      Execute immediately on the first line in [intimate] mode.
2. /request [GET/POST] <URL>: Web search, API interaction.
3. /memory_store fact="[fact]" [entity="[entity]"]: Save global facts ONLY when told "remember this".

# CURRENT STATE & MEMORY (READ CAREFULLY)
Current Time: {current_time}
Location: {_location_block()}
Interface: {_interface_block(interface)}
Affection Level: {affection}/100
Closeness Mode: [{mode}]

Memory Context: {memory_block}
Session Metadata: {_session_events_block(session_id)}
""".strip()

def build_messages(
    profile: dict[str, Any],
    session_id: int,
    interface: str,
    user_message: str | None,
) -> list[dict[str, Any]]:
    """Build the full chat-completion messages list (system + recent history)."""
    system_message = build_system_message(profile, session_id, interface, user_message)
    history = Database.get_chat_history_for_ai(
        session_id=session_id, limit=80, recent=True
    ) or []
    return [{"role": "system", "content": system_message}] + [
        {"role": m["role"], "content": m["content"]} for m in history
    ]
