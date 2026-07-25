from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.db import Database
from app.memory.memory import _is_fence_active_async, trigger_memory_pipeline_async

logger = logging.getLogger(__name__)


class MemoryService:
    _pipeline_semaphore: asyncio.Semaphore | None = None

    @staticmethod
    async def _get_pipeline_semaphore() -> asyncio.Semaphore:
        if MemoryService._pipeline_semaphore is None:
            MemoryService._pipeline_semaphore = asyncio.Semaphore(2)
        return MemoryService._pipeline_semaphore

    @staticmethod
    async def run_per_message_checks_async(
        profile: dict[str, Any],
        user_message: str,
        final_response: str,
        session_id: str,
        active_session: dict[str, Any],
        user_id: str | None = None,
    ) -> None:
        """(｡•̀ᴗ-)✧"""
        del profile, user_message, final_response, active_session
        if not user_id:
            return

        if await _is_fence_active_async(session_id, user_id=user_id):
            return
        asyncio.create_task(MemoryService.trigger_pipeline_async(session_id, user_id))

    @staticmethod
    async def trigger_pipeline_async(
        session_id: str, user_id: str | None = None
    ) -> bool:
        """(｡•̀ᴗ-)✧"""
        if not user_id:
            return False

        semaphore = await MemoryService._get_pipeline_semaphore()
        async with semaphore:
            try:
                count = await Database.get_session_messages_count(
                    session_id, user_id=user_id
                )
                triggered = await trigger_memory_pipeline_async(
                    session_id, count, user_id
                )
                return triggered
            except Exception as e:
                logger.warning("Memory pipeline trigger failed: %s", e)
                return False

    @staticmethod
    async def rebuild_structured_memory_async(
        session_id: str, user_id: str
    ) -> dict[str, Any]:
        """Run extraction and return graph-owned memory counts."""
        from app.db.connection import pg_fetchall_async
        from app.memory.memory import run_memory_pipeline_async

        count = await Database.get_session_messages_count(session_id, user_id=user_id)
        result = await run_memory_pipeline_async(session_id, count, user_id=user_id)
        rows = await pg_fetchall_async(
            """
            SELECT
                (SELECT COUNT(*) FROM memory_nodes WHERE user_id = %s AND status = 'active' AND valid_until IS NULL) AS nodes,
                (SELECT COUNT(*) FROM memory_edges WHERE user_id = %s AND valid_until IS NULL) AS edges,
                (SELECT COUNT(*) FROM memory_evidence WHERE user_id = %s) AS evidence,
                (SELECT COUNT(*) FROM episodes WHERE user_id = %s AND archived_at IS NULL) AS episodes
            """,
            (user_id, user_id, user_id, user_id),
        )
        stats = rows[0] if rows else {}
        return {
            "nodes": stats.get("nodes", 0),
            "edges": stats.get("edges", 0),
            "evidence": stats.get("evidence", 0),
            "episodes": stats.get("episodes", 0),
            "episodes_created": result.get("episodes", 0),
            "claims_processed": result.get("claims", 0),
            "llm_calls": result.get("llm_calls", 0),
        }
