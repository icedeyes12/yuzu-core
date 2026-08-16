from __future__ import annotations

from typing import Any

import httpx

from app.core.context import MissingProviderKeyError, get_request_keyring
from app.providers.custom_openai import CustomOpenAIProvider


class NvidiaNimProvider(CustomOpenAIProvider):
    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.name = "nvidia_nim"
        self.base_url = "https://integrate.api.nvidia.com/v1/chat/completions"
        self.models_url = "https://integrate.api.nvidia.com/v1/models"
        self.available_models: list[str] = []

    async def fetch_live_models(
        self, api_key: str | None = None, base_url: str | None = None
    ) -> list[str]:
        keyring = get_request_keyring("nvidia_nim")
        api_key = api_key or (keyring.key if keyring else None)
        if not api_key:
            raise MissingProviderKeyError("nvidia_nim")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.models_url,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10.0,
            )
        response.raise_for_status()
        metadata = [
            item for item in response.json().get("data", []) if isinstance(item, dict)
        ]
        self.set_model_metadata(metadata)
        self.available_models = sorted(
            {item["id"] for item in metadata if isinstance(item.get("id"), str)}
        )
        return self.available_models

    async def get_models(self) -> list[str]:
        return self.available_models


__all__ = ["NvidiaNimProvider"]
