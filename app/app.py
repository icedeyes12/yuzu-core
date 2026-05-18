# FILE: app/app.py
# DESCRIPTION: Backward-compatible re-export shim. The previous monolithic
#              implementation was split into focused modules in Stage 1
#              of the refactor:
#
#                - app.commands         /command parsing + image guards
#                - app.prompts          system prompt + message context
#                - app.llm_client       chat completion + chutes helper
#                - app.orchestrator     handle_user_message (+ streaming)
#                - app.session_lifecycle  start/end + auto-naming
#                - app.profile_analysis   memory + global profile analysis
#
# This shim preserves the public API previously exposed by app.app so
# main.py, web.py, and scripts/ continue to import from the old location.

from __future__ import annotations

from app.commands import detect_command as _detect_command
from app.database import Database
from app.llm_client import (
    generate_ai_response,
    generate_ai_response_streaming,
)
from app.orchestrator import (
    handle_user_message,
    handle_user_message_streaming,
)
from app.profile_analysis import (
    detect_important_content,
    merge_and_clean_memory,
    normalize_memory_item,
    parse_global_profile_summary,
    should_summarize_memory,
    summarize_global_player_profile,
    summarize_memory,
)
from app.providers import get_ai_manager, reload_ai_manager
from app.session_lifecycle import (
    UserContext,
    auto_name_session_if_needed,
    end_session_cleanup,
    start_session,
)


# ---------------------------------------------------------------------------
# Provider configuration helpers (kept here because they are tiny wrappers
# around the AI manager + Database that don't warrant their own module).
# ---------------------------------------------------------------------------


def get_available_providers() -> list[str]:
    return get_ai_manager().get_available_providers()


def get_all_models() -> dict[str, list[str]]:
    return get_ai_manager().get_all_models()


def get_provider_models(provider_name: str) -> list[str]:
    return get_ai_manager().get_provider_models(provider_name)


def set_preferred_provider(provider_name: str, model_name: str | None = None) -> str:
    profile = Database.get_profile()
    config = profile.get("providers_config") or {}
    config["preferred_provider"] = provider_name
    if model_name:
        config["preferred_model"] = model_name
    Database.update_profile({"providers_config": config})
    reload_ai_manager()

    suffix = f" with model: {model_name}" if model_name else ""
    return f"Preferred provider set to: {provider_name}{suffix}"


def set_vision_model(provider: str, model: str) -> str:
    profile = Database.get_profile()
    config = profile.get("providers_config") or {}
    config["vision_model_preferences"] = {"provider": provider, "model": model}
    Database.update_profile({"providers_config": config})
    return f"Vision model set to: {provider}/{model}"


def get_vision_capabilities() -> dict[str, object]:
    from app.tools import multimodal_tools

    capabilities: dict[str, object] = {
        "has_vision": False,
        "vision_provider": None,
        "vision_model": None,
        "has_image_generation": False,
        "image_generation_provider": None,
    }

    vision_provider, vision_model = multimodal_tools.get_best_vision_provider()
    if vision_provider:
        capabilities["has_vision"] = True
        capabilities["vision_provider"] = vision_provider
        capabilities["vision_model"] = vision_model

    if "openrouter" in (Database.get_api_keys() or {}):
        capabilities["has_image_generation"] = True
        capabilities["image_generation_provider"] = "openrouter"

    return capabilities


# ---------------------------------------------------------------------------
# Async helpers preserved verbatim for FastAPI routes.
# ---------------------------------------------------------------------------


async def retrieve_memory_context_async(
    session_id: int, user_message: str | None = None
) -> tuple[list[int], str]:
    """Async memory retrieval used by FastAPI routes."""
    try:
        from app.memory.retrieval import retrieve_for_context_async

        return await retrieve_for_context_async(session_id, query=user_message)
    except Exception:
        return [], ""


async def mark_pending_review_async(static_ids: list[int], session_id: int) -> None:
    """Async wrapper for marking facts as pending review."""
    if not static_ids:
        return
    import asyncio
    from app.memory.memory_review import mark_retrieved_as_pending_review

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, mark_retrieved_as_pending_review, static_ids, session_id
    )


__all__ = [
    # Orchestration
    "handle_user_message",
    "handle_user_message_streaming",
    # LLM client
    "generate_ai_response",
    "generate_ai_response_streaming",
    # Session lifecycle
    "start_session",
    "end_session_cleanup",
    "auto_name_session_if_needed",
    "UserContext",
    # Profile / memory
    "summarize_memory",
    "should_summarize_memory",
    "detect_important_content",
    "summarize_global_player_profile",
    "parse_global_profile_summary",
    "normalize_memory_item",
    "merge_and_clean_memory",
    # Provider config
    "get_available_providers",
    "get_all_models",
    "get_provider_models",
    "set_preferred_provider",
    "set_vision_model",
    "get_vision_capabilities",
    # Async helpers
    "retrieve_memory_context_async",
    "mark_pending_review_async",
    # Internal helpers retained for legacy imports
    "_detect_command",
]
