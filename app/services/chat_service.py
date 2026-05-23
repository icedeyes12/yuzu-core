from __future__ import annotations

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import AsyncIterator

from fastapi import UploadFile
from app.db import get_active_session_async
from app.stream_manager import StreamManager
from app.orchestrator import handle_user_message

log = logging.getLogger(__name__)


class ChatService:
    @staticmethod
    async def send_message_async(message: str, interface: str = "web") -> str:
        """Process a simple text message (async)."""
        return await handle_user_message(message, interface=interface)

    @staticmethod
    async def process_image_uploads(images: list[UploadFile]) -> list[str]:
        """Save uploaded images and return their markdown references."""
        image_markdowns = []
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
                    filename = f"{timestamp}_{i}_{safe_filename}"
                    filepath = uploads_dir / filename

                    content = await image_file.read()
                    filepath.write_bytes(content)

                    image_markdowns.append(f"![Uploaded Image](uploads/{filename})")
                except Exception as e:
                    log.error(f"Error saving uploaded image {image_file.filename}: {e}")

        return image_markdowns

    @staticmethod
    async def get_stream_generator(
        user_message: str,
        interface: str = "web",
        provider: str | None = None,
        model: str | None = None,
        images: list[UploadFile] | None = None,
    ) -> AsyncIterator[str]:
        """
        Start a streaming message response (async).
        """
        if images:
            image_markdowns = await ChatService.process_image_uploads(images)
            if image_markdowns:
                user_message = (
                    f"{user_message}\n\n" + "\n".join(image_markdowns)
                    if user_message
                    else "\n".join(image_markdowns)
                )

        active_session = await get_active_session_async()
        session_id = active_session["id"]

        buffer = await StreamManager.start_stream(
            session_id,
            user_message,
            interface=interface,
            provider=provider,
            model=model,
        )

        q = buffer.subscribe()
        try:
            while True:
                # q is now an asyncio.Queue, so just await it
                chunk = await q.get()
                if chunk is None:
                    break
                if chunk:
                    escaped_chunk = json.dumps(chunk)
                    yield f'data: {{"chunk": {escaped_chunk}}}\n\n'
        finally:
            buffer.unsubscribe(q)
            # Re-trigger memory pipeline is handled in orchestrator via _post_turn
