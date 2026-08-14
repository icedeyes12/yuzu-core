from __future__ import annotations

import logging
from typing import Any, cast

from app.db import Database
from app.providers import get_ai_manager, reload_ai_manager

logger = logging.getLogger(__name__)


class ConfigService:
    @staticmethod
    async def get_ai_providers_payload(
        user_id: str, profile: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if profile is None:
            profile = await Database.get_profile(user_id)
        profile = cast(dict[str, Any], profile)

        ai_manager = await get_ai_manager()
        providers_config = cast(dict[str, Any], profile.get("providers_config") or {})

        return {
            "available_providers": ai_manager.get_available_providers(),
            "all_models": await ai_manager.get_all_models(),
            "current_provider": providers_config.get("preferred_provider"),
            "current_model": providers_config.get("preferred_model"),
            "model_infos": await ai_manager.get_all_model_infos(),
        }

    @staticmethod
    async def get_frontend_config(user_id: str) -> dict[str, Any]:
        """Unified frontend configuration for web and CLI."""
        profile = await Database.get_profile(user_id)
        ai_providers = await ConfigService.get_ai_providers_payload(user_id, profile)
        return {
            "status": "success",
            "profile": ConfigService.format_profile_dict(profile),
            "ai_providers": ai_providers,
            "all_models": ai_providers["all_models"],
            "current_provider": ai_providers["current_provider"],
            "current_model": ai_providers["current_model"],
            "model_infos": ai_providers["model_infos"],
        }

    @staticmethod
    async def get_global_knowledge_async(user_id: str) -> list[dict[str, Any]]:
        return await Database.list_global_knowledge(user_id=user_id)

    @staticmethod
    def format_profile_dict(profile: dict[str, Any]) -> dict[str, Any]:
        """Format raw profile row into a frontend-friendly dictionary."""
        model_parameters = profile.get("model_parameters") or {}
        return {
            "id": profile["id"],
            "user_name": profile["user_name"],
            "partner_name": profile["partner_name"],
            "affection": profile["affection"],
            "theme": profile["theme"],
            "session_history": profile["session_history"],
            "providers_config": profile["providers_config"],
            "model_parameters": model_parameters,
            "image_model": profile["image_model"],
            "created_at": profile["created_at"].isoformat()
            if profile.get("created_at")
            else None,
            "updated_at": profile["updated_at"].isoformat()
            if profile.get("updated_at")
            else None,
            "personality_preset": model_parameters.get("personality_preset")
            or "helpful",
            "personality_custom": model_parameters.get("personality_custom") or "",
            "character_profile": model_parameters.get("character_profile") or "",
            "temperature": model_parameters.get("temperature"),
            "top_p": model_parameters.get("top_p"),
            "max_tokens": model_parameters.get("max_tokens"),
            "top_k": model_parameters.get("top_k"),
            "additional_instructions": model_parameters.get("additional_instructions")
            or "",
            "presets": model_parameters.get("presets") or [],
            "active_preset": model_parameters.get("active_preset"),
            "history_limit": model_parameters.get("history_limit"),
            "enable_reasoning": model_parameters.get("enable_reasoning"),
            "enable_vision": model_parameters.get("enable_vision"),
            "location_lat": profile.get("location_lat"),
            "location_lon": profile.get("location_lon"),
        }

    @staticmethod
    async def set_preferred_provider_async(
        user_id: str, provider_name: str, model_name: str | None = None
    ) -> str:
        """Async version for web API endpoints."""
        provider_name = provider_name.strip()
        model_name = model_name.strip() if model_name else None
        if not provider_name:
            raise ValueError("Provider name is required")

        ai_manager = await get_ai_manager()
        if provider_name not in ai_manager.get_available_providers():
            raise ValueError(f"Unknown provider: {provider_name}")

        if model_name:
            if not provider_name.startswith("custom_"):
                # Warning: We no longer do strict model presence validation here.
                # Since we use BYOK (client-side keys), the backend may not have
                # a hydrated list of models via get_models() at save time.
                pass

        profile = await Database.get_profile(user_id)
        config = dict(profile.get("providers_config") or {})
        config["preferred_provider"] = provider_name
        if model_name:
            config["preferred_model"] = model_name
        else:
            config.pop("preferred_model", None)
        await Database.update_profile({"providers_config": config}, user_id)
        _ = await reload_ai_manager()

        suffix = f" with model: {model_name}" if model_name else ""
        return f"Preferred provider set to: {provider_name}{suffix}"
