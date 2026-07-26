from __future__ import annotations

from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.utils import get_current_user
from app.db import (
    Database,
    get_active_session_async,
    get_chat_history_async,
    get_profile_async,
    update_profile_async,
)
from app.logging_config import get_logger
from app.providers import get_ai_manager
from app.services.config_service import ConfigService

log = get_logger(__name__)

router = APIRouter(tags=["profile"])


class ProviderSetRequest(BaseModel):
    provider_name: str = Field(..., min_length=1, description="AI provider name")
    model_name: str | None = Field(None, description="Optional model name")


class ProviderTestRequest(BaseModel):
    provider_name: str = Field(..., min_length=1, description="Provider name to test")


class VisionModelSetRequest(BaseModel):
    provider: str = Field(..., min_length=1, description="Vision provider name")
    model: str = Field(..., min_length=1, description="Vision model name")


class LocationUpdateRequest(BaseModel):
    lat: float | None = Field(None, ge=-90, le=90, description="Latitude")
    lon: float | None = Field(None, ge=-180, le=180, description="Longitude")


class ProfileUpdateRequest(BaseModel):
    updates: dict = Field(..., description="Key-value pairs for profile updates")


class GlobalKnowledgeEntryCreateRequest(BaseModel):
    category: str = Field("General", min_length=1, max_length=255)
    content: str = Field(..., min_length=1, max_length=10000)
    sort_order: int = Field(0, ge=0)
    enabled: bool = True


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
        chat_history = await get_chat_history_async(
            session_id=session_id, limit=50, recent=True, user_id=user_id
        )

        profile_dict = ConfigService.format_profile_dict(profile)
        ai_providers_payload = await ConfigService.get_ai_providers_payload(
            user_id, profile
        )
        vision_capabilities = ConfigService.get_vision_capabilities()

        return {
            **profile_dict,
            "chat_history": chat_history,
            "active_session": active_session,
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
        updates = request.updates

        # Intercept fields that belong in context
        context_keys = [
            "persona_preset",
            "persona_prompt",
            "temperature",
            "top_p",
            "max_tokens",
            "top_k",
            "additional_instructions",
            "history_limit",
            "enable_reasoning",
            "enable_vision",
        ]

        context_updates = {}
        for key in context_keys:
            if key in updates:
                context_updates[key] = updates.pop(key)

        if context_updates:
            # Fetch current profile to get existing context
            profile = await get_profile_async(user_id)
            ctx = profile.get("context") or {}
            ctx.update(context_updates)
            updates["context"] = ctx

        await update_profile_async(updates, user_id)
        return {"status": "success"}
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/providers/list")
async def api_list_providers(user_id: str = Depends(get_current_user)):
    try:
        ai_manager = await get_ai_manager()
        available_providers = ai_manager.get_available_providers()
        all_models = await ai_manager.get_all_models()

        profile = await Database.get_profile(user_id)
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


@router.get("/proxy/models/{provider}")
async def api_proxy_models(
    provider: str, request: Request, user_id: str = Depends(get_current_user)
):
    try:
        api_key = request.headers.get("X-Provider-Key", "")
        base_url = request.headers.get("X-Provider-BaseUrl", "")

        url = ""
        if provider == "openrouter":
            url = "https://openrouter.ai/api/v1/models"
        elif provider == "openai":
            url = "https://api.openai.com/v1/models"
        elif provider.startswith("custom") and base_url:
            # Strip trailing path segments to get the base directory
            if "/chat/completions" in base_url:
                base_dir = base_url.split("/chat/completions")[0]
            elif "/v1/messages" in base_url:
                base_dir = base_url.split("/v1/messages")[0]
            elif base_url.rstrip("/").endswith("/v1"):
                base_dir = base_url.rstrip("/")
            else:
                base_dir = base_url.rstrip("/")
            url = f"{base_dir}/models"

        if url:
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(url, headers=headers, timeout=10.0)
                    if resp.status_code == 200:
                        data = resp.json()
                        models = [
                            m.get("id") for m in data.get("data", []) if m.get("id")
                        ]
                        if models:
                            return {"status": "success", "models": models}
            except Exception as e:
                log.warning("Failed to fetch models from %s: %s", url, e)

        # Fallback: custom providers get dummy models so the UI is not stuck
        if provider.startswith("custom"):
            return {"status": "success", "models": ["custom-model-1", "custom-model-2"]}

        return {"status": "error", "message": "Could not fetch models"}

    except Exception as e:
        log.error("Error in proxy models: %s", e)
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
    request: Request,
    payload: ProviderTestRequest,
    user_id: str = Depends(get_current_user),
):
    try:
        from app.api.endpoints.chat import _extract_keyrings
        from app.core.context import clear_request_keyring, set_request_keyrings

        keyrings = _extract_keyrings(request)
        if keyrings:
            set_request_keyrings(keyrings)

        try:
            ai_manager = await get_ai_manager()
            provider = ai_manager.providers.get(payload.provider_name)
            if not provider:
                return {
                    "status": "error",
                    "message": f"Provider {payload.provider_name} not found",
                }
            is_connected = await provider.test_connection()
            return {
                "status": "success",
                "provider": payload.provider_name,
                "connected": is_connected,
                "message": f"{payload.provider_name}: {'Connected' if is_connected else 'Connection failed'}",
            }
        finally:
            if keyrings:
                clear_request_keyring()
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


@router.post("/update_location")
async def api_update_location(
    request: LocationUpdateRequest, user_id: str = Depends(get_current_user)
):
    try:
        profile = await Database.get_profile(user_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")

        if (request.lat is None) != (request.lon is None):
            raise HTTPException(
                status_code=422,
                detail="Latitude and longitude must be provided together",
            )

        updates = {"location_lat": request.lat, "location_lon": request.lon}
        await Database.update_profile(updates, user_id)
        return {
            "status": "success",
            "message": "Location cleared" if request.lat is None else "Location updated",
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error("Error updating location: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/global-knowledge")
async def api_list_global_knowledge(user_id: str = Depends(get_current_user)):
    return {"entries": await ConfigService.get_global_knowledge_async(user_id)}


@router.post("/global-knowledge", status_code=201)
async def api_create_global_knowledge(
    request: GlobalKnowledgeEntryCreateRequest,
    user_id: str = Depends(get_current_user),
):
    entry = await Database.create_global_knowledge(
        category=request.category.strip(),
        content=request.content.strip(),
        sort_order=request.sort_order,
        enabled=request.enabled,
        user_id=user_id,
    )
    return {"entry": entry}


@router.patch("/global-knowledge/{entry_id}")
async def api_update_global_knowledge_entry(
    entry_id: UUID,
    request: GlobalKnowledgeEntryCreateRequest,
    user_id: str = Depends(get_current_user),
):
    entry = await Database.update_global_knowledge(
        entry_id=str(entry_id),
        category=request.category.strip(),
        content=request.content.strip(),
        sort_order=request.sort_order,
        enabled=request.enabled,
        user_id=user_id,
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Global Knowledge entry not found")
    return {"entry": entry}


@router.delete("/global-knowledge/{entry_id}", status_code=204)
async def api_delete_global_knowledge(
    entry_id: UUID, user_id: str = Depends(get_current_user)
):
    deleted = await Database.delete_global_knowledge(str(entry_id), user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Global Knowledge entry not found")
