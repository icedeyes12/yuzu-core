# FILE: app/stream_manager.py
# DESCRIPTION: Backend state management for streaming responses.
#              Allows clients to disconnect and reconnect to ongoing streams.

from __future__ import annotations

import queue
import threading
import time
from typing import Dict, List, Optional

from app.logging_config import get_logger

log = get_logger(__name__)

class StreamBuffer:
    """In-memory cache for a single session's ongoing stream."""
    
    def __init__(self, session_id: int, user_message: str):
        self.session_id = session_id
        self.user_message = user_message
        self.chunks: List[str] = []
        self.is_complete = False
        self.error: Optional[str] = None
        self.clients: List[queue.Queue] = []
        self.lock = threading.Lock()
        self.start_time = time.time()
        self.last_activity = time.time()
        self.assistant_message_id: Optional[int] = None
        self.full_text = ""

    def add_chunk(self, chunk: str):
        """Append a chunk and broadcast to all active subscribers."""
        with self.lock:
            if not chunk:
                return
            self.chunks.append(chunk)
            self.full_text += chunk
            self.last_activity = time.time()
            
            # Broadcast to all connected clients
            for q in self.clients:
                try:
                    q.put_nowait(chunk)
                except queue.Full:
                    pass

    def finish(self, error: Optional[str] = None):
        """Mark the stream as finished and notify subscribers."""
        with self.lock:
            self.is_complete = True
            self.error = error
            # Send sentinel to signal end of stream
            for q in self.clients:
                try:
                    q.put_nowait(None)
                except queue.Full:
                    pass
            self.last_activity = time.time()
            log.info("Stream finished for session %d (error=%s)", self.session_id, error)

    def subscribe(self) -> queue.Queue:
        """Create a new queue and catch up with already-received chunks."""
        with self.lock:
            q = queue.Queue(maxsize=1000)
            # Replay all chunks for catch-up
            for chunk in self.chunks:
                q.put(chunk)
            
            if self.is_complete:
                q.put(None)
            else:
                self.clients.append(q)
            
            return q

    def unsubscribe(self, q: queue.Queue):
        """Remove a client queue."""
        with self.lock:
            if q in self.clients:
                self.clients.remove(q)


class StreamManager:
    """Global manager for session-based stream buffers."""
    
    _buffers: Dict[int, StreamBuffer] = {}
    _lock = threading.Lock()
    _cleanup_thread: Optional[threading.Thread] = None
    
    # TTL for inactive buffers (15 minutes)
    BUFFER_TTL = 900 

    @classmethod
    def get_active_buffer(cls, session_id: int) -> Optional[StreamBuffer]:
        """Get an ongoing stream buffer if it exists and is not finished."""
        with cls._lock:
            buf = cls._buffers.get(session_id)
            if buf and not buf.is_complete:
                return buf
            return None

    @classmethod
    def start_stream(cls, session_id: int, user_message: str, **kwargs) -> StreamBuffer:
        """Start a new background stream for a session."""
        with cls._lock:
            # If a buffer already exists and is active, check if it matches the message
            if session_id in cls._buffers and not cls._buffers[session_id].is_complete:
                existing = cls._buffers[session_id]
                if existing.user_message == user_message:
                    log.info("Reattaching to existing stream for session %d", session_id)
                    return existing
                else:
                    # New message for the same session - we should probably finish the old one
                    log.warning("New message for session %d while another is active. Finishing old one.", session_id)
                    existing.finish(error="Superseded by new message")
            
            # Start a new buffer
            buf = StreamBuffer(session_id, user_message)
            cls._buffers[session_id] = buf
            
            # Start the background orchestration
            thread = threading.Thread(
                target=cls._run_orchestrator,
                args=(buf, user_message),
                kwargs=kwargs,
                name=f"stream-{session_id}"
            )
            thread.daemon = True
            thread.start()
            
            # Ensure cleanup thread is running
            cls._ensure_cleanup_running()
            
            return buf

    @classmethod
    def _run_orchestrator(cls, buf: StreamBuffer, user_message: str, **kwargs):
        """Worker thread running the orchestrator generator."""
        from app.orchestrator import handle_user_message_streaming
        
        log.info("Starting background stream thread for session %d", buf.session_id)
        
        def abort_check():
            return buf.is_complete # If buffer is finished or superseded

        try:
            # Pass abort_check to the generator
            for chunk in handle_user_message_streaming(
                user_message, 
                abort_check=abort_check,
                **kwargs
            ):
                buf.add_chunk(chunk)
                
            buf.finish()
        except Exception as e:
            log.error("Stream thread crashed for session %d: %s", buf.session_id, e, exc_info=True)
            buf.finish(error=str(e))

    @classmethod
    def _ensure_cleanup_running(cls):
        """Start a background thread to prune stale buffers."""
        if cls._cleanup_thread and cls._cleanup_thread.is_alive():
            return
            
        def cleanup_loop():
            while True:
                time.sleep(300) # Check every 5 minutes
                with cls._lock:
                    now = time.time()
                    to_delete = []
                    for sid, buf in cls._buffers.items():
                        if buf.is_complete and (now - buf.last_activity > 60):
                            # Finished buffers stay for 1 minute for final catch-up
                            to_delete.append(sid)
                        elif now - buf.last_activity > cls.BUFFER_TTL:
                            # Stale/abandoned buffers
                            to_delete.append(sid)
                    
                    for sid in to_delete:
                        del cls._buffers[sid]
        
        cls._cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True, name="stream-cleanup")
        cls._cleanup_thread.start()
