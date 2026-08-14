from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.byok import DEFAULT_YUZU_PORTAL_BASE_URL, YUZU_PORTAL
from app.core.context import ConfigurationRequiredError, get_request_keyring


@dataclass
class LLMContext:
    """
    Single Source of Truth (SSOT) for the runtime configuration of an LLM request.
    Contains the fully resolved provider, model, credentials, and parameters.
    """

    provider: str | None
    model: str | None
    api_key: str | None = None
    base_url: str | None = None
    chat_session_id: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_profile(
        cls,
        profile: dict[str, Any],
    ) -> LLMContext:
        """
        Build the LLMContext by merging User Preferences (from DB profile)
        with user credentials from the request keyring.
        """
        config = profile.get("providers_config") or {}

        # 1. Base provider/model from user profile
        provider = config.get("preferred_provider")
        model = config.get("preferred_model")

        # 2. Credential and endpoint resolution
        keyring = get_request_keyring(provider) if provider else None
        api_key = keyring.key if keyring else None
        base_url = (
            DEFAULT_YUZU_PORTAL_BASE_URL
            if provider == YUZU_PORTAL
            else keyring.base_url
            if keyring
            else None
        )

        # 4. Parameters (temperature, etc.) pulled from profile model_parameters.
        #
        # Preset payload wins over loose model_parameters when an active preset is
        # present. This is the only path the runtime uses; there is no
        # fallback to loose model_parameters when a preset is active. Without this
        # precedence, the same preset would not produce a reproducible
        # payload, which violates the persistence contract.
        from app.core.presets import (
            PRESET_PAYLOAD_KEYS,
            resolve_active_preset_payload,
        )

        model_parameters_data = profile.get("model_parameters") or {}
        active_payload = resolve_active_preset_payload(model_parameters_data)
        effective_parameters = (
            active_payload if active_payload is not None else model_parameters_data
        )

        parameters: dict[str, Any] = {}
        if effective_parameters.get("temperature") is not None:
            parameters["temperature"] = float(effective_parameters["temperature"])
        if effective_parameters.get("top_p") is not None:
            parameters["top_p"] = float(effective_parameters["top_p"])
        if effective_parameters.get("max_tokens") is not None:
            parameters["max_tokens"] = int(effective_parameters["max_tokens"])
        if effective_parameters.get("top_k") is not None:
            parameters["top_k"] = int(effective_parameters["top_k"])
        if "additional_instructions" in effective_parameters:
            parameters["additional_instructions"] = str(
                effective_parameters["additional_instructions"] or ""
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
            api_key=api_key,
            base_url=base_url,
            parameters=parameters,
        )

    def require_configured(self) -> LLMContext:
        """(｡•̀ᴗ-)✧"""
        if not self.provider:
            raise ConfigurationRequiredError("preferred_provider")
        if not self.model:
            raise ConfigurationRequiredError("preferred_model")
        return self
