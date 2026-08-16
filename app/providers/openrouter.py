from __future__ import annotations

from typing import Any

import httpx

from app.core.context import MissingProviderKeyError, get_request_keyring
from app.core.llm_context import LLMContext
from app.core.multimodal import multimodal_tools
from app.providers.base import ProviderCapabilities
from app.providers.custom_openai import OpenAICompatibleProvider


class OpenRouterProvider(OpenAICompatibleProvider):
    log_prefix: str = "OpenRouter"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__("openrouter", config)
        self.base_url: str = "https://openrouter.ai/api/v1/chat/completions"
        self.capabilities: ProviderCapabilities = ProviderCapabilities(
            supports_native_fc=True,
            supports_streaming_fc=True,
            supports_tool_call_parsing=True,
            supports_structured_system_content=True,
            supports_vision=True,
        )

    async def fetch_live_models(self, api_key: str | None = None) -> list[str]:
        """Fetch the canonical model list from OpenRouter's /models endpoint.

        Fetch models only when the caller provides a request-scoped key.
        """
        try:
            url = "https://openrouter.ai/api/v1/models"
            key = api_key
            try:
                keyring = get_request_keyring("openrouter")
                if not key and keyring and keyring.key:
                    key = keyring.key
            except MissingProviderKeyError:
                raise
            except Exception:  # noqa: BLE001
                pass
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers, timeout=8.0)
                if resp.status_code != 200:
                    return []
                data = resp.json()
            metadata = [m for m in (data.get("data") or []) if isinstance(m, dict)]
            self.set_model_metadata(metadata)
            models = [
                model_id for m in metadata if isinstance(model_id := m.get("id"), str)
            ]
            self.available_models = models
            return models
        except MissingProviderKeyError:
            raise
        except Exception:
            return []

    def _prepare_payload(
        self, ctx: LLMContext, messages: list[dict[str, Any]], stream: bool, **kwargs
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        messages = self._normalize_messages(messages)
        model = ctx.model
        assert model is not None

        if self.supports_vision(model) and messages:
            last_user_message = self._get_last_user_message(messages)
            if last_user_message and multimodal_tools.has_images(last_user_message):
                vision_messages = self.format_vision_message(last_user_message)
                messages = self._replace_last_user_message(
                    messages, last_user_message, vision_messages
                )

        headers, payload = super()._prepare_payload(ctx, messages, stream, **kwargs)
        headers["HTTP-Referer"] = "https://github.com/icedeyes12/yuzu-companion"
        headers["X-Title"] = "Yuzu-Companion"
        payload["top_k"] = kwargs.get("top_k")
        payload["typical_p"] = kwargs.get("typical_p")
        if ctx.chat_session_id:
            payload["session_id"] = ctx.chat_session_id

        return headers, payload

    def _handle_http_error(self, status_code: int, body: str) -> str | None:
        if status_code == 402:
            return (
                "OpenRouter free tier limit reached. "
                "Please try a different model or add credits."
            )
        if status_code == 429:
            return "Rate limit exceeded. Please wait a moment and try again."
        return None
