# FILE: app/api/endpoints/chat.py
# DESCRIPTION: Chat and messaging endpoints

from __future__ import annotations

from fastapi import APIRouter, Request, Form, File, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.context import (
    RequestKeyring,
    set_request_keyring,
    clear_request_keyring,
)
from app.services.chat_service import ChatService
from app.services.session_service import SessionService
from app.api.utils import get_client_id, get_current_user
from fastapi import Depends
from app.orchestrator import handle_user_message
from app.logging_config import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["chat"])


def _extract_keyring(request: Request) -> RequestKeyring | None:
    """Read BYOK headers from the request and build a RequestKeyring."""
    provider_name = request.headers.get("X-Provider-Name")
    key = request.headers.get("X-Provider-Key")
    base_url = request.headers.get("X-Base-Url")
    model_id = request.headers.get("X-Model-Id")
    if not key and not base_url and not model_id:
        return None
    return RequestKeyring(
        provider=provider_name,
        key=key,
        base_url=base_url,
        model_id=model_id,
    )


class MessageRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User message text")
    interface: str = Field(default="web", description="Interface source identifier")


@router.post("/send_message")
async def api_send_message(
    request: Request,
    payload: MessageRequest, 
    user_id: str = Depends(get_current_user),
):
    keyring = _extract_keyring(request)
    if keyring:
        set_request_keyring(keyring)
    try:
        user_message = payload.message.strip()
        if not user_message:
            return {"reply": "Please type a message!"}

        interface = payload.interface
        log.info("[%s] message: %s...", interface, user_message[:200])

        ai_reply = await ChatService.send_message_async(
            user_message, interface=interface, user_id=user_id
        )

        log.info("AI reply: %s", ai_reply)
        return {"reply": ai_reply}

    except Exception as e:
        log.error("Error in api_send_message: %s", type(e).__name__)
        return {"reply": "Sorry, I encountered an error processing your message."}
    finally:
        if keyring:
            clear_request_keyring()


@router.post("/send_message_stream")
async def api_send_message_stream(
    request: Request,
    message: str | None = Form(None),
    interface: str = Form("web"),
    provider: str | None = Form(None),
    model: str | None = Form(None),
    images: list[UploadFile] = File(default=[]),
    user_id: str = Depends(get_current_user),
):
    """Unified streaming endpoint for text and images."""
    try:
        # Support both JSON (legacy/simple) and Form (unified/images)
        if request.headers.get("content-type", "").startswith("application/json"):
            try:
                data = await request.json()
                user_message = data.get("message", "").strip()
                interface = data.get("interface", "web")
                provider = data.get("provider")
                model = data.get("model")
            except Exception:
                user_message = ""
        else:
            user_message = message.strip() if message else ""

        if not user_message and not images:

            async def empty_generator():
                yield 'data: {"chunk": "Please provide a message or images!"}\n\n'

            return StreamingResponse(empty_generator(), media_type="text/event-stream")

        log.info("[%s] streaming unified message: %s...", interface, user_message[:200])

        keyring = _extract_keyring(request)

        async def _keyring_scoped_stream():
            """Wrap the stream generator so the ContextVar is set before
            StreamManager.start_stream spawns its background task (which
            copies the current context). Cleared in finally."""
            if keyring:
                set_request_keyring(keyring)
            try:
                async for chunk in ChatService.get_stream_generator(
                    user_message,
                    interface=interface,
                    provider=provider,
                    model=model,
                    images=images,
                    user_id=user_id,
                ):
                    yield chunk
            finally:
                if keyring:
                    clear_request_keyring()

        return StreamingResponse(
            _keyring_scoped_stream(),
            media_type="text/event-stream",
        )

    except Exception as e:
        log.error("Error in unified streaming: %s - %s", type(e).__name__, e)

        async def generate_error():
            yield 'data: {"chunk": "Sorry, I encountered an error processing your message."}\n\n'

        return StreamingResponse(generate_error(), media_type="text/event-stream")


@router.post("/generate_image")
async def api_generate_image(
    request: Request,
    payload: MessageRequest,
    user_id: str = Depends(get_current_user),
):
    keyring = _extract_keyring(request)
    if keyring:
        set_request_keyring(keyring)
    try:
        prompt = payload.message.strip()
        if not prompt:
            return {"reply": "Prompt required", "status": "error"}

        ai_reply = await handle_user_message(
            f"/imagine {prompt}", interface="web", user_id=user_id
        )
        return {"reply": ai_reply, "status": "success"}
    except Exception as e:
        log.error("Error generating image: %s", type(e).__name__)
        return {"reply": "Failed to generate image", "status": "error"}
    finally:
        if keyring:
            clear_request_keyring()


@router.post("/browser_unload")
async def api_browser_unload(
    request: Request, user_id: str = Depends(get_current_user)
):
    try:
        from app.db import Database

        client_id = get_client_id(request)
        SessionService.clear_client_session(client_id)
        log.info("Web page closed or refreshed - session cleared")

        profile = await Database.get_profile_async(user_id)
        await SessionService.end_session_cleanup_async(
            profile, interface="web", unexpected_exit=True
        )

        return {"status": "page closed"}
    except Exception:
        return {"status": "error", "message": "Internal server error"}
