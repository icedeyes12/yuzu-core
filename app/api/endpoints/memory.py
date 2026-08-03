from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.models import ERROR_RESPONSES, MemoryResponse
from app.api.rate_limits import acquire_active_user, rate_limit_user, release_active
from app.api.utils import extract_keyrings, get_current_user
from app.core.logging_config import get_logger
from app.db import Database
from app.services.memory_service import MemoryService
from app.services.memory_stats_service import MemoryStatsService

log = get_logger(__name__)

router = APIRouter(tags=["memory"])


@router.post(
    "/rebuild_structured_memory",
    include_in_schema=False,
    response_model=MemoryResponse,
    responses=ERROR_RESPONSES,
)
async def api_rebuild_structured_memory(
    request: Request, user_id: str = Depends(get_current_user)
):
    """Rebuild structured memory for the active session."""
    rate_limit_user(user_id, 1, "memory-rebuild-user")
    from app.core.context import clear_request_keyring, set_request_keyrings

    keyrings = extract_keyrings(request)
    active_acquired = False
    acquire_active_user(user_id, 1, "memory-rebuild-active")
    active_acquired = True
    if keyrings:
        set_request_keyrings(keyrings)
    try:
        active_session = await Database.get_active_session(user_id)
        session_id = str(active_session["id"])

        result = await MemoryService.rebuild_structured_memory_async(
            session_id, user_id=user_id
        )

        return {
            "status": "success",
            "message": (
                f"Memory pipeline completed: {result.get('episodes_created', result.get('episodes', 0))} episodes, "
                f"{result.get('claims_processed', result.get('claims', 0))} claims in one extraction pass"
            ),
            "stats": result,
        }
    except Exception as e:
        log.error("Error rebuilding structured memory: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        if active_acquired:
            release_active(user_id, "memory-rebuild-active")
        if keyrings:
            clear_request_keyring()


@router.get(
    "/memory_stats",
    include_in_schema=False,
    response_model=MemoryResponse,
    responses=ERROR_RESPONSES,
)
async def api_memory_stats(user_id: str = Depends(get_current_user)):
    """Return graph-memory counts for the current tenant."""
    try:
        stats = await MemoryStatsService.get_stats(user_id)
        return {"status": "success", "stats": stats}
    except Exception as e:
        log.error("Error getting graph memory stats: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")
