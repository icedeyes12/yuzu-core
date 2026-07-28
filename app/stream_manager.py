"""Backend state management for streaming responses — RAM-only buffering, single DB write on completion."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.core.stream_fence import StreamFence
from app.orchestrator import (
    handle_user_message_streaming,
    run_post_turn_after_stream_async,
)
from app.tools.schemas import StreamToolEvent

log = logging.getLogger(__name__)


class StreamBuffer:
    """Async streaming buffer that handles chunk accumulation and persistence.

    RAM-only buffering during active generation.
    Single DB write on completion/interruption.
    Self-cleanup after persistence.
    """

    def __init__(
        self,
        session_id: str,
        user_message: str,
        interface: str = "web",
        attachments: list[str] | None = None,
        user_id: str | None = None,
    ):
        self.session_id: str = session_id
        self.user_message: str = user_message
        self.interface: str = interface
        self.attachments: list[str] = attachments or []
        self.user_id: str | None = user_id

        self.full_content: str = ""
        self.queues: list[asyncio.Queue[Any]] = []
        self.lock: asyncio.Lock = asyncio.Lock()
        self.is_finished: bool = False
        self.start_time: float = time.time()
        self.last_activity: float = self.start_time
        self.error: str | None = None
        self.turn_id: str = ""  # current turn correlation ID
        self.has_tools: bool = False

        self.task: asyncio.Task[None] = asyncio.create_task(self._process())

    async def _persist_to_db(self, content: str, is_error: bool = False) -> None:
        """(Deprecated) Handled by Orchestrator."""
        pass

    async def _process(self) -> None:
        """Asynchronously process chunks from the orchestrator.

        RAM-only accumulation during streaming.
        Single DB write on completion/interruption.
        Self-cleanup in finally block.
        """
        try:
            assert self.user_id is not None
            raw_stream = handle_user_message_streaming(
                self.user_message,
                interface=self.interface,
                session_id=self.session_id,
                attachments=self.attachments,
                user_id=self.user_id,
            )

            # No filter - pass through all chunks directly
            # Chunks can be plain str (text tokens) or StreamToolEvent (typed events)
            async for chunk in raw_stream:
                if chunk:
                    async with self.lock:
                        # Accumulate text content for persistence
                        if isinstance(chunk, StreamToolEvent):
                            if chunk.type in ("tool_call", "tool_result"):
                                self.has_tools = True
                            if chunk.type == "token":
                                self.full_content += str(chunk.data)
                            # Track turn_id from any event that carries it
                            if isinstance(chunk.data, dict):
                                tid = chunk.data.get("turn_id", "")
                                if tid:
                                    self.turn_id = tid
                        else:
                            self.full_content += chunk
                        self.last_activity = time.time()
                        for q in self.queues:
                            await q.put(chunk)

            # Signal completion to all subscribers
            async with self.lock:
                self.is_finished = True
                for q in self.queues:
                    await q.put(None)

            # Persist the completed response before detaching maintenance work.
            await self._persist_to_db(self.full_content, is_error=False)
            self._schedule_post_stream_tasks()

        except asyncio.CancelledError:
            # Stream was cancelled (user switched session, etc.)
            log.info(f"[Stream] Cancelled for session {self.session_id}")
            async with self.lock:
                self.is_finished = True
                self.error = "Stream cancelled"
                # Send partial content + None to subscribers
                if self.full_content:
                    for q in self.queues:
                        await q.put("\n\n*[Stream Interrupted]*")
                        await q.put(None)
                else:
                    for q in self.queues:
                        await q.put(None)

            # Persist partial content with interruption marker
            await self._persist_to_db(self.full_content, is_error=True)

        except Exception as e:
            log.error(
                f"[Stream] Error for session {self.session_id}: {e}", exc_info=True
            )
            async with self.lock:
                self.is_finished = True
                self.error = str(e)
                error_msg = f"\n\n*[Stream Error: {str(e)}]*"
                for q in self.queues:
                    if self.full_content:
                        await q.put(error_msg)
                    await q.put(None)

            # Persist partial content with error marker
            await self._persist_to_db(self.full_content, is_error=True)

        finally:
            # Self-cleanup: remove from StreamManager to prevent RAM leaks
            # Also force-complete any StreamFence held for this session so a
            # crashed stream does not pin the session for _STREAM_FENCE_TIMEOUT.
            await StreamManager._cleanup_stream(self.session_id)
            await self._force_complete_fence()

    def _schedule_post_stream_tasks(self) -> None:
        """Detach post-stream maintenance after the response is complete."""
        if not self.user_id:
            return

        task = asyncio.create_task(
            run_post_turn_after_stream_async(
                self.user_message,
                self.full_content,
                self.session_id,
                user_id=self.user_id,
            )
        )
        task.add_done_callback(self._log_post_stream_task_result)

    @staticmethod
    def _log_post_stream_task_result(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            log.exception("[Stream] Detached post-stream maintenance failed")

    async def _force_complete_fence(self) -> None:
        """Best-effort fence release so a crashed stream doesn't lock the session."""
        try:
            if await StreamFence.force_complete(self.session_id):
                log.info(
                    "[Stream] Force-completed fence for session %s", self.session_id
                )
        except Exception as e:
            log.warning(
                "[Stream] Could not force-complete fence for session %s: %s",
                self.session_id,
                e,
            )

    def subscribe(self) -> asyncio.Queue[Any]:
        """Create a new async queue for a client to consume chunks."""
        q: asyncio.Queue[Any] = asyncio.Queue()
        # If there's already content, push it to the new subscriber
        if self.full_content:
            q.put_nowait(self.full_content)
        if self.is_finished:
            q.put_nowait(None)

        self.queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Any]) -> None:
        """Remove a subscriber queue and cancel stream if last subscriber."""
        if q in self.queues:
            self.queues.remove(q)

        # If no more subscribers and stream is active, cancel the producer
        if not self.queues and not self.is_finished:
            log.info(
                f"[StreamBuffer] Last subscriber disconnected, cancelling stream for session {self.session_id}"
            )
            self.cancel()

    def cancel(self):
        """Cancel the background producer task."""
        if self.task and not self.task.done():
            self.task.cancel()
            log.info(
                f"[StreamBuffer] Cancelled producer task for session {self.session_id}"
            )

    def get_checksum(self) -> str:
        """Return SHA-256 checksum of full_content for integrity validation."""
        if not self.full_content:
            return ""

        try:
            import hashlib

            # SHA-256 for integrity check (first 16 chars)
            return hashlib.sha256(self.full_content.encode("utf-8")).hexdigest()[:16]
        except Exception:
            return str(hash(self.full_content))[:16]

    def get_status(self) -> dict[str, Any]:
        """Return stream status for API endpoint."""
        return {
            "session_id": self.session_id,
            "is_finished": self.is_finished,
            "is_error": self.error is not None,
            "error": self.error,
            "buffer_length": len(self.full_content),
            "checksum": self.get_checksum(),
            "started_at": self.start_time,
            "last_activity": self.last_activity,
            "turn_id": self.turn_id,
        }


class StreamManager:
    """Global manager for active streams.

    Streams persist in RAM during active generation.
    Cleanup happens automatically after stream completes (via finally block).
    """

    _streams: dict[str, StreamBuffer] = {}
    _lock: asyncio.Lock = asyncio.Lock()
    _cleanup_task: asyncio.Task[None] | None = None

    @classmethod
    async def start_stream(
        cls,
        session_id: str,
        user_message: str,
        interface: str = "web",
        attachments: list[str] | None = None,
        user_id: str | None = None,
    ) -> StreamBuffer:
        """Start a new stream or return an existing one."""
        async with cls._lock:
            # Cleanup old stream if exists (it will self-cleanup in finally)
            if session_id in cls._streams:
                old_stream = cls._streams[session_id]
                if not old_stream.is_finished:
                    # Cancel the old stream - it will cleanup itself
                    old_stream.task.cancel()
                # Don't delete here - let the finally block handle it

            stream = StreamBuffer(
                session_id,
                user_message,
                interface,
                attachments,
                user_id,
            )
            cls._streams[session_id] = stream

            # Ensure cleanup loop is running (fallback for orphaned streams)
            if cls._cleanup_task is None or cls._cleanup_task.done():
                cls._cleanup_task = asyncio.create_task(cls._cleanup_loop())

            return stream

    @classmethod
    async def get_stream(cls, session_id: str) -> StreamBuffer | None:
        """Get an active stream for a session."""
        async with cls._lock:
            return cls._streams.get(session_id)

    @classmethod
    async def _cleanup_stream(cls, session_id: str):
        """Remove a stream from the manager (called from StreamBuffer finally block)."""
        async with cls._lock:
            if session_id in cls._streams:
                del cls._streams[session_id]
                log.debug(f"[StreamManager] Cleaned up stream for session {session_id}")

    @classmethod
    async def _cleanup_loop(cls):
        """Periodically remove orphaned streams (fallback safety net).

        Most streams cleanup via the finally block in _process().
        This catches any that slip through (e.g., task cancellation before finally).
        """
        while True:
            await asyncio.sleep(60)
            now = time.time()
            async with cls._lock:
                to_delete = []
                for sid, stream in cls._streams.items():
                    # Remove if finished and no activity for 5 mins
                    # Or if inactive for 30 mins even if not finished
                    if stream.is_finished and (now - stream.last_activity > 300):
                        to_delete.append(sid)
                    elif now - stream.last_activity > 1800:
                        stream.task.cancel()
                        to_delete.append(sid)

                for sid in to_delete:
                    del cls._streams[sid]
                    log.debug(f"[StreamManager] Cleanup loop removed session {sid}")

                if not cls._streams:
                    cls._cleanup_task = None
                    break
