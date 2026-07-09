from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from app.core.context import get_request_keyring


@dataclass
class LLMContext:
    """
    Single Source of Truth (SSOT) for the runtime configuration of an LLM request.
    Contains the fully resolved provider, model, credentials, and parameters.
    """

    provider: str
    model: str
    vision_provider: str | None = None
    vision_model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_profile(
        cls,
        profile: dict[str, Any],
        override_provider: str | None = None,
        override_model: str | None = None,
    ) -> "LLMContext":
        """
        Build the LLMContext by merging User Preferences (from DB profile)
        with User Credentials (from BYOK RequestKeyring) and App Config (env vars).
        """
        config = profile.get("providers_config") or {}

        # 1. Base provider/model from profile or overrides
        provider = override_provider or config.get("preferred_provider", "ollama")
        model = override_model or config.get("preferred_model", "glm-4.6:cloud")

        # 2. Vision preferences
        vision_prefs = config.get("vision_model_preferences") or {}
        vision_provider = vision_prefs.get("provider")
        vision_model = vision_prefs.get("model")

        # 3. Credential and Runtime Resolution (BYOK -> Env)
        keyring = get_request_keyring(provider)
        api_key = None
        base_url = None

        if keyring and keyring.key:
            api_key = keyring.key
        else:
            api_key = os.environ.get(f"{provider.upper()}_API_KEY")

        if keyring and keyring.base_url:
            base_url = keyring.base_url
        else:
            base_url = os.environ.get(f"{provider.upper()}_BASE_URL")

        if keyring and keyring.model_id:
            model = keyring.model_id

        # 4. Parameters (temperature, etc.) pulled from profile context
        ctx_data = profile.get("context") or {}
        parameters = {}
        if "temperature" in ctx_data:
            parameters["temperature"] = float(ctx_data["temperature"])
        if "top_p" in ctx_data:
            parameters["top_p"] = float(ctx_data["top_p"])
        if "max_tokens" in ctx_data:
            parameters["max_tokens"] = int(ctx_data["max_tokens"])
        if "top_k" in ctx_data:
            parameters["top_k"] = int(ctx_data["top_k"])
        if "additional_instructions" in ctx_data:
            parameters["additional_instructions"] = str(
                ctx_data["additional_instructions"] or ""
            )

        return cls(
            provider=provider,
            model=model,
            vision_provider=vision_provider,
            vision_model=vision_model,
            api_key=api_key,
            base_url=base_url,
            parameters=parameters,
        )
