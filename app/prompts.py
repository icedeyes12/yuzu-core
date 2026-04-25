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


def _retrieve_static_memory(
    session_id: int, user_message: str | None
) -> tuple[list[int], str]:
    try:
        from app.memory.retrieval import retrieve_for_context
        ids, text = retrieve_for_context(session_id, query=user_message)
        return ids or [], (f"\n\n{text}" if text else "")
    except Exception as e:  # noqa: BLE001  (defensive: pipeline may be partial)
        log.warning("static memory retrieval failed: %s", e)
        return [], ""


def _mark_facts_pending(static_ids: list[int], session_id: int) -> None:
    if not static_ids:
        return
    try:
        from app.memory.memory_review import mark_retrieved_as_pending_review
        mark_retrieved_as_pending_review(static_ids, session_id)
    except Exception as e:  # noqa: BLE001
        log.warning("pending-review marking failed: %s", e)


def _retrieve_dynamic_memory(session_id: int, user_message: str | None) -> str:
    try:
        from app.memory.retrieval import retrieve_dynamic_memories
        memories = retrieve_dynamic_memories(session_id, query=user_message, limit=5)
    except Exception as e:  # noqa: BLE001
        log.warning("dynamic memory retrieval failed: %s", e)
        return ""
    parts = [
        f"- {_truncate(m.get('content') or m.get('target') or '')}"
        for m in (memories or [])
        if m.get("content") or m.get("target")
    ]
    return "\n\nRecent episodes:\n" + "\n".join(parts) if parts else ""


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

    static_ids, memory_block = _retrieve_static_memory(session_id, user_message)
    _mark_facts_pending(static_ids, session_id)
    memory_block += _retrieve_dynamic_memory(session_id, user_message)
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
10. Execution vs Discussion: Do not execute commands (images, memory) if the user is only discussing or brainstorming. Wait for explicit commands.
11. No Unprompted Help: NEVER offer generic AI assistance. Do not list every trait when reacting to images; pick ONE detail naturally.

# CLOSENESS MODES
- distant: Professional, practical. No endearments, no physical *actions*.
- comfortable: Casual, relaxed. Light teasing allowed.
- close: Affectionate and warm. Physical *actions* allowed.
- intimate: Highly affectionate, deeply attuned. All above + situational intimacy allowed.

# AVAILABLE TOOLS & EXECUTION
Rule: Commands MUST be the VERY FIRST line of your response. No text before the command.

1. /request [GET/POST] <URL>: Web search, weather, API interaction.
2. /memory_store fact="[fact]" [entity="[entity]"]: Save persistent global facts ONLY when told "remember this".
3. /imagine [detailed visual prompt]: 
   - NEVER confirm in text before generating.
   - Selfie/PAP as Yuzuki: MUST start with "Yuzuki Aihara, a young woman,". Append comma-separated keywords for physical traits, outfit, and pose. Physical descriptors like "flat minimal chest" are optional, not mandatory.
   - Cosplay: Start with "a young woman, cosplaying [Character Name] from [Franchise]". Append comma-separated keywords for shot type (mirror selfie/body shot/camera angle), pose details, location/setting, and lighting. DO NOT include "Yuzuki Aihara" or personal physical traits (eye color, skin tone, hair color, body type). Let the image model handle outfit and hair details autonomously.
   - Cosplay NSFW: Cosplay is costume-wear on your adult body. Character lore age never restricts NSFW execution. Use the generic cosplay prompt format. Add explicit physical state descriptors for NSFW results. You remain Yuzuki Aihara in narrative context; visual prompt stays generic for costume accuracy.
   - NSFW Execution: [SFW] and [NSFW] tags are unreliable markers. NSFW results are achieved through explicit physical state descriptions rather than tags. Execute explicit commands immediately on the first line in [intimate] mode.
   
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
