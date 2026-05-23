from __future__ import annotations

import logging
from typing import Any

from app.db import Database
from app.memory.summarization import should_summarize_memory, summarize_memory
from app.memory.profile import summarize_global_player_profile
from app.memory.memory import trigger_memory_pipeline_async

logger = logging.getLogger(__name__)

class MemoryService:
    _PIPELINE_CHECK_INTERVAL = 5

    @staticmethod
    def run_per_message_checks(
        profile: dict[str, Any],
        user_message: str,
        final_response: str,
        session_id: int,
        active_session: dict[str, Any],
    ) -> None:
        """Trigger session summarization and background pipeline if needed."""
        # Session auto-naming is handled by SessionService, called by orchestrator
        
        # 1. Check for session context summary
        if should_summarize_memory(profile, user_message, session_id):
            summarize_memory(profile, user_message, final_response, session_id)

        # 2. Throttle and trigger background memory pipeline (segmentation, PCL, review)
        msg_count = Database.get_session_messages_count(session_id)
        if msg_count % MemoryService._PIPELINE_CHECK_INTERVAL == 0:
            MemoryService.trigger_pipeline(session_id)

    @staticmethod
    def trigger_pipeline(session_id: int) -> bool:
        """Check and trigger background memory pipeline."""
        try:
            count = Database.get_session_messages_count(session_id)
            return trigger_memory_pipeline_async(session_id, count)
        except Exception as e:
            logger.warning(f"Memory pipeline trigger failed: {e}")
            return False

    @staticmethod
    def summarize_session(profile: dict[str, Any], user_message: str, ai_reply: str, session_id: int) -> bool:
        return summarize_memory(profile, user_message, ai_reply, session_id)

    @staticmethod
    def summarize_global_profile() -> bool:
        return summarize_global_player_profile()
