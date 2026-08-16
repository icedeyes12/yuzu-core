from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.byok import DEFAULT_YUZU_PORTAL_BASE_URL
from app.core.context import MissingProviderKeyError, get_request_keyring
from app.core.llm_context import LLMContext
from app.providers.custom_openai import CustomOpenAIProvider

DEFAULT_BASE_URL = DEFAULT_YUZU_PORTAL_BASE_URL


class YuzuPortalProvider(CustomOpenAIProvider):
    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.name = "yuzu_portal"
        self.base_url = f"{DEFAULT_BASE_URL}/chat/completions"
        self.available_models: list[str] = []
        self._models_cache_ttl = 600
        self._models_cache_at = 0.0
        self._models_cache_data: list[str] | None = None

    def _resolve_url(self, ctx: LLMContext) -> str:
        return f"{DEFAULT_BASE_URL.rstrip('/')}/chat/completions"

    async def get_models(self) -> list[str]:
        return self.available_models

    async def fetch_live_models(
        self, api_key: str | None = None, base_url: str | None = None
    ) -> list[str]:
        keyring = get_request_keyring("yuzu_portal")
        api_key = api_key or (keyring.key if keyring else None)
        if not api_key:
            raise MissingProviderKeyError("yuzu_portal")

        now = time.time()
        if (
            self._models_cache_data is not None
            and now - self._models_cache_at < self._models_cache_ttl
        ):
            return self._models_cache_data

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{DEFAULT_BASE_URL.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
        response.raise_for_status()
        metadata = [
            item for item in response.json().get("data", []) if isinstance(item, dict)
        ]
        self.set_model_metadata(metadata)
        models = sorted(
            {item["id"] for item in metadata if isinstance(item.get("id"), str)}
        )
        self._models_cache_data = models
        self._models_cache_at = now
        self.available_models = models
        return models
