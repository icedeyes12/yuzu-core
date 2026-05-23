from __future__ import annotations

import logging
from typing import Any

from app.db import Database
from app.memory.summarization import (
    should_summarize_memory_async,
    summarize_memory_async,
)
from app.memory.profile import summarize_global_player_profile
from app.memory.memory import trigger_memory_pipeline_async

logger = logging.getLogger(__name__)


class MemoryService:
    _PIPELINE_CHECK_INTERVAL = 5

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

        # 1. Check for session context summary
        if await should_summarize_memory_async(profile, user_message, session_id):
            await summarize_memory_async(
                profile, user_message, final_response, session_id
            )

        # 2. Throttle and trigger background memory pipeline (segmentation, PCL, review)
        msg_count = await Database.get_session_messages_count_async(session_id)
        if msg_count % MemoryService._PIPELINE_CHECK_INTERVAL == 0:
            await MemoryService.trigger_pipeline_async(session_id)

    @staticmethod
    async def trigger_pipeline_async(session_id: int) -> bool:
        """Check and trigger background memory pipeline (async)."""
        try:
            count = await Database.get_session_messages_count_async(session_id)
            return await trigger_memory_pipeline_async(session_id, count)
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
