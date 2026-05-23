from __future__ import annotations

import logging
import time
from typing import Generator

from app.db import get_api_key
from app.tools import multimodal_tools

logger = logging.getLogger(__name__)


class AIProvider:
    def __init__(self, name: str, config: dict | None = None):
        self.name = name
        self.config = config or {}
        self.is_available = True
        self._last_raw_response: dict | None = None
        self.api_key = self._load_api_key()
        if self.name != "ollama":  # Ollama doesn't need API key
            self.is_available = bool(self.api_key)

    def _load_api_key(self) -> str | None:
        """Centralized API key lookup from DB."""
        try:
            return get_api_key(self.name)
        except Exception:
            return None

    def get_models(self) -> list[str]:
        raise NotImplementedError

    def send_message(self, messages: list[dict], model: str, **kwargs) -> str | None:
        raise NotImplementedError

    def send_message_raw(
        self, messages: list[dict], model: str, **kwargs
    ) -> dict | None:
        text = self.send_message(messages, model, **kwargs)
        if text is not None:
            return {"choices": [{"message": {"content": text, "tool_calls": []}}]}
        return None

    def send_message_streaming(
        self, messages: list[dict], model: str, **kwargs
    ) -> Generator[str, None, None]:
        raise NotImplementedError

    def parse_tool_calls(self, raw_response) -> list[dict]:
        return []

    def test_connection(self) -> bool:
        try:
            models = self.get_models()
            return len(models) > 0
        except Exception:
            return False

    def supports_vision(self, model: str) -> bool:
        return multimodal_tools.is_vision_model(model, self.name)

    def format_vision_message(self, user_message: str) -> list[dict]:
        return multimodal_tools.format_vision_message(user_message, self.name)

    def _get_last_user_message(self, messages: list[dict]) -> str | None:
        for msg in reversed(messages):
            if msg["role"] == "user":
                return msg["content"] if isinstance(msg["content"], str) else None
        return None

    def _replace_last_user_message(
        self, messages: list[dict], old_message: str, new_messages: list[dict]
    ) -> list[dict]:
        new_message_list = []
        replaced = False
        for msg in messages:
            if msg["role"] == "user" and msg["content"] == old_message and not replaced:
                new_message_list.extend(new_messages)
                replaced = True
            else:
                new_message_list.append(msg)
        return new_message_list

    def _normalize_messages(self, messages: list[dict]) -> list[dict]:
        """Common message normalization for OpenAI-compatible providers."""
        if not messages:
            return messages
        standard_roles = {"system", "user", "assistant", "tool"}
        normalized = []
        for msg in messages:
            role = msg.get("role", "")
            if role not in standard_roles:
                content = msg.get("content", "")
                normalized_content = f"[{role}]\n{content}"
                normalized.append({"role": "assistant", "content": normalized_content})
            else:
                normalized.append(msg)
        return normalized


class AIProviderManager:
    def __init__(self):
        self.providers = {}
        self.load_providers()

    def register_provider(self, name: str, provider: AIProvider):
        self.providers[name] = provider

    def get_available_providers(self) -> list[str]:
        return list(self.providers.keys())

    def get_provider_models(self, provider_name: str) -> list[str]:
        if provider_name in self.providers:
            return self.providers[provider_name].get_models()
        return []

    def get_all_models(self) -> dict[str, list[str]]:
        all_models = {}
        for provider_name, provider in self.providers.items():
            all_models[provider_name] = provider.get_models()
        return all_models

    def send_message(
        self, provider_name: str, model: str, messages: list[dict], **kwargs
    ) -> str | None:
        if provider_name not in self.providers:
            return None
        provider = self.providers[provider_name]
        start_time = time.time()
        response = provider.send_message(messages, model, **kwargs)
        response_time = time.time() - start_time
        if response:
            return response
        logger.warning(
            f"[ProviderManager] {provider_name} failed after {response_time:.1f}s"
        )
        return None

    def send_message_raw(
        self, provider_name: str, model: str, messages: list[dict], **kwargs
    ) -> dict | None:
        if provider_name not in self.providers:
            return None
        provider = self.providers[provider_name]
        start_time = time.time()
        raw = provider.send_message_raw(messages, model, **kwargs)
        response_time = time.time() - start_time
        if raw is not None:
            return raw
        logger.warning(
            f"[ProviderManager] {provider_name} raw failed after {response_time:.1f}s"
        )
        return None

    def send_message_streaming(
        self, provider_name: str, model: str, messages: list[dict], **kwargs
    ) -> Generator[str, None, None]:
        if provider_name not in self.providers:
            yield ""
            return
        provider = self.providers[provider_name]
        try:
            for chunk in provider.send_message_streaming(messages, model, **kwargs):
                yield chunk
        except Exception as e:
            yield f"Streaming error: {str(e)}"

    _PREFERRED_MODELS = [
        "Qwen/Qwen3.6-27B-TEE",
        "Qwen/Qwen3-235B-A22B-Instruct-2507-TEE",
    ]

    def _internal_llm_call(self, messages: list[dict], **kwargs) -> str | None:
        if "chutes" not in self.providers:
            return None
        provider = self.providers["chutes"]
        MAIN_MODEL = "google/gemma-4-31B-turbo-TEE"
        FALLBACK_MODEL = "Qwen/Qwen3.6-27B-TEE"

        def _is_connection_error(error: str | None) -> bool:
            if not error:
                return True
            error_lower = error.lower()
            retryable = [
                "timeout",
                "connection",
                "network",
                "refused",
                "reset",
                "socket",
                "timed out",
            ]
            return any(r in error_lower for r in retryable)

        for attempt in range(3):
            result = provider.send_message(
                messages, MAIN_MODEL, log_prefix="[INT]", skip_vision=True, **kwargs
            )
            if result:
                return result
            last_error = getattr(provider, "_last_error", None)
            if not _is_connection_error(last_error):
                break
            if attempt < 2:
                time.sleep(0.5)

        for attempt in range(2):
            result = provider.send_message(
                messages, FALLBACK_MODEL, log_prefix="[INT]", skip_vision=True, **kwargs
            )
            if result:
                return result
            last_error = getattr(provider, "_last_error", None)
            if not _is_connection_error(last_error):
                break
            if attempt < 1:
                time.sleep(0.5)
        return None

    def auto_send_message(self, messages: list[dict], **kwargs) -> str | None:
        return self._internal_llm_call(messages, **kwargs)


_ai_manager_instance = None


def get_ai_manager():
    global _ai_manager_instance
    if _ai_manager_instance is None:
        _ai_manager_instance = AIProviderManager()
    return _ai_manager_instance


def reload_ai_manager():
    global _ai_manager_instance
    _ai_manager_instance = AIProviderManager()
    return _ai_manager_instance
