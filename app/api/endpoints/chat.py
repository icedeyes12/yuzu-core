# FILE: app/api/endpoints/chat.py
# DESCRIPTION: Chat and messaging endpoints

from __future__ import annotations

from fastapi import APIRouter, Request, Form, File, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.chat_service import ChatService
from app.services.session_service import SessionService
from app.app import handle_user_message

router = APIRouter(tags=["chat"])

def _get_session_id(request: Request) -> str:
    client_host = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    return f"{client_host}_{hash(user_agent) % 10000}"

class MessageRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User message text")
    interface: str = Field(default="web", description="Interface source identifier")

@router.post("/send_message")
async def api_send_message(request: MessageRequest):
    try:
        user_message = request.message.strip()
        if not user_message:
            return {"reply": "Please type a message!"}

        interface = request.interface
        print(f"[{interface}] message: {user_message[:200]}...")

        ai_reply = ChatService.send_message(user_message, interface=interface)

        print(f"AI reply: {ai_reply}")
        return {"reply": ai_reply}

    except Exception as e:
        print(f"Error in api_send_message: {type(e).__name__}")
        return {"reply": "Sorry, I encountered an error processing your message."}

@router.post("/send_message_stream")
async def api_send_message_stream(
    request: Request,
    message: str | None = Form(None),
    interface: str = Form("web"),
    provider: str | None = Form(None),
    model: str | None = Form(None),
    images: list[UploadFile] = File(default=[]),
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

        print(f"[{interface}] streaming unified message: {user_message[:200]}...")

        return StreamingResponse(
            ChatService.get_stream_generator(
                user_message,
                interface=interface,
                provider=provider,
                model=model,
                images=images
            ),
            media_type="text/event-stream"
        )

    except Exception as e:
        print(f"Error in unified streaming: {type(e).__name__} - {e}")
        async def generate_error():
            yield 'data: {"chunk": "Sorry, I encountered an error processing your message."}\n\n'
        return StreamingResponse(generate_error(), media_type="text/event-stream")

@router.post("/generate_image")
async def api_generate_image(request: MessageRequest):
    try:
        prompt = request.message.strip()
        if not prompt:
            return {"reply": "Prompt required", "status": "error"}

        ai_reply = handle_user_message(f"/imagine {prompt}", interface="web")
        return {"reply": ai_reply, "status": "success"}
    except Exception as e:
        print(f"Error generating image: {type(e).__name__}")
        return {"reply": "Failed to generate image", "status": "error"}

@router.post("/browser_unload")
async def api_browser_unload(request: Request):
    try:
        from app.db import Database
        client_id = _get_session_id(request)
        SessionService.clear_client_session(client_id)
        print("Web page closed or refreshed - session cleared")

        profile = Database.get_profile()
        SessionService.end_session_cleanup(profile, interface="web", unexpected_exit=True)

        return {"status": "page closed"}
    except Exception:
        return {"status": "error", "message": "Internal server error"}
