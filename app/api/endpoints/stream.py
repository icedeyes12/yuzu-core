# FILE: app/api/endpoints/stream.py
# DESCRIPTION: Stream status and sync validation endpoints

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path

from app.stream_manager import StreamManager
from app.logging_config import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/stream", tags=["stream"])


@router.get("/{session_id}/status")
async def get_stream_status(
    session_id: str = Path(..., description="Session ID", min_length=1),
):
    """Get current stream status and buffer state for a session.

    Used by frontend to check if stream is still active or completed.
    """
    try:
        stream = await StreamManager.get_stream(session_id)

        if not stream:
            return {
                "active": False,
                "completed": False,
                "length": 0,
                "error": "No active stream for this session",
            }

        return {
            "active": not stream.is_finished,
            "completed": stream.is_finished,
            "length": len(stream.full_content),
            "has_error": stream.error is not None,
        }

    except Exception as e:
        log.error(f"[StreamAPI] Status check failed for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{session_id}/sync")
async def sync_stream_buffer(
    session_id: str = Path(..., description="Session ID", min_length=1),
):
    """Sync frontend buffer with backend and return validation checksum.

    Used after stream completion to ensure frontend buffer matches backend.
    If mismatch detected, frontend can request full content replacement.
    """
    try:
        stream = await StreamManager.get_stream(session_id)

        if not stream:
            return {
                "valid": False,
                "error": "No stream found for this session",
                "length": 0,
                "checksum": "",
            }

        # Get backend checksum and length
        checksum = stream.get_checksum()
        length = len(stream.full_content)

        return {
            "valid": True,
            "length": length,
            "checksum": checksum,
            "completed": stream.is_finished,
        }

    except Exception as e:
        log.error(f"[StreamAPI] Sync failed for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
