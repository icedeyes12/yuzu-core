from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.utils import get_client_id, get_current_user
from app.core.context import (
    MissingProviderKeyError,
    RequestKeyring,
    clear_request_keyring,
    set_request_keyrings,
)
from app.core.logging_config import get_logger
from app.services.conversation_service import ConversationService
from app.services.session_service import SessionService

log = get_logger(__name__)

router = APIRouter(tags=["chat"])


def _extract_keyrings(request: Request) -> dict[str, RequestKeyring] | None:
    """Read the grouped client-side BYOK configuration from the request."""
    import base64
    import json
    import urllib.parse

    byok_header = request.headers.get("X-BYOK-Config")
    if not byok_header:
        return None

    try:
        raw_json = urllib.parse.unquote(base64.b64decode(byok_header).decode("utf-8"))
        byok_config = json.loads(raw_json)
        providers = byok_config.get("providers", byok_config)
        if not isinstance(providers, dict):
            return {}

        keyrings = {}
        for provider, cfg in providers.items():
            if not isinstance(cfg, dict):
                continue
            keyrings[provider] = RequestKeyring(
                provider=provider,
                key=cfg.get("api_key"),
                base_url=(
                    cfg.get("base_url") if provider.startswith("custom") else None
                ),
                model_id=cfg.get("model_id"),
            )
        return keyrings
    except Exception as e:
        log.error("Failed to parse X-BYOK-Config header: %s", e)
        return None


class MessageRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User message text")
    interface: str = Field(default="web", description="Interface source identifier")


@router.post("/send_message")
async def api_send_message(
    request: Request,
    payload: MessageRequest,
    user_id: str = Depends(get_current_user),
):
    keyrings = _extract_keyrings(request)
    if keyrings:
        set_request_keyrings(keyrings)
    try:
        user_message = payload.message.strip()
        if not user_message:
            return {"reply": "Please type a message!"}

        interface = payload.interface
        log.info("[%s] message: %s...", interface, user_message[:200])

        ai_reply = await ConversationService.process_user_message_async(
            user_message, interface=interface, user_id=user_id
        )

        log.info("AI reply: %s", ai_reply)
        return {"reply": ai_reply}

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
    except Exception as e:
        log.error("Error in api_send_message: %s", type(e).__name__)
        return {"reply": "Sorry, I encountered an error processing your message."}
    finally:
        if keyrings:
            clear_request_keyring()


@router.post("/send_message_stream")
async def api_send_message_stream(
    request: Request,
    message: str | None = Form(None),
    interface: str = Form("web"),
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
            except Exception:
                user_message = ""
        else:
            user_message = message.strip() if message else ""

        if not user_message and not images:

            async def empty_generator():
                yield 'data: {"type":"error","message":"Please provide a message or images!"}\n\n'

            return StreamingResponse(empty_generator(), media_type="text/event-stream")

        log.info("[%s] streaming unified message: %s...", interface, user_message[:200])

        keyrings = _extract_keyrings(request)

        async def _keyring_scoped_stream():
            if keyrings:
                set_request_keyrings(keyrings)
            try:
                async for chunk in ConversationService.get_stream_generator(
                    user_message,
                    interface=interface,
                    images=images,
                    user_id=user_id,
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
                if keyrings:
                    clear_request_keyring()

        return StreamingResponse(
            _keyring_scoped_stream(),
            media_type="text/event-stream",
        )

    except Exception as e:
        log.error("Error in unified streaming: %s - %s", type(e).__name__, e)

        async def generate_error():
            yield 'data: {"type":"error","message":"Sorry, I encountered an error processing your message."}\n\n'

        return StreamingResponse(generate_error(), media_type="text/event-stream")


@router.post("/generate_image")
async def api_generate_image(
    request: Request,
    payload: MessageRequest,
    user_id: str = Depends(get_current_user),
):
    keyrings = _extract_keyrings(request)
    if keyrings:
        set_request_keyrings(keyrings)
    try:
        prompt = payload.message.strip()
        if not prompt:
            return {"reply": "Prompt required", "status": "error"}

        ai_reply = await ConversationService.process_user_message_async(
            f"/imagine {prompt}", interface="web", user_id=user_id
        )
        return {"reply": ai_reply, "status": "success"}
    except Exception as e:
        log.error("Error generating image: %s", type(e).__name__)
        return {"reply": "Failed to generate image", "status": "error"}
    finally:
        if keyrings:
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

        profile = await Database.get_profile(user_id)
        _ = await SessionService.end_session_cleanup_async(
            profile, interface="web", unexpected_exit=True, user_id=user_id
        )

        return {"status": "page closed"}
    except Exception:
        return {"status": "error", "message": "Internal server error"}
