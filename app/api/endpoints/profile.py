from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.models import (
    ERROR_RESPONSES,
    ConfigResponse,
    KnowledgeEntryResponse,
    KnowledgeListResponse,
    ModelsResponse,
    ProfileResponse,
    ProviderListResponse,
    ProviderTestResponse,
    StatusResponse,
)
from app.api.rate_limits import rate_limit_user
from app.api.utils import (
    extract_keyrings,
    get_current_user,
    validate_external_https_url,
)
from app.core.context import keyring_scope
from app.core.logging_config import get_logger
from app.db import (
    Database,
    get_active_session_async,
    get_chat_history_async,
    get_profile_async,
    update_profile_async,
)
from app.providers import get_ai_manager
from app.services.config_service import ConfigService

log = get_logger(__name__)

router = APIRouter(tags=["profile"])


class ProviderSetRequest(BaseModel):
    provider_name: str = Field(..., min_length=1, description="AI provider name")
    model_name: str | None = Field(None, description="Optional model name")


class ProviderTestRequest(BaseModel):
    provider_name: str = Field(..., min_length=1, description="Provider name to test")


class LocationUpdateRequest(BaseModel):
    lat: float | None = Field(None, ge=-90, le=90, description="Latitude")
    lon: float | None = Field(None, ge=-180, le=180, description="Longitude")


class ProfileUpdateFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_name: str | None = Field(None, max_length=255)
    partner_name: str | None = Field(None, max_length=255)
    affection: int | None = Field(None, ge=0, le=100)
    theme: str | None = Field(None, max_length=255)
    image_model: str | None = Field(None, max_length=255)
    image_provider: str | None = Field(None, max_length=255)
    image_edit_provider: str | None = Field(None, max_length=255)
    image_endpoint: str | None = Field(None, max_length=2048)
    image_edit_endpoint: str | None = Field(None, max_length=2048)
    image_extra_body: dict[str, Any] | None = None
    image_edit_extra_body: dict[str, Any] | None = None
    location_lat: float | None = Field(None, ge=-90, le=90)
    location_lon: float | None = Field(None, ge=-180, le=180)
    personality_preset: str | None = Field(None, max_length=64)
    personality_custom: str | None = Field(None, max_length=10000)
    character_profile: str | None = Field(None, max_length=10000)
    temperature: float | None = Field(None, ge=0, le=2)
    top_p: float | None = Field(None, ge=0, le=1)
    max_tokens: int | None = Field(None, ge=1, le=200000)
    top_k: int | None = Field(None, ge=0, le=1000)
    additional_instructions: str | None = Field(None, max_length=10000)
    history_limit: int | None = Field(None, ge=1, le=1000)
    enable_reasoning: bool | None = None
    enable_vision: bool | None = None


class ProfileUpdateRequest(BaseModel):
    updates: ProfileUpdateFields = Field(
        ..., description="Validated profile fields to update"
    )


class GlobalKnowledgeEntryCreateRequest(BaseModel):
    category: str = Field("General", min_length=1, max_length=255)
    content: str = Field(..., min_length=1, max_length=10000)
    sort_order: int = Field(0, ge=0)
    enabled: bool = True


@router.get("/config", response_model=ConfigResponse, responses=ERROR_RESPONSES)
async def api_get_config(user_id: str = Depends(get_current_user)):
    """Single source of truth for frontend configuration."""
    try:
        return await ConfigService.get_frontend_config(user_id)
    except Exception as e:
        log.error("Error getting config: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/profile", response_model=ProfileResponse, responses=ERROR_RESPONSES)
async def api_get_profile(
    session_id: str | None = None, user_id: str = Depends(get_current_user)
):
    try:
        profile = await get_profile_async(user_id)
        if session_id is None:
            active_session = await get_active_session_async(user_id)
        else:
            active_session = {"id": session_id}
        session_id = str(active_session["id"])
        chat_history = await get_chat_history_async(
            session_id=session_id, limit=50, recent=True, user_id=user_id
        )

        profile_dict = ConfigService.format_profile_dict(profile)
        ai_providers_payload = await ConfigService.get_ai_providers_payload(
            user_id, profile
        )
        return {
            **profile_dict,
            "chat_history": chat_history,
            "active_session": active_session,
            "ai_providers": ai_providers_payload,
        }
    except Exception as e:
        log.error("Error in api_get_profile: %s", e)
        raise HTTPException(status_code=500, detail="Failed to load profile")


@router.post(
    "/update_profile", response_model=StatusResponse, responses=ERROR_RESPONSES
)
async def api_update_profile(
    request: ProfileUpdateRequest, user_id: str = Depends(get_current_user)
):
    try:
        updates = request.updates.model_dump(exclude_unset=True)

        # Intercept fields that belong in model_parameters
        model_parameter_keys = [
            "personality_preset",
            "personality_custom",
            "character_profile",
            "temperature",
            "top_p",
            "max_tokens",
            "top_k",
            "additional_instructions",
            "history_limit",
            "enable_reasoning",
            "enable_vision",
        ]

        model_parameter_updates = {}
        for key in model_parameter_keys:
            if key in updates:
                model_parameter_updates[key] = updates.pop(key)

        if model_parameter_updates:
            # Fetch current profile to get existing model_parameters
            profile = await get_profile_async(user_id)
            model_parameters = profile.get("model_parameters") or {}
            _ = model_parameters.update(model_parameter_updates)
            updates["model_parameters"] = model_parameters

        _ = await update_profile_async(updates, user_id)
        return {"status": "success"}
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/providers/list", response_model=ProviderListResponse, responses=ERROR_RESPONSES
)
async def api_list_providers(user_id: str = Depends(get_current_user)):
    try:
        ai_manager = await get_ai_manager()
        available_providers = ai_manager.get_available_providers()
        all_models = await ai_manager.get_all_models()
        model_infos = await ai_manager.get_all_model_infos()

        profile = await Database.get_profile(user_id)
        providers_config = profile.get("providers_config", {})
        current_provider = providers_config.get("preferred_provider")
        current_model = providers_config.get("preferred_model")

        return {
            "status": "success",
            "available_providers": available_providers,
            "all_models": all_models,
            "current_provider": current_provider,
            "current_model": current_model,
            "model_infos": model_infos,
        }
    except Exception as e:
        log.error("Error listing providers: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/proxy/models/{provider}",
    include_in_schema=False,
    response_model=ModelsResponse,
    responses=ERROR_RESPONSES,
)
async def api_proxy_models(
    provider: str, request: Request, _user_id: str = Depends(get_current_user)
):
    rate_limit_user(_user_id, 10, "proxy-models-user")
    try:
        ai_manager = await get_ai_manager()
        if provider not in ai_manager.get_available_providers():
            raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
        base_url = request.headers.get("X-Provider-BaseUrl")
        if base_url:
            base_url = validate_external_https_url(base_url)
        models, model_infos = await ai_manager.discover_provider_models(
            provider,
            api_key=request.headers.get("X-Provider-Key"),
            base_url=base_url,
        )
        return {"status": "success", "models": models, "model_infos": model_infos}

    except HTTPException:
        raise
    except Exception as e:
        log.error("Error in proxy models: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post(
    "/proxy/models/{provider}/refresh",
    include_in_schema=False,
    response_model=ModelsResponse,
    responses=ERROR_RESPONSES,
)
async def api_refresh_provider_models(
    provider: str, request: Request, _user_id: str = Depends(get_current_user)
):
    rate_limit_user(_user_id, 10, "proxy-models-user")
    ai_manager = await get_ai_manager()
    provider_instance = ai_manager.providers.get(provider)
    if provider_instance is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")

    try:
        provider_instance.clear_model_metadata()
        base_url = request.headers.get("X-Provider-BaseUrl")
        if base_url:
            base_url = validate_external_https_url(base_url)
        models, model_infos = await ai_manager.discover_provider_models(
            provider,
            api_key=request.headers.get("X-Provider-Key"),
            base_url=base_url,
        )
        if not models:
            raise HTTPException(status_code=502, detail="Provider returned no models")
        return {
            "status": "success",
            "models": models,
            "model_infos": model_infos,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error("Error refreshing models for %s: %s", provider, e)
        raise HTTPException(
            status_code=502, detail="Could not refresh provider models"
        ) from e


@router.post(
    "/providers/set_preferred", response_model=StatusResponse, responses=ERROR_RESPONSES
)
async def api_set_preferred_provider(
    request: ProviderSetRequest, user_id: str = Depends(get_current_user)
):
    try:
        result = await ConfigService.set_preferred_provider_async(
            user_id, request.provider_name, request.model_name
        )
        return {"status": "success", "message": result}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        log.error("Error setting preferred provider: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post(
    "/providers/test_connection",
    include_in_schema=False,
    response_model=ProviderTestResponse,
    responses=ERROR_RESPONSES,
)
async def api_test_provider_connection(
    request: Request,
    payload: ProviderTestRequest,
    _user_id: str = Depends(get_current_user),
):
    rate_limit_user(_user_id, 5, "provider-test-user")
    try:
        async with keyring_scope(extract_keyrings(request)):
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
    except Exception as e:
        log.error("Error testing provider connection: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/update_location", response_model=StatusResponse, responses=ERROR_RESPONSES
)
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
            "message": "Location cleared"
            if request.lat is None
            else "Location updated",
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error("Error updating location: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/global-knowledge", response_model=KnowledgeListResponse, responses=ERROR_RESPONSES
)
async def api_list_global_knowledge(user_id: str = Depends(get_current_user)):
    return {"entries": await ConfigService.get_global_knowledge_async(user_id)}


@router.post(
    "/global-knowledge",
    status_code=201,
    response_model=KnowledgeEntryResponse,
    responses=ERROR_RESPONSES,
)
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


@router.put(
    "/global-knowledge/{entry_id}",
    response_model=KnowledgeEntryResponse,
    responses=ERROR_RESPONSES,
)
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


@router.delete(
    "/global-knowledge/{entry_id}",
    status_code=204,
    response_model=None,
    responses=ERROR_RESPONSES,
)
async def api_delete_global_knowledge(
    entry_id: UUID, user_id: str = Depends(get_current_user)
):
    deleted = await Database.delete_global_knowledge(str(entry_id), user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Global Knowledge entry not found")
