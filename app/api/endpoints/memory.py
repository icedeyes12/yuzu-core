# FILE: app/api/endpoints/memory.py
# DESCRIPTION: Memory pipeline and stats endpoints

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends
from app.db import Database
from app.api.utils import get_current_user
from app.services.memory_service import MemoryService
from app.logging_config import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["memory"])


@router.post("/update_session_context")
async def api_update_session_context(user_id: str = Depends(get_current_user)):
    try:
        active_session = await Database.get_active_session_async(user_id)
        session_id = active_session["id"]
        profile = await Database.get_profile_async(user_id)

        chat_history = await Database.get_chat_history_async(session_id=session_id)

        if len(chat_history) < 5:
            return {
                "status": "error",
                "message": "Need at least 5 conversation messages",
            }

        last_user_msg = next(
            (msg for msg in reversed(chat_history) if msg["role"] == "user"), None
        )
        last_ai_reply = next(
            (msg for msg in reversed(chat_history) if msg["role"] == "assistant"), None
        )

        if last_user_msg and last_ai_reply:
            success = await MemoryService.summarize_session_async(
                profile, last_user_msg["content"], last_ai_reply["content"], session_id,
                user_id,
            )

            if success:
                session_memory = await Database.get_session_memory_async(session_id)
                return {
                    "status": "success",
                    "message": "Session context updated!",
                    "session_memory": session_memory,
                }
            else:
                return {"status": "error", "message": "Session context update failed"}
        else:
            return {"status": "error", "message": "Need conversation history"}

    except Exception as e:
        log.error("Error updating session context: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/update_global_profile")
async def api_update_global_profile(user_id: str = Depends(get_current_user)):
    try:
        success = await MemoryService.summarize_global_profile_async(user_id)

        if success:
            profile = await Database.get_profile_async(user_id)
            return {
                "status": "success",
                "message": "Global player profile updated from ALL sessions!",
                "profile": profile,
            }
        else:
            return {"status": "error", "message": "Global profile analysis failed"}
    except Exception as e:
        log.error("Error updating global profile: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/rebuild_structured_memory")
async def api_rebuild_structured_memory(user_id: str = Depends(get_current_user)):
    """Rebuild structured memory for the active session."""
    try:
        active_session = await Database.get_active_session_async(user_id)
        session_id = active_session["id"]

        result = await MemoryService.rebuild_structured_memory_async(session_id)

        return {
            "status": "success",
            "message": (
                f"Memory pipeline completed: {result['segments']} segments, "
                f"{result['episodes']} episodes, {result['pcl_runs']} PCL runs"
            ),
            "stats": result,
        }
    except Exception as e:
        log.error("Error rebuilding structured memory: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/run_memory_decay")
async def api_run_memory_decay(user_id: str = Depends(get_current_user)):
    try:
        active_session = await Database.get_active_session_async(user_id)
        session_id = active_session["id"]

        from app.memory.review import run_decay_async

        await run_decay_async(session_id)

        return {
            "status": "success",
            "message": (
                "Memory decay applied. Old memories faded, recent ones preserved."
            ),
        }
    except Exception as e:
        log.error("Error running memory decay: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/memory_stats")
async def api_memory_stats(user_id: str = Depends(get_current_user)):
    try:
        active_session = await Database.get_active_session_async(user_id)
        session_id = active_session["id"]

        from app.memory.db_memory_facade import (
            MemoryDB,
            FACT_TYPE_STATIC,
            FACT_TYPE_DYNAMIC,
        )

        semantic_count = MemoryDB.count_facts(
            fact_type=FACT_TYPE_STATIC, session_id=session_id, user_id=user_id
        )
        episodic_count = MemoryDB.count_facts(
            fact_type=FACT_TYPE_DYNAMIC, session_id=session_id, user_id=user_id
        )

        top_facts = []
        try:
            facts = MemoryDB.get_facts_by_session(
                session_id=session_id, fact_type=FACT_TYPE_STATIC, limit=10, user_id=user_id
            )
            for f in facts:
                meta = f.get("metadata") or {}
                content = f.get("content", "")
                category = meta.get("category", "")
                if content:
                    top_facts.append(
                        f"{category}: {content[:100]}" if category else content[:100]
                    )
        except Exception as e:
            log.error("[memory_stats] top_facts failed: %s", e)

        return {
            "status": "success",
            "stats": {
                "semantic": semantic_count,
                "episodic": episodic_count,
                "segments": 0,
                "top_facts": top_facts,
            },
        }
    except Exception as e:
        log.error("Error getting memory stats: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")
