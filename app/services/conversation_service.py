from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

from fastapi import UploadFile

from app.db import Database
from app.orchestrator import handle_user_message
from app.stream_manager import StreamManager

log = logging.getLogger(__name__)


class ConversationService:
    """
    Application Layer boundary.
    Owns the business logic (orchestrator execution), but knows nothing about
    how it was triggered (REST, CLI, SSE).
    """

    @staticmethod
    async def process_user_message_async(
        message: str, interface: str = "web", user_id: str | None = None
    ) -> str:
        """Process a simple text message (non-streaming, async)."""
        if not user_id:
            raise ValueError("user_id is required")
        return await handle_user_message(message, interface=interface, user_id=user_id)

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
        if not user_id:
            raise ValueError("user_id is required")

        attachments = []
        if images:
            attachments = await ConversationService.process_image_uploads(images)

        active_session = await Database.get_active_session(user_id)
        session_id = active_session["id"]

        # Build text string for display in history
        history_summary = "Processed pending knowledge items"
        if attachments:
            image_markdown = "\n".join(
                [f"![Uploaded Image]({path})" for path in attachments]
            )
            history_summary += "\n\n" + image_markdown
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
            attachments=attachments,  # Pass paths for vision context
            user_id=user_id,
        )

        q = buffer.subscribe()
        try:
            from app.tools.schemas import StreamToolEvent

            while True:
                chunk = await q.get()
                if chunk is None:
                    done_event = json.dumps({"type": "done", "turn_id": buffer.turn_id})
                    yield f"data: {done_event}\n\n"
                    break
                if chunk:
                    if isinstance(chunk, StreamToolEvent):
                        payload = chunk.to_sse()
                        payload["turn_id"] = buffer.turn_id
                        yield f"data: {json.dumps(payload)}\n\n"
                    else:
                        token_event = json.dumps(
                            {
                                "type": "token",
                                "content": chunk,
                                "turn_id": buffer.turn_id,
                            }
                        )
                        yield f"data: {token_event}\n\n"
        except asyncio.CancelledError:
            log.info(f"[Stream] Client disconnected for session {session_id}")
            buffer.cancel()
            raise
        finally:
            buffer.unsubscribe(q)

    @staticmethod
    async def process_image_uploads(images: list[UploadFile]) -> list[str]:
        """Save uploaded images and return their file paths."""
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
                        c if c.isalnum() or c in "._-" else "_"
                        for c in image_file.filename
                    )
                    filepath = uploads_dir / f"{timestamp}_{i}_{safe_filename}"

                    content = await image_file.read()
                    filepath.write_bytes(content)
                    saved_paths.append(str(filepath))
                except Exception as e:
                    log.error("Error saving image %s: %s", image_file.filename, e)
                finally:
                    await image_file.seek(0)

        return saved_paths
