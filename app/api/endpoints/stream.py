# FILE: app/api/endpoints/stream.py
# DESCRIPTION: Stream status and sync validation endpoints

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.stream_manager import StreamManager
from app.logging_config import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/stream", tags=["stream"])


@router.get("/{session_id}/status")
async def get_stream_status(session_id: int):
    """Get stream buffer status for frontend sync validation.
    
    Informational: Returns buffer state to allow frontend validation.
    Frontend can call this after stream completion to verify integrity.
    
    Returns:
        - is_finished: bool - Stream completed
        - is_error: bool - Stream encountered error
        - buffer_length: int - Character count
        - checksum: str - SHA-256 hash (first 16 chars)
        - last_activity: float - Unix timestamp
    """
    stream = await StreamManager.get_stream(session_id)
    
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found")
    
    return stream.get_status()


@router.get("/{session_id}/sync")
async def sync_stream_buffer(session_id: int):
    """Sync with backend stream buffer for integrity validation.
    
    Informational: Called by frontend after stream completes to validate
    that its local buffer matches backend's canonical buffer.
    
    Frontend should:
    1. Wait for stream completion
    2. Call this endpoint
    3. Compare checksums
    4. If mismatch, reload from DB
    
    Returns:
        - full_content: str - Complete buffered text
        - checksum: str - Hash for validation
        - buffer_length: int - Character count
    """
    stream = await StreamManager.get_stream(session_id)
    
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found")
    
    if not stream.is_finished:
        raise HTTPException(status_code=400, detail="Stream still active")
    
    return {
        "full_content": stream.full_content,
        "checksum": stream.get_checksum(),
        "buffer_length": len(stream.full_content),
    }
