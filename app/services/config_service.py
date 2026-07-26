from __future__ import annotations

import logging
from typing import Any

from app.db import Database
from app.providers import get_ai_manager, reload_ai_manager

logger = logging.getLogger(__name__)


class ConfigService:
    @staticmethod
    async def get_ai_providers_payload(
        user_id: str, profile: dict | None = None
    ) -> dict[str, Any]:
        if profile is None:
            profile = await Database.get_profile(user_id)

        ai_manager = await get_ai_manager()
        providers_config = profile.get("providers_config", {})

        return {
            "available_providers": ai_manager.get_available_providers(),
            "all_models": await ai_manager.get_all_models(),
            "current_provider": providers_config.get("preferred_provider"),
            "current_model": providers_config.get("preferred_model"),
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
            "vision": await ConfigService.get_vision_payload_async(user_id, profile),
            "all_models": ai_providers["all_models"],
            "current_provider": ai_providers["current_provider"],
            "current_model": ai_providers["current_model"],
        }

    @staticmethod
    async def get_global_knowledge_async(user_id: str) -> list[dict[str, Any]]:
        return await Database.list_global_knowledge(user_id=user_id)

    @staticmethod
    async def get_vision_payload_async(
        user_id: str, profile: dict | None = None
    ) -> dict[str, Any]:
        if profile is None:
            profile = await Database.get_profile(user_id)

        ai_manager = await get_ai_manager()
        capabilities = ai_manager.get_all_provider_capabilities()
        models = await ai_manager.get_all_models()
        vision_capabilities = {
            provider: metadata
            for provider, metadata in capabilities.items()
            if metadata.get("supports_vision")
        }
        providers_config = profile.get("providers_config", {})
        vision_prefs = providers_config.get("vision_model_preferences") or {}

        return {
            "capabilities": vision_capabilities,
            "models_by_provider": {
                provider: models.get(provider, []) for provider in vision_capabilities
            },
            "current_provider": vision_prefs.get("provider"),
            "current_model": vision_prefs.get("model"),
        }

    @staticmethod
    def format_profile_dict(profile: dict) -> dict[str, Any]:
        """Format raw profile row into a frontend-friendly dictionary."""
        ctx = profile.get("context") or {}
        return {
            "id": profile["id"],
            "user_name": profile["user_name"],
            "partner_name": profile["partner_name"],
            "affection": profile["affection"],
            "theme": profile["theme"],
            "session_history": profile["session_history"],
            "providers_config": profile["providers_config"],
            "context": ctx,
            "image_model": profile["image_model"],
            "image_provider": profile.get("image_provider"),
            "vision_model": profile["vision_model"],
            "image_edit_provider": profile.get("image_edit_provider"),
            "image_endpoint": profile.get("image_endpoint"),
            "image_edit_endpoint": profile.get("image_edit_endpoint"),
            "vision_model_preferences": profile.get("providers_config", {}).get(
                "vision_model_preferences", {}
            ),
            "created_at": profile["created_at"].isoformat()
            if profile.get("created_at")
            else None,
            "updated_at": profile["updated_at"].isoformat()
            if profile.get("updated_at")
            else None,
            "persona_preset": ctx.get("persona_preset"),
            "persona_prompt": ctx.get("persona_prompt"),
            "temperature": ctx.get("temperature"),
            "top_p": ctx.get("top_p"),
            "max_tokens": ctx.get("max_tokens"),
            "top_k": ctx.get("top_k"),
            "additional_instructions": ctx.get("additional_instructions") or "",
            "presets": ctx.get("presets") or [],
            "active_preset": ctx.get("active_preset"),
            "history_limit": ctx.get("history_limit"),
            "enable_reasoning": ctx.get("enable_reasoning"),
            "enable_vision": ctx.get("enable_vision"),
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
                models = await ai_manager.get_provider_models(provider_name)
                if model_name not in models:
                    raise ValueError(
                        f"Model '{model_name}' is not available for provider '{provider_name}'"
                    )

        profile = await Database.get_profile(user_id)
        config = dict(profile.get("providers_config") or {})
        config["preferred_provider"] = provider_name
        if model_name:
            config["preferred_model"] = model_name
        else:
            config.pop("preferred_model", None)
        await Database.update_profile({"providers_config": config}, user_id)
        await reload_ai_manager()

        suffix = f" with model: {model_name}" if model_name else ""
        return f"Preferred provider set to: {provider_name}{suffix}"

    @staticmethod
    async def set_vision_model_async(user_id: str, provider: str, model: str) -> str:
        """Async version for web API endpoints."""
        profile = await Database.get_profile(user_id)
        config = profile.get("providers_config") or {}
        config["vision_model_preferences"] = {"provider": provider, "model": model}
        await Database.update_profile({"providers_config": config}, user_id)
        return f"Vision model set to: {provider}/{model}"
