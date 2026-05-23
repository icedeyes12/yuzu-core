from __future__ import annotations

import os
import json
import asyncio
import logging
from datetime import datetime
from typing import Any, AsyncIterator

from fastapi import UploadFile
from app.db import Database, get_active_session_async
from app.stream_manager import StreamManager
from app.orchestrator import handle_user_message

log = logging.getLogger(__name__)

class ChatService:
    @staticmethod
    def send_message(message: str, interface: str = "web") -> str:
        """Process a simple text message synchronously."""
        return handle_user_message(message, interface=interface)

    @staticmethod
    async def process_image_uploads(images: list[UploadFile]) -> list[str]:
        """Save uploaded images and return their markdown references."""
        image_markdowns = []
        if not images:
            return []

        uploads_dir = "static/uploads"
        os.makedirs(uploads_dir, exist_ok=True)
        
        for i, image_file in enumerate(images):
            if image_file and image_file.filename:
                try:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    # Clean filename
                    safe_filename = "".join(c for c in image_file.filename if c.isalnum() or c in (".", "-", "_")).rstrip()
                    filename = f"{timestamp}_{i}_{safe_filename}"
                    filepath = os.path.join(uploads_dir, filename)
                    
                    content = await image_file.read()
                    with open(filepath, "wb") as f:
                        f.write(content)
                    
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
        Start a streaming message response and return an async generator 
        yielding SSE-formatted data chunks.
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

        buffer = StreamManager.start_stream(
            session_id,
            user_message,
            interface=interface,
            provider=provider,
            model=model,
        )

        q = buffer.subscribe()
        try:
            while True:
                # Use a loop executor for the blocking queue.get()
                chunk = await asyncio.get_event_loop().run_in_executor(None, q.get)
                if chunk is None:
                    break
                if chunk:
                    escaped_chunk = json.dumps(chunk)
                    yield f'data: {{"chunk": {escaped_chunk}}}\n\n'
        finally:
            buffer.unsubscribe(q)
            # Re-trigger memory pipeline is handled in orchestrator via _post_turn
