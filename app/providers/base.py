from __future__ import annotations

import logging
import time
import asyncio
from typing import AsyncGenerator
from contextlib import asynccontextmanager

from app.db import get_api_key_async
from app.tools import multimodal_tools

logger = logging.getLogger(__name__)

# ── Provider-level rate limiting (generalized) ───────────────────────────────
# Each provider gets its own semaphore and rate limit config
# NOTE: Semaphores are created lazily via async getters to ensure they bind
# to the active event loop at creation time, not at module import time.

_PROVIDER_SEMAPHORES: dict[str, asyncio.Semaphore] = {}
_PROVIDER_LAST_CALL: dict[str, float] = {}
_PROVIDER_RATE_LIMITS: dict[str, float] = {
    "chutes": 0.5,  # 0.5s between Chutes requests (strict)
    "openrouter": 0.3,  # 0.3s between OpenRouter requests
    "ollama": 0.1,  # 0.1s for local Ollama (relaxed)
    # Default for unknown providers
    "default": 0.5,
}

# ── Model-level rate limiting ───────────────────────────────────────────────

_MODEL_SEMAPHORES: dict[str, asyncio.Semaphore] = {}
_MODEL_LAST_CALL: dict[str, float] = {}
_MODEL_RATE_LIMIT = 1.0  # Min 1s between calls to same model


async def _get_provider_semaphore_async(provider: str) -> asyncio.Semaphore:
    """Get or create a semaphore for a specific provider (async).
    
    Creates the semaphore lazily in the current event loop to avoid
    cross-loop binding issues.
    """
    if provider not in _PROVIDER_SEMAPHORES:
        _PROVIDER_SEMAPHORES[provider] = asyncio.Semaphore(1)
    return _PROVIDER_SEMAPHORES[provider]


async def _get_model_semaphore_async(model: str) -> asyncio.Semaphore:
    """Get or create a semaphore for a specific model (async).
    
    Creates the semaphore lazily in the current event loop to avoid
    cross-loop binding issues.
    """
    if model not in _MODEL_SEMAPHORES:
        _MODEL_SEMAPHORES[model] = asyncio.Semaphore(1)
    return _MODEL_SEMAPHORES[model]


@asynccontextmanager
async def _rate_limit_provider(provider: str, model: str, source: str = "llm"):
    """Context manager for provider-level rate limiting.

    Args:
        provider: Provider name (e.g., "chutes", "openrouter")
        model: Model name for per-model rate limiting
        source: Source context for logging (e.g., "chat", "pcl_memory", "embedding")
    """
    provider_sem = await _get_provider_semaphore_async(provider)
    model_sem = await _get_model_semaphore_async(model)

    # Acquire provider-global semaphore first
    async with provider_sem:
        # Enforce provider-level delay
        provider_delay = _PROVIDER_RATE_LIMITS.get(
            provider, _PROVIDER_RATE_LIMITS["default"]
        )
        if provider in _PROVIDER_LAST_CALL:
            elapsed = time.time() - _PROVIDER_LAST_CALL[provider]
            if elapsed < provider_delay:
                await asyncio.sleep(provider_delay - elapsed)

        # Acquire model-specific semaphore
        async with model_sem:
            # Enforce model-level delay
            if model in _MODEL_LAST_CALL:
                elapsed = time.time() - _MODEL_LAST_CALL[model]
                if elapsed < _MODEL_RATE_LIMIT:
                    await asyncio.sleep(_MODEL_RATE_LIMIT - elapsed)

            # Log the action with context
            logger.info(f"[{source.upper()}] Requesting {provider}/{model}...")

            try:
                yield
            finally:
                # Update timestamps
                _PROVIDER_LAST_CALL[provider] = time.time()
                _MODEL_LAST_CALL[model] = time.time()


# ── Retry with exponential backoff (429 handling) ─────────────────────────────


async def _retry_with_backoff(
    func,
    provider: str,
    model: str,
    max_retries: int = 3,
    backoff_base: float = 2.0,
    **kwargs,
):
    """Execute function with retry logic for 429 errors.

    IMPORTANT: This function releases the rate limit lock BEFORE sleeping,
    allowing other requests to proceed during the backoff period.

    Args:
        func: Async function to call (e.g., _chutes_raw)
        provider: Provider name for rate limiting
        model: Model name for rate limiting
        max_retries: Maximum retry attempts (default: 3)
        backoff_base: Base backoff in seconds (default: 2.0, doubles each retry)
        **kwargs: Arguments to pass to func

    Returns:
        Result from func, or raises exception after max retries

    Example backoff sequence: 2s, 4s, 8s (if max_retries=3)
    """
    last_error = None

    for attempt in range(max_retries):
        should_retry = False
        backoff = backoff_base * (2**attempt) if attempt > 0 else 0

        try:
            async with _rate_limit_provider(provider, model):
                result = await func(**kwargs)

                # Check if result indicates 429
                if isinstance(result, tuple) and len(result) >= 1:
                    status = result[0]
                    if status == 429:
                        should_retry = True
                        last_error = "HTTP 429: Rate limited"
                        logger.warning(
                            f"[{provider}] 429 on {model}, "
                            f"attempt {attempt + 1}/{max_retries}"
                        )

        except Exception as e:
            last_error = str(e)
            logger.error(f"[{provider}] Request failed: {e}")
            raise

        if should_retry and attempt < max_retries - 1:
            # Sleep OUTSIDE the lock to not block other requests
            logger.info(f"[{provider}] Backing off for {backoff}s...")
            await asyncio.sleep(backoff)
            continue

        return result

    raise Exception(f"Max retries ({max_retries}) exceeded: {last_error}")


# ── AIProvider base class ───────────────────────────────────────────────────


class AIProvider:
    def __init__(self, name: str, config: dict | None = None):
        self.name = name
        self.config = config or {}
        self.is_available = True
        self._last_raw_response: dict | None = None
        self.api_key = None  # Will be loaded async

    async def initialize(self) -> None:
        """Async initialization to load API keys."""
        self.api_key = await self._load_api_key()
        if self.name != "ollama":  # Ollama doesn't need API key
            self.is_available = bool(self.api_key)

    async def _load_api_key(self) -> str | None:
        """Centralized API key lookup from DB (async)."""
        try:
            return await get_api_key_async(self.name)
        except Exception:
            return None

    async def get_models(self) -> list[str]:
        raise NotImplementedError

    async def send_message(
        self, messages: list[dict], model: str, source: str = "llm", **kwargs
    ) -> str | None:
        raise NotImplementedError

    async def send_message_raw(
        self, messages: list[dict], model: str, source: str = "llm", **kwargs
    ) -> dict | None:
        text = await self.send_message(messages, model, source=source, **kwargs)
        if text is not None:
            return {"choices": [{"message": {"content": text, "tool_calls": []}}]}
        return None

    async def send_message_streaming(
        self, messages: list[dict], model: str, source: str = "llm", **kwargs
    ) -> AsyncGenerator[str, None]:
        raise NotImplementedError
        yield ""  # Keep as async generator

    def parse_tool_calls(self, raw_response) -> list[dict]:
        return []

    async def test_connection(self) -> bool:
        try:
            models = await self.get_models()
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
        self.providers: dict[str, AIProvider] = {}
        # initialization is now deferred to an async setup call

    async def initialize(self):
        """Async initialization of all registered providers."""
        if hasattr(self, "load_providers"):
            if asyncio.iscoroutinefunction(self.load_providers):
                await self.load_providers()
            else:
                self.load_providers()

        await asyncio.gather(*[p.initialize() for p in self.providers.values()])

    def register_provider(self, name: str, provider: AIProvider):
        self.providers[name] = provider

    def get_available_providers(self) -> list[str]:
        return list(self.providers.keys())

    async def get_provider_models(self, provider_name: str) -> list[str]:
        if provider_name in self.providers:
            return await self.providers[provider_name].get_models()
        return []

    async def get_all_models(self) -> dict[str, list[str]]:
        all_models = {}
        for provider_name, provider in self.providers.items():
            if asyncio.iscoroutinefunction(provider.get_models):
                all_models[provider_name] = await provider.get_models()
            else:
                all_models[provider_name] = provider.get_models()
        return all_models

    async def send_message(
        self, provider_name: str, model: str, messages: list[dict], **kwargs
    ) -> str | None:
        if provider_name not in self.providers:
            return None
        provider = self.providers[provider_name]
        start_time = time.time()
        response = await provider.send_message(messages, model, **kwargs)
        response_time = time.time() - start_time
        if response:
            return response
        logger.warning(
            f"[ProviderManager] {provider_name} failed after {response_time:.1f}s"
        )
        return None

    async def send_message_raw(
        self,
        provider_name: str,
        model: str,
        messages: list[dict],
        source: str = "llm",
        **kwargs,
    ) -> dict | None:
        if provider_name not in self.providers:
            return None
        provider = self.providers[provider_name]
        start_time = time.time()
        raw = await provider.send_message_raw(messages, model, source=source, **kwargs)
        response_time = time.time() - start_time
        if raw is not None:
            return raw
        logger.warning(
            f"[ProviderManager] {provider_name} raw failed after {response_time:.1f}s"
        )
        return None

    async def send_message_streaming(
        self,
        provider_name: str,
        model: str,
        messages: list[dict],
        source: str = "llm",
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        if provider_name not in self.providers:
            yield ""
            return
        provider = self.providers[provider_name]
        try:
            async for chunk in provider.send_message_streaming(
                messages, model, source=source, **kwargs
            ):
                yield chunk
        except asyncio.CancelledError:
            # Propagate cancellation - do NOT catch it here
            # This ensures the HTTP stream is properly closed
            raise
        except Exception as e:
            yield f"Streaming error: {str(e)}"

    _PREFERRED_MODELS = [
        "Qwen/Qwen3.6-27B-TEE",
        "Qwen/Qwen3-235B-A22B-Thinking-2507",
    ]

    async def _internal_llm_call(
        self, messages: list[dict], source: str = "internal", **kwargs
    ) -> str | None:
        if "chutes" not in self.providers:
            logger.warning("[INT] chutes provider not available")
            return None
        provider = self.providers["chutes"]
        MAIN_MODEL = "google/gemma-4-31B-turbo-TEE"
        FALLBACK_MODEL = "Qwen/Qwen3.6-27B-TEE"

        logger.debug(f"[INT] Starting with {MAIN_MODEL}, {len(messages)} messages")

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
            result = await provider.send_message(
                messages, MAIN_MODEL, source=source, skip_vision=True, **kwargs
            )
            if result:
                logger.debug(f"[INT] Success with {MAIN_MODEL}: {len(result)} chars")
                return result

            last_error = getattr(provider, "_last_error", None)

            # Calculate backoff: 1s, 2s, 4s (using 2 ** attempt since attempt starts at 0)
            backoff = 2**attempt
            logger.warning(
                f"[INT] {MAIN_MODEL} failed (attempt {attempt + 1}): {last_error}. Retrying in {backoff}s..."
            )

            if not _is_connection_error(last_error):
                break

            await asyncio.sleep(backoff)

        # Mandatory cooldown before trying fallback model
        await asyncio.sleep(1.0)
        logger.warning(f"[INT] Falling back to {FALLBACK_MODEL}")
        result = await provider.send_message(
            messages, FALLBACK_MODEL, source=source, skip_vision=True, **kwargs
        )
        if result:
            logger.debug(f"[INT] Success with {FALLBACK_MODEL}: {len(result)} chars")
            return result
        last_error = getattr(provider, "_last_error", None)
        logger.warning(f"[INT] {FALLBACK_MODEL} failed: {last_error}")

        logger.error("[INT] All models failed, returning None")
        return None

    async def auto_send_message(self, messages: list[dict], **kwargs) -> str | None:
        return await self._internal_llm_call(messages, **kwargs)


_ai_manager_instance = None


async def get_ai_manager():
    global _ai_manager_instance
    if _ai_manager_instance is None:
        _ai_manager_instance = AIProviderManager()
        await _ai_manager_instance.initialize()
    return _ai_manager_instance


async def reload_ai_manager():
    global _ai_manager_instance
    _ai_manager_instance = AIProviderManager()
    await _ai_manager_instance.initialize()
    return _ai_manager_instance
