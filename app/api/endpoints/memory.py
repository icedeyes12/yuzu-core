# FILE: app/api/endpoints/memory.py
# DESCRIPTION: Memory pipeline and stats endpoints

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from app.db import Database
from app.services.memory_service import MemoryService
from app.logging_config import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["memory"])


@router.post("/update_session_context")
async def api_update_session_context():
    try:
        active_session = await Database.get_active_session_async()
        session_id = active_session["id"]
        profile = await Database.get_profile_async()

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
                profile, last_user_msg["content"], last_ai_reply["content"], session_id
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
async def api_update_global_profile():
    try:
        success = await MemoryService.summarize_global_profile_async()

        if success:
            profile = await Database.get_profile_async()
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
async def api_rebuild_structured_memory():
    try:
        active_session = await Database.get_active_session_async()
        session_id = active_session["id"]

        from app.memory.memory import run_memory_pipeline_async
        from app.memory.db_memory import (
            count_facts,
            FACT_TYPE_STATIC,
            FACT_TYPE_DYNAMIC,
        )

        # Get message count
        count = await Database.get_session_messages_count_async(session_id)

        # Run the full pipeline
        result = await run_memory_pipeline_async(session_id, count)

        semantic_count = count_facts(fact_type=FACT_TYPE_STATIC, session_id=session_id)
        episodic_count = count_facts(fact_type=FACT_TYPE_DYNAMIC, session_id=session_id)

        return {
            "status": "success",
            "message": f"Memory pipeline completed: {result.get('segments', 0)} segments, {result.get('episodes', 0)} episodes, {result.get('pcl_runs', 0)} PCL runs",
            "stats": {
                "semantic": semantic_count,
                "episodic": episodic_count,
                "segments": result.get("segments", 0),
                "episodes": result.get("episodes", 0),
                "pcl_runs": result.get("pcl_runs", 0),
            },
        }
    except Exception as e:
        log.error("Error rebuilding structured memory: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/run_memory_decay")
async def api_run_memory_decay():
    try:
        active_session = await Database.get_active_session_async()
        session_id = active_session["id"]

        from app.memory.review import run_decay_async

        await run_decay_async(session_id)

        return {
            "status": "success",
            "message": "Memory decay applied. Old memories faded, recent ones preserved.",
        }
    except Exception as e:
        log.error("Error running memory decay: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/memory/store")
async def api_store_memory(request: Request, session_id: int | None = None):
    pass


@router.get("/memory/retrieve")
async def api_retrieve_memory(request: Request, session_id: int | None = None):
    pass


@router.get("/memory_stats")
async def api_memory_stats():
    try:
        active_session = await Database.get_active_session_async()
        session_id = active_session["id"]

        from app.memory.db_memory import (
            count_facts,
            FACT_TYPE_STATIC,
            FACT_TYPE_DYNAMIC,
            get_facts_by_session,
        )

        semantic_count = count_facts(fact_type=FACT_TYPE_STATIC, session_id=session_id)
        episodic_count = count_facts(fact_type=FACT_TYPE_DYNAMIC, session_id=session_id)

        top_facts = []
        try:
            facts = get_facts_by_session(
                session_id=session_id, fact_type=FACT_TYPE_STATIC, limit=10
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
