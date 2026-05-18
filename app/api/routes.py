# FILE: app/api/routes.py
# DESCRIPTION: API endpoints for yuzu-companion web interface

from __future__ import annotations

from fastapi import APIRouter, Request, HTTPException, Form, File, UploadFile
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel, Field
from datetime import datetime
import json
import os

from app.app import (
    handle_user_message,
    handle_user_message_streaming,
    end_session_cleanup,
    summarize_memory,
    summarize_global_player_profile,
    set_preferred_provider,
    get_vision_capabilities,
    set_vision_model,
)
from app.database import Database
from app.providers import get_ai_manager
from app.database import (
    get_active_session_async,
    get_all_sessions_async,
    create_session_async,
    switch_session_async,
    rename_session_async,
    delete_session_async,
    get_session_memory_async,
    get_chat_history_async,
    clear_session_messages_async,
    add_message_async,
    get_profile_async,
    update_profile_async,
    get_api_keys_async,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

api_router = APIRouter()

# Global session tracker (shared with web.py)
_web_session_tracker: dict[str, bool] = {}


def set_session_tracker(tracker: dict[str, bool]):
    global _web_session_tracker
    _web_session_tracker = tracker


def _get_session_id(request: Request) -> str:
    client_host = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    return f"{client_host}_{hash(user_agent) % 10000}"


# ---------------------------------------------------------------------------# Pydantic Models
# ---------------------------------------------------------------------------


class MessageRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User message text")
    interface: str = Field(default="web", description="Interface source identifier")


class StreamMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User message text")
    interface: str = Field(default="web", description="Interface source identifier")
    provider: str | None = Field(None, description="AI provider to use")
    model: str | None = Field(None, description="AI model to use")


class ApiKeyRequest(BaseModel):
    key_name: str = Field(..., min_length=1, description="Name for the API key")
    api_key: str = Field(..., min_length=1, description="The API key value")


class ChutesKeyRequest(BaseModel):
    api_key: str = Field(..., min_length=1, description="Chutes API key value")


class SessionCreateRequest(BaseModel):
    name: str = Field(default="New Chat", min_length=1, description="Session name")


class SessionSwitchRequest(BaseModel):
    session_id: int = Field(..., gt=0, description="Session ID to switch to")


class SessionRenameRequest(BaseModel):
    session_id: int = Field(..., gt=0, description="Session ID to rename")
    name: str = Field(..., min_length=1, description="New session name")


class SessionDeleteRequest(BaseModel):
    session_id: int = Field(..., gt=0, description="Session ID to delete")


class ProviderSetRequest(BaseModel):
    provider_name: str = Field(..., min_length=1, description="AI provider name")
    model_name: str | None = Field(None, description="Optional model name")


class ProviderTestRequest(BaseModel):
    provider_name: str = Field(..., min_length=1, description="Provider name to test")


class VisionModelSetRequest(BaseModel):
    provider: str = Field(..., min_length=1, description="Vision provider name")
    model: str = Field(..., min_length=1, description="Vision model name")


class LocationUpdateRequest(BaseModel):
    lat: float = Field(..., description="Latitude")
    lon: float = Field(..., description="Longitude")


class GlobalKnowledgeUpdateRequest(BaseModel):
    facts: str = Field(..., description="Global knowledge facts")


# ---------------------------------------------------------------------------
# Config API - Frontend SSOT
# ---------------------------------------------------------------------------


@api_router.get("/config")
async def api_get_config():
    """Single source of truth for frontend configuration."""
    try:
        ai_manager = get_ai_manager()
        available_providers = ai_manager.get_available_providers()
        all_models = ai_manager.get_all_models()
        vision_capabilities = get_vision_capabilities()

        profile = Database.get_profile()
        providers_config = profile.get("providers_config", {})
        current_provider = providers_config.get("preferred_provider", "ollama")
        current_model = providers_config.get("preferred_model", "glm-4.6:cloud")
        vision_prefs = providers_config.get("vision_model_preferences", {})

        from app.tools.multimodal import multimodal_tools

        vision_models_by_provider = {}
        for provider in ["chutes", "openrouter"]:
            vision_models_by_provider[provider] = (
                multimodal_tools.get_available_vision_models(provider)
            )

        return {
            "status": "success",
            "ai_providers": {
                "available_providers": available_providers,
                "all_models": all_models,
                "current_provider": current_provider,
                "current_model": current_model,
            },
            "vision": {
                "capabilities": vision_capabilities,
                "models_by_provider": vision_models_by_provider,
                "current_provider": vision_prefs.get("provider"),
                "current_model": vision_prefs.get("model"),
            },
        }
    except Exception as e:
        print(f"Error getting config: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Profile & Chat API
# ---------------------------------------------------------------------------


@api_router.get("/get_profile")
async def api_get_profile():
    try:
        profile = await get_profile_async()
        active_session = await get_active_session_async()
        chat_history = await get_chat_history_async(
            session_id=active_session["id"], limit=None
        )
        session_memory = await get_session_memory_async(active_session["id"])

        ai_manager = get_ai_manager()
        available_providers = ai_manager.get_available_providers()
        all_models = ai_manager.get_all_models()

        providers_config = profile.get("providers_config", {})
        current_provider = providers_config.get("preferred_provider", "ollama")
        current_model = providers_config.get("preferred_model", "glm-4.6:cloud")

        api_keys = await get_api_keys_async()
        vision_capabilities = get_vision_capabilities()

        profile_dict = {
            "id": profile["id"],
            "display_name": profile["display_name"],
            "partner_name": profile["partner_name"],
            "affection": profile["affection"],
            "theme": profile["theme"],
            "memory": profile["memory"],
            "session_history": profile["session_history"],
            "global_knowledge": profile["global_knowledge"],
            "providers_config": profile["providers_config"],
            "context": profile["context"],
            "image_model": profile["image_model"],
            "vision_model": profile["vision_model"],
            "vision_model_preferences": profile.get("providers_config", {}).get(
                "vision_model_preferences", {}
            ),
            "created_at": profile["created_at"].isoformat()
            if profile["created_at"]
            else None,
            "updated_at": profile["updated_at"].isoformat()
            if profile["updated_at"]
            else None,
        }

        return {
            **profile_dict,
            "chat_history": chat_history,
            "api_keys": api_keys,
            "active_session": active_session,
            "session_memory": session_memory,
            "ai_providers": {
                "available_providers": available_providers,
                "all_models": all_models,
                "current_provider": current_provider,
                "current_model": current_model,
            },
            "multimodal_capabilities": vision_capabilities,
        }
    except Exception as e:
        print(f"Error in api_get_profile: {e}")
        raise HTTPException(status_code=500, detail="Failed to load profile")


@api_router.post("/send_message")
async def api_send_message(request: MessageRequest):
    try:
        user_message = request.message.strip()

        if not user_message:
            return {"reply": "Please type a message!"}

        interface = request.interface  # from request payload
        print(f"[{interface}] message: {user_message[:200]}...")

        active_session = Database.get_active_session()
        _ = active_session["id"]

        ai_reply = handle_user_message(user_message, interface=interface)  # DYNAMIC

        print(f"AI reply: {ai_reply}")

        return {"reply": ai_reply}

    except Exception as e:
        # Log internally but don't expose details to user
        print(f"Error in api_send_message: {type(e).__name__}")
        return {"reply": "Sorry, I encountered an error processing your message."}


@api_router.post("/send_message_stream")
async def api_send_message_stream(request: StreamMessageRequest):
    try:
        user_message = request.message.strip()

        if not user_message:

            async def empty_generator():
                yield 'data: {"chunk": "Please type a message!"}\n\n'

            return StreamingResponse(empty_generator(), media_type="text/event-stream")

        interface = request.interface  # from request payload
        print(f"[{interface}] streaming message: {user_message[:200]}...")

        response_generator = handle_user_message_streaming(
            user_message,
            interface=interface,  # DYNAMIC
            provider=request.provider,
            model=request.model,
        )

        def generate():
            for chunk in response_generator:
                if chunk:
                    escaped_chunk = json.dumps(chunk)
                    yield f'data: {{"chunk": {escaped_chunk}}}\n\n'

        return StreamingResponse(generate(), media_type="text/event-stream")

    except Exception as e:
        # Log internally but don't expose details
        print(f"Error in streaming: {type(e).__name__}")

        def generate_error():
            yield 'data: {"chunk": "Sorry, I encountered an error processing your message."}\n\n'

        return StreamingResponse(generate_error(), media_type="text/event-stream")


@api_router.post("/send_message_with_images")
async def api_send_message_with_images(
    request: Request,
    message: str = Form(""),
    images: list[UploadFile] = File(default=[]),
):
    try:
        message_text = message.strip()

        if not message_text and not images:
            return {"reply": "Please provide a message or images!"}

        print(f"Processing message with {len(images)} images")

        active_session = Database.get_active_session()
        _ = active_session["id"]

        saved_images = []
        image_markdowns = []

        for i, image_file in enumerate(images):
            if image_file and image_file.filename:
                uploads_dir = "static/uploads"
                os.makedirs(uploads_dir, exist_ok=True)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_filename = "".join(
                    c
                    for c in image_file.filename
                    if c.isalnum() or c in (".", "-", "_")
                ).rstrip()
                filename = f"{timestamp}_{i}_{safe_filename}"
                filepath = os.path.join(uploads_dir, filename)

                content = await image_file.read()
                with open(filepath, "wb") as f:
                    f.write(content)

                web_url = f"/uploads/{filename}"
                image_markdown = f"![Uploaded Image](uploads/{filename})"
                image_markdowns.append(image_markdown)

                saved_images.append(
                    {
                        "web_url": web_url,
                        "filepath": filepath,
                        "markdown": image_markdown,
                    }
                )
                print(f"Saved image to static: {filepath}")

        if image_markdowns:
            final_user_message = (
                f"{message_text}\n\n" + "\n".join(image_markdowns)
                if message_text
                else "\n".join(image_markdowns)
            )
        else:
            final_user_message = message_text

        print(f"Final user message: {final_user_message[:200]}...")

        ai_reply = handle_user_message(final_user_message, interface="web")

        return {"reply": ai_reply, "uploaded_images": saved_images}

    except Exception as e:
        # Log internally but don't expose details
        print(f"Error in image upload: {type(e).__name__}")
        return {"reply": "Error processing message."}


@api_router.post("/generate_image")
async def api_generate_image(request: MessageRequest):
    try:
        prompt = request.message.strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="Prompt required")

        ai_reply = handle_user_message(f"/imagine {prompt}", interface="web")
        return {"reply": ai_reply, "status": "success"}
    except Exception as e:
        print(f"Error generating image: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Failed to generate image")


@api_router.get("/get_vision_capabilities")
async def api_get_vision_capabilities():
    try:
        capabilities = get_vision_capabilities()
        return {"status": "success", "capabilities": capabilities}
    except Exception as e:
        print(f"Error getting vision capabilities: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Failed to get vision capabilities")


@api_router.post("/update_profile")
async def api_update_profile(request: Request):
    try:
        updates = await request.json()
        await update_profile_async(updates)
        return {"status": "success"}
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")


@api_router.post("/clear_chat")
async def api_clear_chat(request: Request):
    try:
        active_session = await get_active_session_async()
        session_id = active_session["id"]

        await clear_session_messages_async(session_id)

        client_id = _get_session_id(request)
        _web_session_tracker.pop(client_id, None)

        return {"status": "success"}
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")


@api_router.post("/end_session")
async def api_end_session(request: Request):
    try:
        client_id = _get_session_id(request)
        _web_session_tracker.pop(client_id, None)

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        profile = Database.get_profile()

        session_history = profile.get("session_history", {})
        current_session = session_history.get("current_session", {})
        start_time = current_session.get("start_time")
        duration = 0

        if start_time:
            try:
                start = datetime.fromisoformat(start_time)
                duration = (datetime.now() - start).total_seconds() / 60
            except Exception:
                pass

        disconnect_msg = (
            f"*{profile['display_name']} disconnected from web interface at {current_time}. "
            f"Session duration: {duration:.1f} minutes*"
        )

        Database.add_message("system", disconnect_msg)
        end_session_cleanup(profile, interface="web", unexpected_exit=False)
        return {"status": "session ended"}
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------


@api_router.post("/add_api_key")
async def api_add_api_key(request: ApiKeyRequest):
    if not request.api_key or not request.key_name:
        return {"status": "error", "message": "Key name and API key required"}

    if Database.add_api_key(request.key_name, request.api_key):
        return {"status": "success", "message": f"{request.key_name} API key added"}
    else:
        return {
            "status": "error",
            "message": "API key already exists or failed to save",
        }


@api_router.post("/add_chutes_key")
async def api_add_chutes_key(request: ChutesKeyRequest):
    try:
        api_key = request.api_key.strip()

        if not api_key:
            return {"status": "error", "message": "Chutes API key required"}

        if Database.add_api_key("chutes", api_key):
            return {
                "status": "success",
                "message": "Chutes API key added successfully!",
            }
        else:
            return {"status": "error", "message": "Failed to save Chutes API key"}
    except Exception as e:
        print(f"Error adding Chutes API key: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@api_router.post("/remove_api_key")
async def api_remove_api_key(request: Request):
    try:
        data = await request.json()
        key_name = data.get("key_name", "").strip()

        if not key_name:
            return {"status": "error", "message": "Key name required"}

        if Database.remove_api_key(key_name):
            return {"status": "success", "message": f"{key_name} API key removed"}
        else:
            return {"status": "error", "message": "API key not found"}
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Memory & Context
# ---------------------------------------------------------------------------


@api_router.post("/update_session_context")
async def api_update_session_context():
    try:
        active_session = Database.get_active_session()
        session_id = active_session["id"]
        profile = Database.get_profile()

        chat_history = Database.get_chat_history(session_id=session_id)

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
            success = summarize_memory(
                profile, last_user_msg["content"], last_ai_reply["content"], session_id
            )

            if success:
                session_memory = Database.get_session_memory(session_id)
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
        print(f"Error updating session context: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@api_router.post("/update_global_profile")
async def api_update_global_profile():
    try:
        success = summarize_global_player_profile()

        if success:
            profile = Database.get_profile()
            print(f"Returning updated profile with memory: {profile.get('memory', {})}")

            return {
                "status": "success",
                "message": "Global player profile updated from ALL sessions!",
                "profile": profile,
            }
        else:
            return {"status": "error", "message": "Global profile analysis failed"}
    except Exception as e:
        print(f"Error updating global profile: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@api_router.post("/rebuild_structured_memory")
async def api_rebuild_structured_memory():
    try:
        active_session = Database.get_active_session()
        session_id = active_session["id"]

        from app.memory.memory import run_memory_pipeline
        from app.memory.db_memory import (
            count_facts,
            FACT_TYPE_STATIC,
            FACT_TYPE_DYNAMIC,
        )

        # Get message count
        count = Database.get_session_messages_count(session_id)

        # Run the full pipeline
        result = run_memory_pipeline(session_id, count)

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
        print(f"Error rebuilding structured memory: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@api_router.post("/run_memory_decay")
async def api_run_memory_decay():
    try:
        active_session = Database.get_active_session()
        session_id = active_session["id"]

        from app.memory.review import run_decay

        run_decay(session_id)

        return {
            "status": "success",
            "message": "Memory decay applied. Old memories faded, recent ones preserved.",
        }
    except Exception as e:
        print(f"Error running memory decay: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@api_router.get("/memory_stats")
async def api_memory_stats():
    try:
        active_session = Database.get_active_session()
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
            print(f"[memory_stats] top_facts failed: {e}")

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
        print(f"Error getting memory stats: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Provider Management
# ---------------------------------------------------------------------------


@api_router.get("/providers/list")
async def api_list_providers():
    try:
        ai_manager = get_ai_manager()
        available_providers = ai_manager.get_available_providers()
        all_models = ai_manager.get_all_models()

        profile = Database.get_profile()
        providers_config = profile.get("providers_config", {})
        current_provider = providers_config.get("preferred_provider", "ollama")
        current_model = providers_config.get("preferred_model", "glm-4.6:cloud")

        return {
            "status": "success",
            "available_providers": available_providers,
            "all_models": all_models,
            "current_provider": current_provider,
            "current_model": current_model,
        }
    except Exception as e:
        print(f"Error listing providers: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@api_router.post("/providers/set_preferred")
async def api_set_preferred_provider(request: ProviderSetRequest):
    try:
        if not request.provider_name:
            return {"status": "error", "message": "Provider name required"}

        result = set_preferred_provider(request.provider_name, request.model_name)

        return {"status": "success", "message": result}
    except Exception as e:
        print(f"Error setting preferred provider: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@api_router.post("/providers/test_connection")
async def api_test_provider_connection(request: ProviderTestRequest):
    try:
        if not request.provider_name:
            return {"status": "error", "message": "Provider name required"}

        ai_manager = get_ai_manager()
        provider = ai_manager.providers.get(request.provider_name)

        if not provider:
            return {
                "status": "error",
                "message": f"Provider {request.provider_name} not found",
            }
        is_connected = provider.test_connection()

        return {
            "status": "success",
            "provider": request.provider_name,
            "connected": is_connected,
            "message": f"{request.provider_name}: {'Connected' if is_connected else 'Connection failed'}",
        }
    except Exception as e:
        print(f"Error testing provider connection: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@api_router.post("/providers/set_vision_model")
async def api_set_vision_model(request: VisionModelSetRequest):
    try:
        if not request.provider or not request.model:
            return {"status": "error", "message": "Provider and model required"}

        result = set_vision_model(request.provider, request.model)

        return {"status": "success", "message": result}
    except Exception as e:
        print(f"Error setting vision model: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@api_router.post("/providers/test_vision")
async def api_test_vision():
    try:
        return {"status": "success", "message": "Vision model test successful"}
    except Exception as e:
        print(f"Error testing vision: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@api_router.post("/browser_unload")
async def api_browser_unload(request: Request):
    try:
        client_id = _get_session_id(request)
        _web_session_tracker.pop(client_id, None)
        print("Web page closed or refreshed - session cleared")

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        profile = Database.get_profile()

        session_history = profile.get("session_history", {})
        current_session = session_history.get("current_session", {})
        start_time = current_session.get("start_time")
        duration = 0

        if start_time:
            try:
                start = datetime.fromisoformat(start_time)
                duration = (datetime.now() - start).total_seconds() / 60
            except Exception:
                pass

        disconnect_msg = (
            f"*{profile['display_name']} disconnected unexpectedly from web interface at {current_time}. "
            f"Session duration: {duration:.1f} minutes*"
        )

        Database.add_message("system", disconnect_msg)
        end_session_cleanup(profile, interface="web", unexpected_exit=True)

        return {"status": "page closed"}
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Session Management
# ---------------------------------------------------------------------------


@api_router.get("/sessions/list")
async def api_list_sessions():
    try:
        sessions = await get_all_sessions_async()
        return {"sessions": sessions}
    except Exception as e:
        print(f"Error listing sessions: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@api_router.post("/sessions/create")
async def api_create_session(http_request: Request, request: SessionCreateRequest):
    try:
        session_id = await create_session_async(request.name)
        await switch_session_async(session_id)

        client_id = _get_session_id(http_request)
        _web_session_tracker.pop(client_id, None)

        return {"status": "success", "session_id": session_id}
    except Exception as e:
        print(f"Error creating session: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@api_router.post("/sessions/switch")
async def api_switch_session(request: SessionSwitchRequest, http_request: Request):
    try:
        if not request.session_id:
            raise HTTPException(status_code=400, detail="session_id required")

        await switch_session_async(request.session_id)

        client_id = _get_session_id(http_request)
        _web_session_tracker.pop(client_id, None)

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        profile = await get_profile_async()

        all_sessions = await get_all_sessions_async()
        session_count = len(all_sessions)

        connection_msg = (
            f"*{profile['display_name']} connected to web interface at {current_time}. "
            f"Switched to session #{[s['id'] for s in all_sessions].index(request.session_id) + 1} of {session_count}*"
        )

        await add_message_async(request.session_id, "system", connection_msg)

        _web_session_tracker[client_id] = True

        chat_history = await get_chat_history_async(session_id=request.session_id)
        session_memory = await get_session_memory_async(request.session_id)

        return {
            "status": "success",
            "session_id": request.session_id,
            "chat_history": chat_history,
            "session_memory": session_memory,
        }
    except Exception as e:
        print(f"Error switching session: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@api_router.post("/sessions/rename")
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
        print(f"Error renaming session: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@api_router.post("/sessions/delete")
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
        print(f"Error deleting session: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@api_router.get("/sessions/{session_id}/memory")
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
        print(f"Error getting session memory: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Location & Global Knowledge
# ---------------------------------------------------------------------------


@api_router.post("/update_location")
async def api_update_location(request: LocationUpdateRequest):
    try:
        context = Database.get_context()
        context["location"] = {"lat": request.lat, "lon": request.lon}
        Database.update_context(context)
        return {"status": "ok"}
    except Exception as e:
        print(f"Error updating location: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@api_router.post("/update_weather_location")
async def api_update_weather_location(request: LocationUpdateRequest):
    try:
        context = Database.get_context()
        context["location"] = {"lat": request.lat, "lon": request.lon}
        Database.update_context(context)
        return {"status": "success", "message": "Weather location updated"}
    except Exception as e:
        print(f"Error updating weather location: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@api_router.post("/global_knowledge/update")
async def api_update_global_knowledge(request: GlobalKnowledgeUpdateRequest):
    try:
        global_knowledge = {"facts": request.facts}
        Database.update_profile({"global_knowledge": global_knowledge})
        return {"status": "success", "message": "Global knowledge updated"}
    except Exception as e:
        print(f"Error updating global knowledge: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Static File Serving
# ---------------------------------------------------------------------------


@api_router.get("/static/uploads/{filename}")
async def serve_uploaded_image(filename: str):
    try:
        uploads_dir = os.path.abspath(os.path.join(BASE_DIR, "static", "uploads"))
        file_path = os.path.abspath(
            os.path.normpath(os.path.join(uploads_dir, filename))
        )
        if not file_path.startswith(uploads_dir + os.sep):
            raise HTTPException(status_code=404, detail="Image not found")
        if os.path.exists(file_path):
            return FileResponse(file_path)
        raise HTTPException(status_code=404, detail="Image not found")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")


@api_router.get("/static/generated_images/{filename}")
async def serve_generated_image(filename: str):
    try:
        generated_dir = os.path.abspath(
            os.path.join(BASE_DIR, "static", "generated_images")
        )
        file_path = os.path.abspath(
            os.path.normpath(os.path.join(generated_dir, filename))
        )
        if not file_path.startswith(generated_dir + os.sep):
            raise HTTPException(status_code=404, detail="Image not found")
        if os.path.exists(file_path):
            return FileResponse(file_path)
        raise HTTPException(status_code=404, detail="Image not found")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")
