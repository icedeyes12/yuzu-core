# FILE: app/api/endpoints/sessions.py
# DESCRIPTION: Session management endpoints

from __future__ import annotations

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
from app.db import (
    get_all_sessions_async,
    get_active_session_async,
    get_chat_history_async,
    get_session_memory_async,
    create_session_async,
    switch_session_async,
    rename_session_async,
    delete_session_async,
    clear_session_messages_async,
    Database,
)
from app.services.session_service import SessionService
from app.logging_config import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["sessions"])


def _get_session_id(request: Request) -> str:
    client_host = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    return f"{client_host}_{hash(user_agent) % 10000}"


class SessionCreateRequest(BaseModel):
    name: str = Field(default="New Chat", min_length=1, description="Session name")


class SessionSwitchRequest(BaseModel):
    session_id: int = Field(..., gt=0, description="Session ID to switch to")


class SessionRenameRequest(BaseModel):
    session_id: int = Field(..., gt=0, description="Session ID to rename")
    name: str = Field(..., min_length=1, description="New session name")


class SessionDeleteRequest(BaseModel):
    session_id: int = Field(..., gt=0, description="Session ID to delete")


@router.get("/chat_history")
async def api_get_chat_history(session_id: int | None = None):
    """Get chat history for a specific session or the active session."""
    try:
        if session_id:
            chat_history = await get_chat_history_async(session_id=session_id)
        else:
            active_session = await get_active_session_async()
            if active_session:
                chat_history = await get_chat_history_async(active_session["id"])
            else:
                chat_history = await get_chat_history_async()
        return {"status": "success", "chat_history": chat_history}
    except Exception as e:
        log.error("Error getting chat history: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/sessions/list")
async def api_list_sessions():
    try:
        sessions = await get_all_sessions_async()
        return {"sessions": sessions}
    except Exception as e:
        log.error("Error listing sessions: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/sessions/create")
async def api_create_session(http_request: Request, request: SessionCreateRequest):
    try:
        session_id = await create_session_async(request.name)
        await switch_session_async(session_id)

        client_id = _get_session_id(http_request)
        SessionService.clear_client_session(client_id)

        return {"status": "success", "session_id": session_id}
    except Exception as e:
        log.error("Error creating session: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/sessions/switch")
async def api_switch_session(request: SessionSwitchRequest, http_request: Request):
    try:
        if not request.session_id:
            raise HTTPException(status_code=400, detail="session_id required")

        await switch_session_async(request.session_id)

        client_id = _get_session_id(http_request)
        SessionService.clear_client_session(client_id)

        SessionService.start_session(interface="web")

        SessionService.mark_client_connected(client_id)

        chat_history = await get_chat_history_async(session_id=request.session_id)
        session_memory = await get_session_memory_async(request.session_id)

        return {
            "status": "success",
            "session_id": request.session_id,
            "chat_history": chat_history,
            "session_memory": session_memory,
        }
    except Exception as e:
        log.error("Error switching session: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/sessions/rename")
async def api_rename_session(request: SessionRenameRequest):
    try:
        if not request.session_id or not request.name:
            raise HTTPException(status_code=400, detail="session_id and name required")

        success = await rename_session_async(request.session_id, request.name)

        if success:
            return {"status": "success"}
        else:
            raise HTTPException(status_code=404, detail="Session not found")
    except HTTPException:
        raise
    except Exception as e:
        log.error("Error renaming session: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/sessions/delete")
async def api_delete_session(request: SessionDeleteRequest):
    try:
        if not request.session_id:
            raise HTTPException(status_code=400, detail="session_id required")

        success = await delete_session_async(request.session_id)

        if success:
            active_session = await get_active_session_async()
            chat_history = await get_chat_history_async()
            session_memory = await get_session_memory_async(active_session["id"])

            return {
                "status": "success",
                "active_session": active_session,
                "chat_history": chat_history,
                "session_memory": session_memory,
            }
        else:
            raise HTTPException(status_code=404, detail="Session not found")
    except HTTPException:
        raise
    except Exception as e:
        log.error("Error deleting session: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/clear_chat")
async def api_clear_chat(request: Request, session_id: int | None = None):
    try:
        if session_id:
            session_id = session_id
        else:
            active_session = await get_active_session_async()
            session_id = active_session["id"]

        await clear_session_messages_async(session_id)

        client_id = _get_session_id(request)
        SessionService.clear_client_session(client_id)

        return {"status": "success"}
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/end_session")
async def api_end_session(request: Request):
    try:
        client_id = _get_session_id(request)
        SessionService.clear_client_session(client_id)

        profile = await Database.get_profile_async()
        await SessionService.end_session_cleanup_async(
            profile, interface="web", unexpected_exit=False
        )
        return {"status": "session ended"}
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/sessions/{session_id}/memory")
async def api_get_session_memory(session_id: int):
    try:
        session_memory = await get_session_memory_async(session_id)
        return {
            "status": "success",
            "session_id": session_id,
            "session_context": session_memory.get("session_context", ""),
            "last_summarized": session_memory.get("last_summarized", "Never"),
        }
    except Exception as e:
        log.error("Error getting session memory: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")
