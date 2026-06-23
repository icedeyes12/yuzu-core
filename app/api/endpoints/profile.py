# FILE: app/api/endpoints/profile.py
# DESCRIPTION: Profile, config, and provider settings endpoints

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from datetime import datetime

from app.db import (
    Database,
    get_profile_async,
    get_active_session_async,
    get_chat_history_async,
    get_session_memory_async,
    update_profile_async,
)
from app.api.utils import get_current_user
from app.stream_manager import StreamManager
from app.services.config_service import ConfigService
from app.providers import get_ai_manager
from app.logging_config import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["profile"])


class ApiKeyRequest(BaseModel):
    key_name: str = Field(..., min_length=1, description="Name for the API key")
    api_key: str = Field(..., min_length=1, description="The API key value")


class ChutesKeyRequest(BaseModel):
    api_key: str = Field(..., min_length=1, description="Chutes API key value")


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


class ProfileUpdateRequest(BaseModel):
    updates: dict = Field(..., description="Key-value pairs for profile updates")


class ApiKeyRemoveRequest(BaseModel):
    key_name: str = Field(
        ..., min_length=1, description="Name of the API key to remove"
    )


@router.get("/config")
async def api_get_config(user_id: str = Depends(get_current_user)):
    """Single source of truth for frontend configuration."""
    try:
        return await ConfigService.get_frontend_config(user_id)
    except Exception as e:
        log.error("Error getting config: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/profile")
async def api_get_profile(
    session_id: str | None = None, user_id: str = Depends(get_current_user)
):
    try:
        profile = await get_profile_async(user_id)
        if session_id is None:
            active_session = await get_active_session_async(user_id)
        else:
            active_session = {"id": session_id}
        session_id = active_session["id"]
        chat_history = await get_chat_history_async(session_id=session_id, limit=None, user_id=user_id)

        # Inject ongoing stream if it exists
        active_buf = await StreamManager.get_stream(session_id)
        if active_buf and active_buf.full_content:
            # Check if the last message in history is already this response
            last_msg = chat_history[-1] if chat_history else None
            is_duplicate = False
            if last_msg and last_msg.get("role") == "assistant":
                if len(last_msg.get("content", "")) >= len(active_buf.full_content):
                    is_duplicate = True

            if not is_duplicate:
                chat_history.append(
                    {
                        "id": -99,  # Sentinel ID for live content
                        "role": "assistant",
                        "content": active_buf.full_content,
                        "timestamp": datetime.now().isoformat(),
                    }
                )
        session_memory = await get_session_memory_async(
            active_session["id"], user_id=user_id
        )  # ownership via session FK

        profile_dict = ConfigService.format_profile_dict(profile)
        ai_providers_payload = await ConfigService.get_ai_providers_payload(profile)
        vision_capabilities = ConfigService.get_vision_capabilities()

        return {
            **profile_dict,
            "chat_history": chat_history,
            "active_session": active_session,
            "session_memory": session_memory,
            "ai_providers": ai_providers_payload,
            "multimodal_capabilities": vision_capabilities,
        }
    except Exception as e:
        log.error("Error in api_get_profile: %s", e)
        raise HTTPException(status_code=500, detail="Failed to load profile")


@router.post("/update_profile")
async def api_update_profile(
    request: ProfileUpdateRequest, user_id: str = Depends(get_current_user)
):
    try:
        await update_profile_async(request.updates, user_id)
        return {"status": "success"}
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/add_api_key")
async def api_add_api_key(
    request: ApiKeyRequest, user_id: str = Depends(get_current_user)
):
    if await Database.add_api_key_async(request.key_name, request.api_key):
        return {"status": "success", "message": f"{request.key_name} API key added"}
    else:
        return {
            "status": "error",
            "message": "API key already exists or failed to save",
        }


@router.post("/add_chutes_key")
async def api_add_chutes_key(
    request: ChutesKeyRequest, user_id: str = Depends(get_current_user)
):
    try:
        if await Database.add_api_key_async("chutes", request.api_key.strip()):
            return {
                "status": "success",
                "message": "Chutes API key added successfully!",
            }
        else:
            return {"status": "error", "message": "Failed to save Chutes API key"}
    except Exception as e:
        log.error("Error adding Chutes API key: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/remove_api_key")
async def api_remove_api_key(
    request: ApiKeyRemoveRequest, user_id: str = Depends(get_current_user)
):
    try:
        if await Database.remove_api_key_async(request.key_name):
            return {
                "status": "success",
                "message": f"{request.key_name} API key removed",
            }
        else:
            return {"status": "error", "message": "API key not found"}
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/providers/list")
async def api_list_providers(user_id: str = Depends(get_current_user)):
    try:
        ai_manager = await get_ai_manager()
        available_providers = ai_manager.get_available_providers()
        all_models = await ai_manager.get_all_models()

        profile = await Database.get_profile_async(user_id)
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
        log.error("Error listing providers: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/providers/set_preferred")
async def api_set_preferred_provider(
    request: ProviderSetRequest, user_id: str = Depends(get_current_user)
):
    try:
        result = await ConfigService.set_preferred_provider_async(
            user_id, request.provider_name, request.model_name
        )
        return {"status": "success", "message": result}
    except Exception as e:
        log.error("Error setting preferred provider: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/providers/test_connection")
async def api_test_provider_connection(
    request: ProviderTestRequest, user_id: str = Depends(get_current_user)
):
    try:
        ai_manager = await get_ai_manager()
        provider = ai_manager.providers.get(request.provider_name)
        if not provider:
            return {
                "status": "error",
                "message": f"Provider {request.provider_name} not found",
            }
        is_connected = await provider.test_connection()
        return {
            "status": "success",
            "provider": request.provider_name,
            "connected": is_connected,
            "message": f"{request.provider_name}: {'Connected' if is_connected else 'Connection failed'}",
        }
    except Exception as e:
        log.error("Error testing provider connection: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/get_vision_capabilities")
async def api_get_vision_capabilities(user_id: str = Depends(get_current_user)):
    try:
        capabilities = ConfigService.get_vision_capabilities()
        return {"status": "success", "capabilities": capabilities}
    except Exception as e:
        log.error("Error getting vision capabilities: %s - %s", type(e).__name__, e)
        raise HTTPException(status_code=500, detail="Failed to get vision capabilities")


@router.post("/providers/set_vision_model")
async def api_set_vision_model(
    request: VisionModelSetRequest, user_id: str = Depends(get_current_user)
):
    try:
        result = await ConfigService.set_vision_model_async(
            user_id, request.provider, request.model
        )
        return {"status": "success", "message": result}
    except Exception as e:
        log.error("Error setting vision model: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/providers/test_vision")
async def api_test_vision(user_id: str = Depends(get_current_user)):
    return {"status": "success", "message": "Vision model test successful"}


@router.post("/update_location")
async def api_update_location(
    request: LocationUpdateRequest, user_id: str = Depends(get_current_user)
):
    try:
        context = await Database.get_context_async(user_id)
        context["location"] = {"lat": request.lat, "lon": request.lon}
        await Database.update_context_async(context, user_id)
        return {"status": "success", "message": "Location updated"}
    except Exception as e:
        log.error("Error updating location: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/update_weather_location")
async def api_update_weather_location(
    request: LocationUpdateRequest, user_id: str = Depends(get_current_user)
):
    """Alias for update_location to maintain compatibility."""
    return await api_update_location(request, user_id)


@router.post("/global_knowledge/update")
async def api_update_global_knowledge(
    request: GlobalKnowledgeUpdateRequest, user_id: str = Depends(get_current_user)
):
    try:
        global_knowledge = {"facts": request.facts}
        await Database.update_profile_async(
            {"global_knowledge": global_knowledge}, user_id
        )
        return {"status": "success", "message": "Global knowledge updated"}
    except Exception as e:
        log.error("Error updating global knowledge: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")
