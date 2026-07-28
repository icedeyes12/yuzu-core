from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.utils import get_client_id, get_current_user
from app.db import (
    Database,
    clear_session_messages_async,
    create_session_async,
    delete_session_async,
    get_active_session_async,
    get_all_sessions_async,
    get_chat_history_async,
    rename_session_async,
    switch_session_async,
)
from app.logging_config import get_logger
from app.services.session_service import SessionService

log = get_logger(__name__)

router = APIRouter(tags=["sessions"])


class SessionCreateRequest(BaseModel):
    name: str = Field(default="New Chat", min_length=1, description="Session name")


class SessionSwitchRequest(BaseModel):
    session_id: str = Field(..., min_length=1, description="Session ID to switch to")


class SessionRenameRequest(BaseModel):
    session_id: str = Field(..., min_length=1, description="Session ID to rename")
    name: str = Field(..., min_length=1, description="New session name")


class SessionDeleteRequest(BaseModel):
    session_id: str = Field(..., min_length=1, description="Session ID to delete")


@router.get("/chat_history")
async def api_get_chat_history(
    session_id: str | None = None,
    limit: int | None = 50,
    user_id: str = Depends(get_current_user),
):
    """Get chat history for a specific session or the active session.
    Defaults to the 50 most recent messages to avoid loading massive histories.
    Pass limit=0 to load all (use with caution on large sessions).
    """
    try:
        effective_limit = limit if limit and limit > 0 else None
        active_session = None
        if session_id:
            chat_history = await get_chat_history_async(
                session_id=session_id,
                limit=effective_limit,
                recent=True,
                user_id=user_id,
            )
        else:
            active_session = await get_active_session_async(user_id)
            if active_session:
                chat_history = await get_chat_history_async(
                    active_session["id"],
                    limit=effective_limit,
                    recent=True,
                    user_id=user_id,
                )
            else:
                chat_history = []
        return {
            "status": "success",
            "active_session_id": active_session["id"] if active_session else None,
            "chat_history": chat_history,
        }
    except Exception as e:
        log.error("Error getting chat history: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/sessions/list")
async def api_list_sessions(user_id: str = Depends(get_current_user)):
    try:
        sessions = await get_all_sessions_async(user_id)
        return {"sessions": sessions}
    except Exception as e:
        log.error("Error listing sessions: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/sessions/create")
async def api_create_session(
    http_request: Request,
    request: SessionCreateRequest,
    user_id: str = Depends(get_current_user),
):
    try:
        session_id = await create_session_async(request.name, user_id=user_id)
        if session_id is None:
            raise HTTPException(status_code=500, detail="Failed to create session")
        _ = await switch_session_async(session_id, user_id=user_id)

        client_id = get_client_id(http_request)
        SessionService.clear_client_session(client_id)

        return {"status": "success", "session_id": session_id}
    except Exception as e:
        log.error("Error creating session: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/sessions/switch")
async def api_switch_session(
    request: SessionSwitchRequest,
    http_request: Request,
    user_id: str = Depends(get_current_user),
):
    try:
        if not request.session_id:
            raise HTTPException(status_code=400, detail="session_id required")

        switched = await switch_session_async(request.session_id, user_id)
        if not switched:
            raise HTTPException(status_code=404, detail="Session not found")

        client_id = get_client_id(http_request)
        SessionService.clear_client_session(client_id)

        _ = await SessionService.start_session_async(interface="web", user_id=user_id)

        SessionService.mark_client_connected(client_id)

        chat_history = await get_chat_history_async(
            session_id=request.session_id, limit=50, recent=True, user_id=user_id
        )

        return {
            "status": "success",
            "active_session_id": request.session_id,
            "session_id": request.session_id,
            "chat_history": chat_history,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error("Error switching session: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/sessions/rename")
async def api_rename_session(
    request: SessionRenameRequest, user_id: str = Depends(get_current_user)
):
    try:
        if not request.session_id or not request.name:
            raise HTTPException(status_code=400, detail="session_id and name required")

        success = await rename_session_async(request.session_id, request.name, user_id)

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
async def api_delete_session(
    request: SessionDeleteRequest, user_id: str = Depends(get_current_user)
):
    try:
        if not request.session_id:
            raise HTTPException(status_code=400, detail="session_id required")

        success = await delete_session_async(request.session_id, user_id)

        if success:
            active_session = await get_active_session_async(user_id)
            if active_session:
                chat_history = await get_chat_history_async(
                    active_session["id"], limit=50, recent=True, user_id=user_id
                )
            else:
                chat_history = []

            return {
                "status": "success",
                "active_session": active_session,
                "chat_history": chat_history,
            }
        else:
            raise HTTPException(status_code=404, detail="Session not found")
    except HTTPException:
        raise
    except Exception as e:
        log.error("Error deleting session: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/clear_chat")
async def api_clear_chat(
    request: Request,
    session_id: str | None = None,
    user_id: str = Depends(get_current_user),
):
    try:
        if not session_id:
            active_session = await get_active_session_async(user_id)
            session_id = active_session["id"]

        assert isinstance(session_id, str)
        _ = await clear_session_messages_async(session_id, user_id=user_id)

        client_id = get_client_id(request)
        SessionService.clear_client_session(client_id)

        return {"status": "success"}
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/end_session")
async def api_end_session(request: Request, user_id: str = Depends(get_current_user)):
    try:
        client_id = get_client_id(request)
        SessionService.clear_client_session(client_id)

        profile = await Database.get_profile(user_id)
        _ = await SessionService.end_session_cleanup_async(
            profile, interface="web", unexpected_exit=False, user_id=user_id
        )
        return {"status": "session ended"}
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")
