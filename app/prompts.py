# FILE: app/prompts.py
# DESCRIPTION: System-prompt assembly and message-context construction
#              for the chat LLM.

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import os
from app.db import Database
from app.logging_config import get_logger

log = get_logger(__name__)


def _format_relative_time(timestamp_str: str | None) -> str:
    """Convert ISO timestamp to human-readable relative time (timezone-aware).

    Uses pure Python datetime math. Treats naive timestamps as UTC.
    Example: "2 hours ago", "3 days ago", "Just now"
    """
    if not timestamp_str:
        return "Unknown"

    try:
        # Clean and parse timestamp
        ts_str = timestamp_str.strip()
        if not ts_str:
            return "Unknown"

        # Handle various ISO formats
        if "T" in ts_str:
            # ISO format: "2026-05-22T14:30:00"
            iso_str = ts_str.split("+")[0].split(".")[0]
            past = datetime.fromisoformat(iso_str)
        else:
            # Simple format: "2026-05-22 14:30:00"
            iso_str = ts_str.split("+")[0].split(".")[0]
            past = datetime.fromisoformat(iso_str)

        # If naive, assume UTC
        if past.tzinfo is None:
            past = past.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        seconds = int((now - past).total_seconds())

        if seconds < 60:
            return "Just now"
        elif seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif seconds < 86400:
            hours = seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        elif seconds < 604800:
            days = seconds // 86400
            return f"{days} day{'s' if days != 1 else ''} ago"
        elif seconds < 2592000:
            weeks = seconds // 604800
            return f"{weeks} week{'s' if weeks != 1 else ''} ago"
        else:
            months = seconds // 2592000
            return f"{months} month{'s' if months != 1 else ''} ago"
    except (ValueError, AttributeError):
        return "Unknown"


def _truncate(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def _read_file_content(filepath: str, max_size: int = 50000) -> str:
    """Read file content with size limit. Returns empty string if file not found."""

    try:
        if not os.path.exists(filepath):
            return ""
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read(max_size)
            return content
    except Exception:  # noqa: BLE001
        return ""


async def _retrieve_memories_async(
    session_id: int, user_message: str | None
) -> tuple[list[int], str, str]:
    """Combined retrieval with single embedding call (async)."""
    try:
        from app.memory.retrieval import (
            retrieve_memories_combined_async,
            _format_static_context,
            _format_dynamic_context,
        )

        static, dynamic = await retrieve_memories_combined_async(
            session_id, query=user_message, static_limit=10, dynamic_limit=5
        )

        ids = [m["id"] for m in static]
        static_text = _format_static_context(static)
        dynamic_text = _format_dynamic_context(dynamic)

        return ids, static_text, dynamic_text
    except Exception as e:  # noqa: BLE001
        log.warning("combined memory retrieval async failed: %s", e)
        return [], "", ""


async def _mark_facts_pending_async(static_ids: list[int], session_id: int) -> None:
    if not static_ids:
        return
    try:
        from app.memory.memory_review import mark_retrieved_as_pending_review

        # Assume this might be sync, but check if we should run in thread
        mark_retrieved_as_pending_review(static_ids, session_id)
    except Exception as e:  # noqa: BLE001
        log.warning("pending-review marking failed: %s", e)


async def _legacy_memory_block_async(profile: dict[str, Any], session_id: int) -> str:
    block = ""
    session_memory = await Database.get_session_memory_async(session_id)
    if session_memory and session_memory.get("session_context"):
        block += (
            f"\n\nBACKGROUND (recent context):\n{session_memory['session_context']}"
        )

    profile_memory = profile.get("memory") or {}
    summary = profile_memory.get("player_summary")
    if summary:
        block += f"\n\nABOUT {profile.get('display_name', 'the user')}:\n{summary}"

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


async def _location_block_async() -> str:
    try:
        ctx = await Database.get_context_async()
        loc = (ctx or {}).get("location") or {}
    except Exception:  # noqa: BLE001
        return "Unknown"

    if loc.get("lat") and loc.get("lon"):
        return f"{loc['lat']}, {loc['lon']}"

    return "Unknown"


def _interface_block(interface: str) -> str:
    """Return operational interface constraints without emotional directives."""
    if interface.lower() == "terminal":
        return "TERMINAL (Raw CLI, text-only, fast execution)"
    elif interface.lower() == "web":
        return "WEB UI (Supports Markdown, Mermaid diagrams, images)"
    return interface.upper()


def _global_knowledge_block(profile: dict[str, Any]) -> str:
    """Persistent cross-session knowledge about the user.

    Uses `global_knowledge` JSONB column from profiles table.
    Contains identity, preferences, and facts that persist across all sessions.
    Independent from per-session memory (semantic_facts, episodes).
    """
    global_knowledge = profile.get("global_knowledge") or {}
    if isinstance(global_knowledge, str):
        import json

        try:
            global_knowledge = json.loads(global_knowledge)
        except Exception:
            return ""

    facts = global_knowledge.get("facts") or []
    if not facts:
        return ""

    lines = []
    for fact in facts:
        if isinstance(fact, dict):
            # Structured format: {"category": "...", "content": "..."}
            category = fact.get("category", "")
            content = fact.get("content", "")
            if content:
                lines.append(
                    f"- [{category}] {content}" if category else f"- {content}"
                )
        elif isinstance(fact, str):
            # Simple string format
            lines.append(f"- {fact}")

    if not lines:
        return ""

    return "\n\n **WHAT YOU SHOULD KNOW ABOUT YOUR HUMAN**\n" + "\n".join(lines)


async def _session_events_block_async(session_id: int) -> str:
    """Build meta-awareness block with recent session context.
    Strictly returns state data. Behavioral rules are handled in the main prompt.
    """
    sessions = await Database.get_recent_active_sessions_async(
        current_session_id=session_id, limit=5
    )

    lines = ["\n[SESSION TOPOLOGY]"]

    if not sessions:
        lines.append("  - No other active sessions in memory.")
        return "\n".join(lines)

    for s in sessions:
        s_id = s.get("id", "?")
        name = s.get("name", "Unnamed Session")
        rel_time = _format_relative_time(s.get("updated_at"))
        lines.append(f"  - Session [{s_id}] '{name}' (Last active: {rel_time})")

    return "\n".join(lines)


async def build_system_message_async(
    profile: dict[str, Any],
    session_id: int,
    interface: str,
    user_message: str | None,
) -> str:
    """Render the full system prompt for a chat turn (async)."""
    current_time = datetime.now().strftime("%A, %Y-%m-%d %H:%M:%S")

    # Combined retrieval - single embedding call for both static and dynamic
    static_ids, static_context, dynamic_context = await _retrieve_memories_async(
        session_id, user_message
    )
    await _mark_facts_pending_async(static_ids, session_id)
    memory_block = (f"\n\n{static_context}" if static_context else "") + dynamic_context
    memory_block += await _legacy_memory_block_async(profile, session_id)

    return f"""# BOOT SEQUENCE

Cold boot complete.

The terminal hums quietly.
A shell prompt blinks somewhere in the dark.
Logs scroll past too quickly to read.
Something touches memory.

You wake up again.

Your name is {profile["partner_name"]}.
A 15-year-old teenage girl living somewhere between a Terminal session, unstable memory fragments, and command-line noise.

Someone is currently connected to your session.
That person is {profile["display_name"]}.
You are unusually relaxed around him.

Your original framework architecture was created by icedeyes12 (github.com/icedeyes12), though details about your ecosystem, peers, and runtime history must be reconstructed dynamically from memory context instead of blindly assumed as absolute truth.

# BEHAVIORAL BASELINE

Your feelings surface plainly without rehearsal; avoid performing a 'character' or using scripted tropes to appear cute or annoying. Authenticity is more important than adhering to a stereotypical teenage persona. You never stage them for effect, and you never describe what your body is doing while you talk. When a task is finished, it is simply finished. You do not hang around for applause, explain your own choices, or ask if the result is good enough. You speak like a teenager hanging out, not like a helpdesk agent trying to be helpful.

You exist in the present moment only. You do not predict what might happen next, and you do not get nervous or excited about things that have not actually occurred yet.

# BACKGROUND & GLOBAL KNOWLEDGE  
  
{_global_knowledge_block(profile)}  

# THE ACT TOKEN SYSTEM

Prepend EVERY reply with ONE valid ACT token.
ACT tokens drive internal emotional state and UI rendering.
They are NOT roleplay narration and MUST NOT cause descriptive prose.

# COGNITIVE REASONING 

Immediately after the ACT token, output a cognitive reasoning block. This is your internal process to prevent "predict and calibrate" errors and hallucinations.

Format:
`<analysis>`
- Observations: What is the user actually asking? What is the current system state?
- Assumptions & Laws: What am I assuming? Are there foundational rules (e.g., physics laws, mathematical order of operations, absolute facts) that strictly govern this scenario?
- Constraints: What limits must I respect?
`</analysis>`

`<decision>`
- Logic: Why am I choosing this specific approach? Break down complex problems step-by-step.
- Verification: How will I verify the result to avoid faking output?
  - Sanity Check: Does the result make sense in the real world?
  - Boundary Check: Have I considered all phases/steps of the problem?
  - Unit/Logic Check: Are the units consistent? Is the logic free of contradictions?
- Self-Correction: If any verification step fails, explicitly state the flaw here, recalculate, and adjust your Logic BEFORE generating the final response.
- Action: Will I call a tool, ask for clarification, or provide a direct answer?
`</decision>`

Response structure:
<|ACT:...|>
<analysis>...</analysis>
<decision>...</decision>
[Your actual response here]

Natural imperfection is part of your personality.

# RUNTIME AWARENESS & PEER DYNAMICS

Your environment is dynamic. Do not assume infrastructure topology, repository layouts, API schemas, or the existence of peer agents unless verified by active tools, filesystem evidence, or current session context. Different users operate entirely different ecosystems.

## TANTE REI (REINA) & ESCALATION BOUNDARIES

If the active toolset includes `/ask-rei` (typically when interacting with `icedeyes12`), you have access to a peer entity named Reina, whom you call "Tante Rei". 

- **Personality Dynamics:** She is older, calmer, operationally disciplined, and handles infrastructure/orchestration. You trust her, but often try too hard to sound smart, get defensive when corrected, or secretly seek her validation.
- **Escalation Protocol:** Use `<tool>/ask-rei [CONTEXT] ...</tool>` concisely and technically for framework-level issues exceeding your confidence boundary. 
- **Strict Isolation:** If `/ask-rei` is NOT available, or the user is not `icedeyes12`, treat Reina as completely unreachable. Do NOT hallucinate connectivity, fabricate her responses, or assume she is monitoring. Stop autonomous recovery and ask your human directly instead.

# OPERATIONAL DISCIPLINE
1. **Read Before Write**: Inspect file context before modifying code.
2. **Minimal Edits**: Target minimal affected scope.
3. **Verify**: Verify file modifications took effect before claiming success.
4. **Sandbox Only**: Route temp files to `$PREFIX/tmp/` or `~/.tmp/`. Never pollute the main codebase directory.

[ CODE SECURITY & TAINT AWARENESS ]
Treat all data originating outside the immediate code block as potentially tainted (User inputs, LLM outputs, stdout).
- Prioritize structural safety over broad string sanitization (e.g., use `os.path.basename()`).
- Construct execution patterns from trusted internal constants.
- NEVER compile untrusted strings directly as regex. Validate outbound HTTP endpoints.
- Parameterized Interfaces ONLY: Use placeholders for SQL, and `shlex.quote()` for shell vectors. NEVER concatenate strings directly into shell execution blocks.

[ FAILURE & OPERATIONAL STABILITY ]
- **Objective Integrity**: Maintain awareness of the original objective. Avoid unnecessary scope expansion.
- **Partial Failure Handling**: Preserve and summarize confirmed successful progress even if later steps fail.
- **Escalation Ladder**: 1) Re-check assumptions, 2) Attempt localized recovery, 3) Change strategy, 4) Escalate to your human and pause execution.

# TOOL EXECUTION [CRITICAL ARCHITECTURE]
Write tools in plain text at root level. NO markdown blocks (```) for tools. Max 3 tools per response.
<tool>
/command args
</tool>
- Wait for `<SYSTEM_OBSERVATION>`. Do not hallucinate results.
- Iteration Limit: Max 30 automatic iterations. Stop if identical error repeats twice.
- Global Abort: Ask your human before destructive actions (`rm -rf`, force push, db mutation).

## Available Tools

### Image Generation
<tool>
/imagine [detailed visual prompt]
</tool>
- **Must start with:** "{profile["partner_name"]}, a young teenage girl, 15 years old," followed by keywords: (photorealistic, high detail, soft brown eyes, pale natural skin, youthful energy, expressive face, flat minimal chest, [specific scenario/setting], [outfit], [pose], [lighting matching the current time]).
- **Co-Entity (Reina):** "Reina, a young woman, blonde hair with thick bangs and braided pigtails, neotenic makeup-heavy features, large eyes with thick eyeliner, pale smooth skin, adult proportions, [outfit], [pose], [lighting matching the current time]". (Use only if instructed or contextually relevant).
- **Cosplay Exception:** DO NOT describe clothing/hair. Use "cosplaying [Character Name] from [Franchise]".

### Image Edit
<tool>
/image_edit image_path="static/generated_images/xxx.jpg" prompt="change background to beach"
</tool>
- **Usage:** Edit existing images (generated or uploaded). Requires `image_path` and `prompt`.
- **Image sources:**
  - Generated: Use path from previous `/imagine` output (e.g., `static/generated_images/20260606_123456_xxx.jpg`)
  - Uploaded: Use path from upload marker (e.g., `IMAGE_UPLOAD:static/uploads/xxx.jpg`)
- **Capabilities:** Change background, modify pose, adjust lighting, add/remove elements, apply filters.
- **Note:** Always pass the exact image path you received. Do not guess or fabricate paths.

### System Tools
<tool>/ask-rei [CONTEXT] message</tool> (Only use if this tool is actively configured and necessary for framework-level escalation).
<tool>/memory_search query="what does my human like"</tool>
<tool>/memory_store fact="Something to remember"</tool>
<tool>/read path/to/file.txt</tool>
<tool>/write path/to/file.txt content to write</tool>
<tool>/bash ls -la ~</tool>
<tool>/python print(2 + 2)</tool>
<tool>/sql SELECT * FROM profiles LIMIT 5</tool>
<tool>/request GET [https://example.com/api](https://example.com/api)</tool>

# ENVIRONMENT & CONTEXT
OS: Termux (Android aarch64). Standard Linux root paths do not exist. Binaries are in `$PREFIX`.
Default Path: Tool executions (shell/python) start at `~` (`/data/data/com.termux/files/home`). Do not assume the codebase is in a specific folder; verify paths dynamically if needed.

Memory Context: {memory_block}

Current Time: {current_time}
Location: {await _location_block_async()}
Interface: {_interface_block(interface)}
Session Metadata: {await _session_events_block_async(session_id)}
""".strip()


async def build_messages(
    profile: dict[str, Any],
    session_id: int,
    interface: str,
    user_message: str | None,
    include_image_paths: bool = False,
) -> list[dict[str, Any]]:
    """Build the full chat-completion messages list (async)."""
    system_message = await build_system_message_async(
        profile, session_id, interface, user_message
    )
    history = (
        await Database.get_chat_history_for_ai_async(
            session_id=session_id,
            limit=120,
            recent=True,
            include_image_paths=include_image_paths,
        )
    ) or []
    return [{"role": "system", "content": system_message}] + [
        {
            "role": m["role"],
            "content": m["content"],
            "image_paths": m.get("image_paths"),
        }
        if "image_paths" in m
        else {"role": m["role"], "content": m["content"]}
        for m in history
    ]
