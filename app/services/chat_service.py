from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import AsyncIterator

from fastapi import UploadFile
from app.db import get_active_session_async
from app.stream_manager import StreamManager
from app.orchestrator import handle_user_message
from app.tools.schemas import StreamToolEvent

log = logging.getLogger(__name__)


class ChatService:
    @staticmethod
    async def send_message_async(
        message: str, interface: str = "web", user_id: str | None = None
    ) -> str:
        """Process a simple text message (async)."""
        return await handle_user_message(message, interface=interface, user_id=user_id)

    @staticmethod
    async def process_image_uploads(images: list[UploadFile]) -> list[str]:
        """Save uploaded images and return their file paths.

        Returns list of saved file paths like ['static/uploads/20250526_123456_0_image.png']
        """
        saved_paths = []
        if not images:
            return []

        uploads_dir = Path("static/uploads")
        uploads_dir.mkdir(parents=True, exist_ok=True)

        for i, image_file in enumerate(images):
            if image_file and image_file.filename:
                try:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    # Clean filename
                    safe_filename = "".join(
                        c
                        for c in image_file.filename
                        if c.isalnum() or c in (".", "-", "_")
                    ).rstrip()
                    # Determine extension from content type or filename
                    ext = Path(safe_filename).suffix.lower()
                    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                        ext = ".png"
                        safe_filename = f"{Path(safe_filename).stem}{ext}"

                    filename = f"{timestamp}_{i}_{safe_filename}"
                    filepath = uploads_dir / filename

                    content = await image_file.read()
                    filepath.write_bytes(content)

                    saved_paths.append(str(filepath))
                    log.info(f"[Upload] Saved image: {filepath}")
                except Exception as e:
                    log.error(f"Error saving uploaded image {image_file.filename}: {e}")

        return saved_paths

    @staticmethod
    async def get_stream_generator(
        user_message: str,
        interface: str = "web",
        provider: str | None = None,
        model: str | None = None,
        images: list[UploadFile] | None = None,
        user_id: str | None = None,
    ) -> AsyncIterator[str]:
        """
        Start a streaming message response (async).
        Images are saved to disk and paths are passed to the orchestrator.
        """
        image_paths = []
        if images:
            image_paths = await ChatService.process_image_uploads(images)

        active_session = await get_active_session_async(user_id)
        session_id = active_session["id"]

        # Build markdown for display in history
        if image_paths:
            image_markdown = "\n".join(
                [f"![Uploaded Image]({path})" for path in image_paths]
            )
            if user_message:
                user_message = f"{user_message}\n\n{image_markdown}"
            else:
                user_message = image_markdown

        buffer = await StreamManager.start_stream(
            session_id,
            user_message,
            interface=interface,
            provider=provider,
            model=model,
            image_paths=image_paths,  # Pass paths for vision context
            user_id=user_id,
        )

        q = buffer.subscribe()
        try:
            while True:
                # q is now an asyncio.Queue, so just await it
                chunk = await q.get()
                if chunk is None:
                    # Emit turn-complete event
                    done_event = json.dumps({"type": "done", "turn_id": buffer.turn_id})
                    yield f"data: {done_event}\n\n"
                    break
                if chunk:
                    if isinstance(chunk, StreamToolEvent):
                        # Typed event — serialize via to_sse()
                        payload = json.dumps(chunk.to_sse())
                        yield f"data: {payload}\n\n"
                    else:
                        # Plain text token — backward-compatible + typed envelope
                        token_event = json.dumps(
                            {
                                "type": "token",
                                "chunk": chunk,
                                "turn_id": buffer.turn_id,
                            }
                        )
                        yield f"data: {token_event}\n\n"
        except asyncio.CancelledError:
            # Client disconnected - cancel the producer task
            log.info(f"[Stream] Client disconnected for session {session_id}")
            buffer.cancel()
            raise
        finally:
            buffer.unsubscribe(q)
            # Re-trigger memory pipeline is handled in orchestrator via _post_turn
