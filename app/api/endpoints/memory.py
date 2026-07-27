from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.utils import get_current_user
from app.db import Database
from app.logging_config import get_logger
from app.services.memory_service import MemoryService
from app.services.memory_stats_service import MemoryStatsService

log = get_logger(__name__)

router = APIRouter(tags=["memory"])


@router.post("/rebuild_structured_memory")
async def api_rebuild_structured_memory(user_id: str = Depends(get_current_user)):
    """Rebuild structured memory for the active session."""
    try:
        active_session = await Database.get_active_session(user_id)
        session_id = active_session["id"]

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


@router.get("/memory_stats")
async def api_memory_stats(user_id: str = Depends(get_current_user)):
    """Return graph-memory counts for the current tenant."""
    try:
        stats = await MemoryStatsService.get_stats(user_id)
        return {"status": "success", "stats": stats}
    except Exception as e:
        log.error("Error getting graph memory stats: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")
