# FILE: app/stream_manager.py
# DESCRIPTION: Backend state management for streaming responses.
#              Allows clients to disconnect and reconnect to ongoing streams.
#              RAM-only buffering with single DB write on completion.

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List, Optional

from app.orchestrator import handle_user_message_streaming

log = logging.getLogger(__name__)


class StreamBuffer:
    """Async streaming buffer that handles chunk accumulation and persistence.

    RAM-only buffering during active generation.
    Single DB write on completion/interruption.
    Self-cleanup after persistence.
    """

    def __init__(
        self,
        session_id: int,
        user_message: str,
        interface: str = "web",
        provider: Optional[str] = None,
        model: Optional[str] = None,
        image_paths: Optional[List[str]] = None,
    ):
        self.session_id = session_id
        self.user_message = user_message
        self.interface = interface
        self.provider = provider
        self.model = model
        self.image_paths = image_paths or []

        self.full_content = ""
        self.queues: List[asyncio.Queue] = []
        self.lock = asyncio.Lock()
        self.is_finished = False
        self.start_time = time.time()
        self.last_activity = self.start_time
        self.error: Optional[str] = None

        # Start the background task
        self.task = asyncio.create_task(self._process())

    async def _persist_to_db(self, content: str, is_error: bool = False) -> None:
        """Persist the final assistant message to database.

        Single DB write after stream completes or is interrupted.
        Called from finally block to ensure cleanup.
        """
        if not content and not is_error:
            return

        try:
            from app.db import Database

            final_content = content
            if is_error and content:
                final_content = f"{content}\n\n*[Stream Interrupted/Error]*"

            # Single insert - no placeholder, direct final content
            await Database.add_message_async(
                "assistant",
                final_content,
                session_id=self.session_id,
            )
            log.info(
                f"[Stream] Persisted {len(final_content)} chars to DB for session {self.session_id}"
            )

        except Exception as e:
            log.error(f"[Stream] Failed to persist to DB: {e}", exc_info=True)

    async def _process(self):
        """Asynchronously process chunks from the orchestrator.

        RAM-only accumulation during streaming.
        Single DB write on completion/interruption.
        Self-cleanup in finally block.
        """
        try:
            async for chunk in handle_user_message_streaming(
                self.user_message,
                interface=self.interface,
                session_id=self.session_id,
                provider=self.provider,
                model=self.model,
                image_paths=self.image_paths,
            ):
                async with self.lock:
                    self.full_content += chunk
                    self.last_activity = time.time()
                    for q in self.queues:
                        await q.put(chunk)

            # Signal completion to all subscribers
            async with self.lock:
                self.is_finished = True
                for q in self.queues:
                    await q.put(None)

            # Persist successful completion
            await self._persist_to_db(self.full_content, is_error=False)

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
            await StreamManager._cleanup_stream(self.session_id)

    def subscribe(self) -> asyncio.Queue:
        """Create a new async queue for a client to consume chunks."""
        q = asyncio.Queue()
        # If there's already content, push it to the new subscriber
        if self.full_content:
            q.put_nowait(self.full_content)
        if self.is_finished:
            q.put_nowait(None)

        self.queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        """Remove a subscriber queue."""
        if q in self.queues:
            self.queues.remove(q)


class StreamManager:
    """Global manager for active streams.

    Streams persist in RAM during active generation.
    Cleanup happens automatically after stream completes (via finally block).
    """

    _streams: Dict[int, StreamBuffer] = {}
    _lock = asyncio.Lock()
    _cleanup_task: Optional[asyncio.Task] = None

    @classmethod
    async def start_stream(
        cls,
        session_id: int,
        user_message: str,
        interface: str = "web",
        provider: Optional[str] = None,
        model: Optional[str] = None,
        image_paths: Optional[List[str]] = None,
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
                session_id, user_message, interface, provider, model, image_paths
            )
            cls._streams[session_id] = stream

            # Ensure cleanup loop is running (fallback for orphaned streams)
            if cls._cleanup_task is None or cls._cleanup_task.done():
                cls._cleanup_task = asyncio.create_task(cls._cleanup_loop())

            return stream

    @classmethod
    async def get_stream(cls, session_id: int) -> Optional[StreamBuffer]:
        """Get an active stream for a session."""
        async with cls._lock:
            return cls._streams.get(session_id)

    @classmethod
    async def _cleanup_stream(cls, session_id: int):
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
