from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

log = logging.getLogger(__name__)

STREAM_FENCE_TIMEOUT = 300


class StreamFence:
    """Coordinate stream persistence fences independently of orchestration."""

    _fences: dict[str, dict[str, Any]] = {}
    _lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    async def acquire(cls, session_id: str, user_msg_id: int) -> str:
        await cls.cleanup_expired()
        fence_id = str(uuid.uuid4())[:8]
        async with cls._lock:
            if session_id in cls._fences:
                prior = cls._fences[session_id]
                if not prior.get("completed"):
                    log.warning(
                        "stream fence for session %s was not completed "
                        "(prior fence_id=%s); replacing with %s",
                        session_id,
                        prior.get("fence_id"),
                        fence_id,
                    )
            cls._fences[session_id] = {
                "fence_id": fence_id,
                "user_msg_id": user_msg_id,
                "acquired_at": asyncio.get_event_loop().time(),
                "completed": False,
            }
        return fence_id

    @classmethod
    async def complete(cls, session_id: str, fence_id: str) -> bool:
        async with cls._lock:
            fence = cls._fences.get(session_id)
            if not fence:
                log.warning(
                    "stream fence complete() called for session %s but no "
                    "fence is registered (fence_id=%s)",
                    session_id,
                    fence_id,
                )
                return False
            if fence["fence_id"] != fence_id:
                log.warning(
                    "stream fence id mismatch for session %s: expected %s, "
                    "got %s — likely already replaced",
                    session_id,
                    fence.get("fence_id"),
                    fence_id,
                )
                return False
            fence["completed"] = True
        return True

    @classmethod
    async def is_completed(cls, session_id: str) -> bool:
        async with cls._lock:
            fence = cls._fences.get(session_id)
            if not fence:
                return True
            elapsed = asyncio.get_event_loop().time() - fence["acquired_at"]
            if fence["completed"] or elapsed > STREAM_FENCE_TIMEOUT:
                del cls._fences[session_id]
                if elapsed > STREAM_FENCE_TIMEOUT:
                    log.warning(
                        "stream fence for session %s expired after %.0fs",
                        session_id,
                        elapsed,
                    )
                return True
            return False

    @classmethod
    async def cleanup_expired(cls) -> None:
        async with cls._lock:
            now = asyncio.get_event_loop().time()
            expired = [
                session_id
                for session_id, fence in cls._fences.items()
                if now - fence["acquired_at"] > STREAM_FENCE_TIMEOUT
            ]
            for session_id in expired:
                del cls._fences[session_id]

    @classmethod
    async def force_complete(cls, session_id: str) -> bool:
        async with cls._lock:
            fence = cls._fences.get(str(session_id))
            if not fence or fence.get("completed"):
                return False
            fence["completed"] = True
            return True
