from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.db import Database, get_api_keys
from app.providers import get_ai_manager, reload_ai_manager

logger = logging.getLogger(__name__)

class ConfigService:
    @staticmethod
    def get_vision_capabilities() -> dict[str, Any]:
        from app.tools import multimodal_tools

        capabilities: dict[str, Any] = {
            "has_vision": False,
            "vision_provider": None,
            "vision_model": None,
            "has_image_generation": False,
            "image_generation_provider": None,
        }

        vision_provider, vision_model = multimodal_tools.get_best_vision_provider()
        if vision_provider:
            capabilities["has_vision"] = True
            capabilities["vision_provider"] = vision_provider
            capabilities["vision_model"] = vision_model

        if "openrouter" in (get_api_keys() or {}):
            capabilities["has_image_generation"] = True
            capabilities["image_generation_provider"] = "openrouter"

        return capabilities

    @staticmethod
    def get_ai_providers_payload(profile: dict | None = None) -> dict[str, Any]:
        if profile is None:
            profile = Database.get_profile()
        
        ai_manager = get_ai_manager()
        providers_config = profile.get("providers_config", {})
        
        return {
            "available_providers": ai_manager.get_available_providers(),
            "all_models": ai_manager.get_all_models(),
            "current_provider": providers_config.get("preferred_provider", "ollama"),
            "current_model": providers_config.get("preferred_model", "glm-4.6:cloud"),
        }

    @staticmethod
    def get_vision_payload(profile: dict | None = None) -> dict[str, Any]:
        if profile is None:
            profile = Database.get_profile()
            
        from app.tools.multimodal import multimodal_tools
        
        vision_capabilities = ConfigService.get_vision_capabilities()
        providers_config = profile.get("providers_config", {})
        vision_prefs = providers_config.get("vision_model_preferences", {})

        vision_models_by_provider = {}
        for provider in ["chutes", "openrouter"]:
            vision_models_by_provider[provider] = (
                multimodal_tools.get_available_vision_models(provider)
            )

        return {
            "capabilities": vision_capabilities,
            "models_by_provider": vision_models_by_provider,
            "current_provider": vision_prefs.get("provider"),
            "current_model": vision_prefs.get("model"),
        }

    @staticmethod
    def get_frontend_config() -> dict[str, Any]:
        """Unified frontend configuration for web and CLI."""
        profile = Database.get_profile()
        return {
            "status": "success",
            "ai_providers": ConfigService.get_ai_providers_payload(profile),
            "vision": ConfigService.get_vision_payload(profile),
        }

    @staticmethod
    def format_profile_dict(profile: dict) -> dict[str, Any]:
        """Format raw profile row into a frontend-friendly dictionary."""
        return {
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
            "created_at": profile["created_at"].isoformat() if profile.get("created_at") else None,
            "updated_at": profile["updated_at"].isoformat() if profile.get("updated_at") else None,
        }

    @staticmethod
    def set_preferred_provider(provider_name: str, model_name: str | None = None) -> str:
        profile = Database.get_profile()
        config = profile.get("providers_config") or {}
        config["preferred_provider"] = provider_name
        if model_name:
            config["preferred_model"] = model_name
        Database.update_profile({"providers_config": config})
        reload_ai_manager()

        suffix = f" with model: {model_name}" if model_name else ""
        return f"Preferred provider set to: {provider_name}{suffix}"

    @staticmethod
    def set_vision_model(provider: str, model: str) -> str:
        profile = Database.get_profile()
        config = profile.get("providers_config") or {}
        config["vision_model_preferences"] = {"provider": provider, "model": model}
        Database.update_profile({"providers_config": config})
        return f"Vision model set to: {provider}/{model}"
