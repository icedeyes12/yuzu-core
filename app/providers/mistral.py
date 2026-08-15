from __future__ import annotations

from typing import Any

import httpx

from app.core.context import MissingProviderKeyError, get_request_keyring
from app.providers.custom_openai import CustomOpenAIProvider


def _normalize_mistral_model(record: dict[str, Any]) -> dict[str, Any]:
    capabilities = record.get("capabilities")
    capabilities = capabilities if isinstance(capabilities, dict) else {}
    metadata: dict[str, Any] = {"id": record.get("id")}
    max_context = record.get("max_context_length")
    if isinstance(max_context, int):
        metadata["context_length"] = max_context
    if capabilities.get("vision") is True:
        metadata["input_modalities"] = ["text", "image"]
    elif capabilities.get("vision") is False:
        metadata["input_modalities"] = ["text"]
    if capabilities.get("function_calling") is True:
        metadata["supported_parameters"] = ["tools", "tool_choice"]
    if capabilities.get("reasoning") is True:
        metadata["reasoning_mode"] = "provider-specific"
    elif capabilities.get("reasoning") is False:
        metadata["reasoning_mode"] = "unsupported"
    return metadata


class MistralProvider(CustomOpenAIProvider):
    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.name = "mistral"
        self.base_url = "https://api.mistral.ai/v1/chat/completions"
        self.models_url = "https://api.mistral.ai/v1/models"
        self.available_models: list[str] = []

    async def fetch_live_models(
        self, api_key: str | None = None, base_url: str | None = None
    ) -> list[str]:
        keyring = get_request_keyring("mistral")
        api_key = api_key or (keyring.key if keyring else None)
        if not api_key:
            raise MissingProviderKeyError("mistral")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.models_url,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10.0,
            )
        response.raise_for_status()
        records = [
            item for item in response.json().get("data", []) if isinstance(item, dict)
        ]
        self.set_model_metadata(
            [_normalize_mistral_model(record) for record in records]
        )
        self.available_models = sorted(
            {item["id"] for item in records if isinstance(item.get("id"), str)}
        )
        return self.available_models

    async def get_models(self) -> list[str]:
        return self.available_models


__all__ = ["MistralProvider"]
