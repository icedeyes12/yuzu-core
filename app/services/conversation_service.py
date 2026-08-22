from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import UploadFile

from app.core.request_context import ClientContext
from app.db import Database
from app.services.file_service import QuotaExceeded, StorageUnavailable
from app.services.files import get_file_service
from app.services.orchestrator import handle_user_message
from app.services.stream_manager import StreamManager
from app.tools.schemas import StreamToolEvent

log = logging.getLogger(__name__)


class ConversationService:
    """
    Application Layer boundary.
    Owns the business logic (orchestrator execution), but knows nothing about
    how it was triggered (REST, CLI, SSE).
    """

    @staticmethod
    async def process_user_message_async(
        message: str,
        interface: str = "web",
        user_id: str | None = None,
        client_context: ClientContext | None = None,
    ) -> str:
        """Process a simple text message (non-streaming, async)."""
        if not user_id:
            raise ValueError("user_id is required")
        return await handle_user_message(
            message,
            interface=interface,
            user_id=user_id,
            client_context=client_context,
        )

    @staticmethod
    async def get_stream_generator(
        user_message: str,
        interface: str = "web",
        images: list[UploadFile] | None = None,
        user_id: str | None = None,
        client_context: ClientContext | None = None,
    ) -> AsyncIterator[str]:
        """
        Start a streaming message response (async).
        Images are saved to disk and paths are passed to the orchestrator.
        """
        if not user_id:
            raise ValueError("user_id is required")

        attachments = []
        if images:
            attachments = await ConversationService.process_image_uploads(
                images, user_id
            )

        active_session = await Database.get_active_session(user_id)
        session_id = str(active_session["id"])

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
            attachments=attachments,  # Pass paths for vision context
            user_id=user_id,
            client_context=client_context,
        )

        q = buffer.subscribe()
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(q.get(), timeout=15)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
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
    async def process_image_uploads(
        images: list[UploadFile], user_id: str
    ) -> list[str]:
        """Persist uploaded images and return private logical URLs."""
        saved_paths = []
        if not images:
            return []

        service = get_file_service()

        for image_file in images:
            if image_file and image_file.filename:
                try:
                    content = await image_file.read()
                    row = await service.persist_bytes(
                        owner_id=user_id,
                        data=content,
                        kind="upload",
                        original_name=image_file.filename,
                        mime_type=image_file.content_type or "application/octet-stream",
                    )
                    from app.core.ids import EntityType, PublicId

                    file_id = PublicId.encode(EntityType.FILE, row["id"])
                    saved_paths.append(f"/api/v1/files/{file_id}")
                except (QuotaExceeded, StorageUnavailable):
                    raise
                except Exception as e:
                    log.error("Error saving image %s: %s", image_file.filename, e)
                finally:
                    await image_file.seek(0)

        return saved_paths
