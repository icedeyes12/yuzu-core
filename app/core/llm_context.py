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

    provider: str | None
    model: str | None
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
    ) -> LLMContext:
        """
        Build the LLMContext by merging User Preferences (from DB profile)
        with User Credentials (from BYOK RequestKeyring) and App Config (env vars).
        """
        config = profile.get("providers_config") or {}

        # 1. Base provider/model from profile or overrides
        provider = override_provider or config.get("preferred_provider")
        model = override_model or config.get("preferred_model")

        # 2. Vision preferences
        vision_prefs = config.get("vision_model_preferences") or {}
        vision_provider = vision_prefs.get("provider")
        vision_model = vision_prefs.get("model")

        # 3. Credential and Runtime Resolution (BYOK -> Env)
        keyring = get_request_keyring(provider) if provider else None
        api_key = None
        base_url = None

        if keyring and keyring.key:
            api_key = keyring.key
        else:
            api_key = os.environ.get(f"{provider.upper()}_API_KEY") if provider else None

        if keyring and keyring.base_url:
            base_url = keyring.base_url
        else:
            base_url = os.environ.get(f"{provider.upper()}_BASE_URL") if provider else None

        if keyring and keyring.model_id:
            model = keyring.model_id

        # 4. Parameters (temperature, etc.) pulled from profile context.
        #
        # Preset payload wins over loose context when an active preset is
        # present. This is the only path the runtime uses; there is no
        # fallback to loose context when a preset is active. Without this
        # precedence, the same preset would not produce a reproducible
        # payload, which violates the persistence contract.
        from app.core.presets import (
            PRESET_PAYLOAD_KEYS,
            resolve_active_preset_payload,
        )

        ctx_data = profile.get("context") or {}
        active_payload = resolve_active_preset_payload(ctx_data)
        effective_ctx = active_payload if active_payload is not None else ctx_data

        parameters: dict[str, Any] = {}
        if effective_ctx.get("temperature") is not None:
            parameters["temperature"] = float(effective_ctx["temperature"])
        if effective_ctx.get("top_p") is not None:
            parameters["top_p"] = float(effective_ctx["top_p"])
        if effective_ctx.get("max_tokens") is not None:
            parameters["max_tokens"] = int(effective_ctx["max_tokens"])
        if effective_ctx.get("top_k") is not None:
            parameters["top_k"] = int(effective_ctx["top_k"])
        if "additional_instructions" in effective_ctx:
            parameters["additional_instructions"] = str(
                effective_ctx["additional_instructions"] or ""
            )

        # Tag the active payload for downstream consumers (e.g. the
        # message builder) so they can reproduce the exact field set that
        # drove this request. Tests and audit logs use this marker.
        if active_payload is not None:
            parameters["_payload_source"] = "preset"
            parameters["_payload_keys"] = list(PRESET_PAYLOAD_KEYS)

        return cls(
            provider=provider,
            model=model,
            vision_provider=vision_provider,
            vision_model=vision_model,
            api_key=api_key,
            base_url=base_url,
            parameters=parameters,
        )
