from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.models import (
    ERROR_RESPONSES,
    MessageResponse,
    OperationResponse,
    StreamMetadata,
)
from app.api.rate_limits import acquire_active_user, rate_limit_user, release_active
from app.api.utils import (
    extract_keyrings,
    get_client_id,
    get_current_user,
    release_stream_slot,
    try_acquire_stream_slot,
)
from app.core.context import (
    MissingProviderKeyError,
    clear_request_keyring,
    set_request_keyrings,
)
from app.core.logging_config import get_logger
from app.core.request_context import (
    ClientContext,
    clear_client_context,
    set_client_context,
)
from app.services.conversation_service import ConversationService
from app.services.session_service import SessionService

log = get_logger(__name__)

router = APIRouter(tags=["chat"])


class MessageRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User message text")
    interface: str = Field(default="web", description="Interface source identifier")


_ALLOWED_UPLOAD_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_MAX_UPLOAD_COUNT = 3


def _validate_uploads(images: list[UploadFile]) -> None:
    if len(images) > _MAX_UPLOAD_COUNT:
        raise HTTPException(
            status_code=413, detail="A maximum of 3 images may be uploaded"
        )
    for image in images:
        if not image or not image.filename:
            raise HTTPException(
                status_code=422, detail="Each upload must have a filename"
            )
        if image.content_type not in _ALLOWED_UPLOAD_TYPES:
            raise HTTPException(
                status_code=415,
                detail="Only JPEG, PNG, WebP, and GIF images are accepted",
            )
        filename = image.filename.replace("\\", "/")
        if "\x00" in filename or filename.rsplit("/", 1)[-1] != filename:
            raise HTTPException(status_code=422, detail="Invalid upload filename")


async def _validate_upload_sizes(images: list[UploadFile]) -> None:
    _validate_uploads(images)
    for image in images:
        content = await image.read(_MAX_UPLOAD_BYTES + 1)
        await image.seek(0)
        if len(content) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413, detail="Each image must be 10 MB or smaller"
            )


@router.post(
    "/send_message",
    response_model=MessageResponse,
    responses={
        401: {"description": "Authentication required"},
        424: {"description": "Provider key required"},
        502: {"description": "AI provider failure"},
    },
)
async def api_send_message(
    request: Request,
    payload: MessageRequest,
    user_id: str = Depends(get_current_user),
):
    rate_limit_user(user_id, 10, "send-message-user")
    set_client_context(
        ClientContext(
            timezone=request.headers.get("X-Client-Timezone"),
            local_time=request.headers.get("X-Client-Local-Time"),
        )
    )
    keyrings = extract_keyrings(request)
    if keyrings:
        set_request_keyrings(keyrings)
    active_acquired = False
    try:
        acquire_active_user(user_id, 1, "send-message-active")
        active_acquired = True
        user_message = payload.message.strip()
        if not user_message:
            return MessageResponse(reply="Please type a message!")

        interface = payload.interface
        log.info("[%s] message: %s...", interface, user_message[:200])

        ai_reply = await ConversationService.process_user_message_async(
            user_message, interface=interface, user_id=user_id
        )

        log.info("AI reply: %s", ai_reply)
        return MessageResponse(reply=ai_reply)

    except MissingProviderKeyError as e:
        log.warning("Missing provider key: %s", e)
        raise HTTPException(
            status_code=424,
            detail=(
                "Please set your Yuzu Portal API key in the config to use this chat model."
                if e.provider == "yuzu_portal"
                else f"No API key for {e.provider}. Set your key in Settings → Provider Keys."
            ),
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error("Error in api_send_message: %s", type(e).__name__)
        raise HTTPException(
            status_code=502,
            detail="The AI provider failed to process the message",
        ) from e
    finally:
        if active_acquired:
            release_active(user_id, "send-message-active")
        if keyrings:
            clear_request_keyring()
        clear_client_context()


@router.post(
    "/send_message_stream",
    response_model=None,
    responses={
        200: {"description": "Server-sent events"},
        **ERROR_RESPONSES,
    },
)
async def api_send_message_stream(
    request: Request,
    message: str | None = Form(None),
    interface: str = Form("web"),
    images: list[UploadFile] = File(default=[]),
    user_id: str = Depends(get_current_user),
):
    """Unified streaming endpoint for text and images."""
    acquired = False
    try:
        rate_limit_user(user_id, 10, "send-message-stream-user")
        if not try_acquire_stream_slot(user_id):
            raise HTTPException(
                status_code=429,
                detail="Too many active streams for this user",
                headers={"Retry-After": "5"},
            )
        acquired = True

        # Support both JSON (legacy/simple) and Form (unified/images)
        if request.headers.get("content-type", "").startswith("application/json"):
            try:
                data = await request.json()
                user_message = data.get("message", "").strip()
                interface = data.get("interface", "web")
            except Exception:
                user_message = ""
        else:
            user_message = message.strip() if message else ""

        if not user_message and not images:

            async def empty_generator():
                yield 'data: {"type":"error","message":"Please provide a message or images!"}\n\n'

            return StreamingResponse(empty_generator(), media_type="text/event-stream")

        log.info("[%s] streaming unified message: %s...", interface, user_message[:200])

        await _validate_upload_sizes(images)
        keyrings = extract_keyrings(request)

        async def _keyring_scoped_stream():
            context = ClientContext(
                timezone=request.headers.get("X-Client-Timezone"),
                local_time=request.headers.get("X-Client-Local-Time"),
            )
            if keyrings:
                set_request_keyrings(keyrings)
            try:
                async for chunk in ConversationService.get_stream_generator(
                    user_message,
                    interface=interface,
                    images=images,
                    user_id=user_id,
                    client_context=context,
                ):
                    yield chunk
            except MissingProviderKeyError as e:
                log.warning("Missing provider key in stream: %s", e)
                message = (
                    "Please set your Yuzu Portal API key in the config to use this chat model."
                    if e.provider == "yuzu_portal"
                    else f"No API key for {e.provider}. Set your key in Settings → Provider Keys."
                )
                payload = json.dumps(
                    {
                        "type": "error",
                        "error": "missing_key",
                        "provider": e.provider,
                        "message": message,
                    }
                )
                yield f"data: {payload}\n\n"
            finally:
                release_stream_slot(user_id)
                if keyrings:
                    clear_request_keyring()

        return StreamingResponse(
            _keyring_scoped_stream(),
            media_type="text/event-stream",
            headers={
                "X-Stream-Heartbeat-Seconds": str(
                    StreamMetadata().heartbeat_interval_seconds
                ),
                "X-Stream-Idle-Timeout-Seconds": str(
                    StreamMetadata().idle_timeout_seconds
                ),
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    except Exception as e:
        if acquired:
            release_stream_slot(user_id)
        log.error("Error in unified streaming: %s - %s", type(e).__name__, e)

        async def generate_error():
            yield 'data: {"type":"error","message":"Sorry, I encountered an error processing your message."}\n\n'

        return StreamingResponse(
            generate_error(),
            media_type="text/event-stream",
            headers={
                "X-Stream-Heartbeat-Seconds": str(
                    StreamMetadata().heartbeat_interval_seconds
                ),
                "X-Stream-Idle-Timeout-Seconds": str(
                    StreamMetadata().idle_timeout_seconds
                ),
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )


@router.post(
    "/generate_image",
    include_in_schema=False,
    response_model=MessageResponse,
    responses=ERROR_RESPONSES,
)
async def api_generate_image(
    request: Request,
    payload: MessageRequest,
    user_id: str = Depends(get_current_user),
):
    rate_limit_user(user_id, 3, "generate-image-user")
    keyrings = extract_keyrings(request)
    if keyrings:
        set_request_keyrings(keyrings)
    try:
        prompt = payload.message.strip()
        if not prompt:
            return MessageResponse(reply="Prompt required", status="error")

        ai_reply = await ConversationService.process_user_message_async(
            f"/imagine {prompt}", interface="web", user_id=user_id
        )
        return MessageResponse(reply=ai_reply, status="success")
    except MissingProviderKeyError as e:
        raise HTTPException(
            status_code=424, detail=f"No API key for {e.provider}"
        ) from e
    except Exception as e:
        log.error("Error generating image: %s", type(e).__name__)
        raise HTTPException(status_code=502, detail="Image generation failed") from e
    finally:
        if keyrings:
            clear_request_keyring()
        clear_client_context()


@router.post(
    "/browser_unload",
    include_in_schema=False,
    response_model=OperationResponse,
    responses=ERROR_RESPONSES,
)
async def api_browser_unload(
    request: Request, user_id: str = Depends(get_current_user)
):
    try:
        from app.db import Database

        client_id = get_client_id(request)
        SessionService.clear_client_session(client_id)
        log.info("Web page closed or refreshed - session cleared")

        profile = await Database.get_profile(user_id)
        _ = await SessionService.end_session_cleanup_async(
            profile, interface="web", unexpected_exit=True, user_id=user_id
        )

        return {"status": "page closed"}
    except Exception:
        return {"status": "error", "message": "Internal server error"}
