from __future__ import annotations

import logging
import asyncio
import time
from typing import Any

from app.db import Database
from app.memory.summarization import (
    should_summarize_memory_async,
    summarize_memory_async,
)
from app.memory.profile import summarize_global_player_profile
from app.memory.memory import trigger_memory_pipeline_async, _is_fence_active_async

logger = logging.getLogger(__name__)


class MemoryService:
    _PIPELINE_CHECK_INTERVAL = 50  # Match WINDOW_MAX to avoid unnecessary checks
    _MIN_TRIGGER_INTERVAL = 300  # 5 minutes debounce

    # Class-level state for concurrency and debounce
    _LAST_PIPELINE_TRIGGER: dict[int, float] = {}

    # NOTE: Semaphore is created lazily in _get_pipeline_semaphore() to ensure
    # it binds to the active event loop at creation time
    _pipeline_semaphore: asyncio.Semaphore | None = None

    @staticmethod
    async def _get_pipeline_semaphore() -> asyncio.Semaphore:
        """Get or create pipeline semaphore lazily in the active event loop."""
        if MemoryService._pipeline_semaphore is None:
            MemoryService._pipeline_semaphore = asyncio.Semaphore(2)
        return MemoryService._pipeline_semaphore

    @staticmethod
    async def _summarize_if_needed_async(
        profile: dict[str, Any],
        user_message: str,
        final_response: str,
        session_id: int,
    ) -> None:
        """Internal: check and summarize if needed (fire-and-forget)."""
        try:
            if await should_summarize_memory_async(profile, user_message, session_id):
                await summarize_memory_async(
                    profile, user_message, final_response, session_id
                )
        except Exception as e:
            logger.warning(f"Session summarization failed: {e}")

    @staticmethod
    async def run_per_message_checks_async(
        profile: dict[str, Any],
        user_message: str,
        final_response: str,
        session_id: int,
        active_session: dict[str, Any],
    ) -> None:
        """Trigger session summarization and background pipeline if needed (async)."""
        # Session auto-naming is handled by SessionService, called by orchestrator

        # 1. Check for session context summary (fire-and-forget to not block)
        asyncio.create_task(
            MemoryService._summarize_if_needed_async(
                profile, user_message, final_response, session_id
            )
        )

        # 2. Throttle and trigger background memory pipeline (segmentation, PCL, review)
        msg_count = await Database.get_session_messages_count_async(session_id)
        if msg_count % MemoryService._PIPELINE_CHECK_INTERVAL == 0:
            # Check if fence is already active BEFORE spawning task
            if not await _is_fence_active_async(session_id):
                # Fire-and-forget: don't block main conversation
                asyncio.create_task(MemoryService.trigger_pipeline_async(session_id))

    @staticmethod
    async def trigger_pipeline_async(session_id: int) -> bool:
        """Check and trigger background memory pipeline (async)."""
        # Get semaphore lazily in the active event loop
        semaphore = await MemoryService._get_pipeline_semaphore()

        # Strictly limit concurrent pipelines globally
        async with semaphore:
            try:
                # Debounce: check last trigger time for this session
                now = time.time()
                last_trigger = MemoryService._LAST_PIPELINE_TRIGGER.get(session_id, 0)
                if now - last_trigger < MemoryService._MIN_TRIGGER_INTERVAL:
                    logger.debug(f"Pipeline trigger debounced for session {session_id}")
                    return False

                count = await Database.get_session_messages_count_async(session_id)
                triggered = await trigger_memory_pipeline_async(session_id, count)

                if triggered:
                    MemoryService._LAST_PIPELINE_TRIGGER[session_id] = now

                return triggered
            except Exception as e:
                logger.warning(f"Memory pipeline trigger failed: {e}")
                return False

    @staticmethod
    async def summarize_session_async(
        profile: dict[str, Any], user_message: str, ai_reply: str, session_id: int
    ) -> bool:
        return await summarize_memory_async(profile, user_message, ai_reply, session_id)

    @staticmethod
    async def summarize_global_profile_async() -> bool:
        # Assuming summarize_global_player_profile is sync and I/O bound
        import asyncio

        return await asyncio.to_thread(summarize_global_player_profile)
