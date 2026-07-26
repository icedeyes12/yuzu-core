from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from app.core.context import (
    MissingProviderKeyError,
)
from app.core.llm_context import LLMContext
from app.providers.openai_protocol import (
    sanitize_and_validate_messages,
    sanitize_openai_payload,
)
from app.tools import multimodal_tools
from app.tools.schemas import StreamToolEvent

logger = logging.getLogger(__name__)

# ── Provider-level rate limiting (generalized) ───────────────────────────────
# Each provider gets its own semaphore and rate limit config
# CRITICAL: Semaphores MUST be created per-event-loop to prevent cross-loop binding

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

# Track which event loop each semaphore belongs to
_SEMAPHORE_LOOPS: dict[str, int] = {}  # semaphore_key -> loop_id


async def _get_provider_semaphore_async(provider: str) -> asyncio.Semaphore:
    """Get or create a semaphore for a specific provider (async).

    CRITICAL: Creates semaphore in current event loop to prevent cross-loop binding.
    If the event loop changed (e.g., after FastAPI reload), recreate the semaphore.
    """
    current_loop_id = id(asyncio.get_event_loop())

    # Check if semaphore exists and belongs to current loop
    if provider in _PROVIDER_SEMAPHORES:
        if _SEMAPHORE_LOOPS.get(provider) == current_loop_id:
            return _PROVIDER_SEMAPHORES[provider]
        # Loop changed - recreate semaphore
        logger.debug(
            f"[RateLimit] Event loop changed for {provider}, recreating semaphore"
        )

    # Create new semaphore in current loop
    _PROVIDER_SEMAPHORES[provider] = asyncio.Semaphore(1)
    _SEMAPHORE_LOOPS[provider] = current_loop_id
    return _PROVIDER_SEMAPHORES[provider]


async def _get_model_semaphore_async(model: str) -> asyncio.Semaphore:
    """Get or create a semaphore for a specific model (async).

    CRITICAL: Creates semaphore in current event loop to prevent cross-loop binding.
    """
    current_loop_id = id(asyncio.get_event_loop())
    sem_key = f"model:{model}"

    if sem_key in _MODEL_SEMAPHORES:
        if _SEMAPHORE_LOOPS.get(sem_key) == current_loop_id:
            return _MODEL_SEMAPHORES[sem_key]
        # Loop changed - recreate semaphore
        logger.debug(
            f"[RateLimit] Event loop changed for model {model}, recreating semaphore"
        )

    _MODEL_SEMAPHORES[model] = asyncio.Semaphore(1)
    _SEMAPHORE_LOOPS[sem_key] = current_loop_id
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


class ProviderCapabilities:
    """Declares what calling features a provider supports.

    Used by AIProviderManager to route requests correctly and by
    the orchestrator to decide whether to attach tools.
    """

    def __init__(
        self,
        *,
        supports_native_fc: bool = False,
        supports_streaming_fc: bool = False,
        supports_tool_call_parsing: bool = False,
        supports_structured_system_content: bool = False,
        supports_vision: bool = False,
    ):
        self.supports_native_fc = supports_native_fc
        self.supports_streaming_fc = supports_streaming_fc
        self.supports_tool_call_parsing = supports_tool_call_parsing
        self.supports_structured_system_content = supports_structured_system_content
        self.supports_vision = supports_vision

    def to_dict(self) -> dict[str, bool]:
        return {
            "supports_native_fc": self.supports_native_fc,
            "supports_streaming_fc": self.supports_streaming_fc,
            "supports_tool_call_parsing": self.supports_tool_call_parsing,
            "supports_structured_system_content": self.supports_structured_system_content,
            **({"supports_vision": True} if self.supports_vision else {}),
        }


class AIProvider:
    def __init__(self, name: str, config: dict | None = None):
        self.name = name
        self.config = config or {}
        self.is_available = True
        self._last_raw_response: dict | None = None
        self.capabilities = ProviderCapabilities()  # Subclasses override

    async def initialize(self) -> None:
        """Async initialization."""
        pass

    def _require_api_key(self, ctx: LLMContext) -> str:
        """Return the API key from context, raising MissingProviderKeyError if absent."""
        if not ctx.api_key:
            raise MissingProviderKeyError(self.name)
        return ctx.api_key

    async def get_models(self) -> list[str]:
        raise NotImplementedError

    async def send_message(
        self, ctx: LLMContext, messages: list[dict], source: str = "llm", **kwargs
    ) -> str | None:
        raise NotImplementedError

    async def send_message_raw(
        self, ctx: LLMContext, messages: list[dict], source: str = "llm", **kwargs
    ) -> dict | None:
        text = await self.send_message(ctx, messages, source=source, **kwargs)
        if text is not None:
            return {"choices": [{"message": {"content": text, "tool_calls": []}}]}
        return None

    async def _send_message_streaming_impl(
        self, ctx: LLMContext, messages: list[dict], source: str = "llm", **kwargs
    ) -> AsyncGenerator[str | StreamToolEvent, None]:
        """Default implementation raises; subclasses override this."""
        raise NotImplementedError
        # pragma: no cover - kept as type-checker anchor
        if False:
            yield ""

    async def send_message_streaming(
        self, ctx: LLMContext, messages: list[dict], source: str = "llm", **kwargs
    ) -> AsyncGenerator[str | StreamToolEvent, None]:
        """Yield raw chunks from the provider. Default delegates to abstract impl."""
        async for chunk in self._send_message_streaming_impl(
            ctx, messages, source=source, **kwargs
        ):
            yield chunk

    def parse_tool_calls(self, raw_response) -> list[dict]:
        return []

    async def test_connection(self) -> bool:
        try:
            models = await self.get_models()
            return len(models) > 0
        except Exception:
            return False

    def supports_vision(self, model: str) -> bool:
        return self.capabilities.supports_vision

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
        normalized = sanitize_and_validate_messages(messages)
        return normalized


class AIProviderManager:
    def __init__(self):
        self.providers: dict[str, AIProvider] = {}
        # initialization is now deferred to an async setup call

    async def initialize(self):
        """Async initialization of all registered providers."""
        try:
            load_fn = getattr(self, "load_providers", None)
            if load_fn:
                import inspect

                if inspect.iscoroutinefunction(load_fn):
                    await load_fn()
                else:
                    load_fn()
        except Exception:
            pass

        await asyncio.gather(*[p.initialize() for p in self.providers.values()])

    def register_provider(self, name: str, provider: AIProvider):
        self.providers[name] = provider

    @staticmethod
    def _sanitize_outbound_messages(messages: list[dict]) -> list[dict]:
        """(｡•̀ᴗ-)✧"""
        try:
            return sanitize_and_validate_messages(messages)
        except ValueError as exc:
            logger.error(
                "[ProviderManager] invalid outbound Chat Completions messages: %s", exc
            )
            raise

    @staticmethod
    def _sanitize_provider_kwargs(provider: AIProvider, kwargs: dict) -> dict:
        extensions_by_provider = {
            "chutes": {"top_k", "typical_p"},
            "openrouter": {"top_k", "typical_p"},
            "cerebras": {"top_k", "typical_p"},
            "ollama": {"top_k", "typical_p", "num_ctx"},
        }
        extensions = extensions_by_provider.get(provider.name, set())
        payload = sanitize_openai_payload(kwargs, provider_extensions=extensions)
        for key in ("messages", "model", "stream"):
            payload.pop(key, None)
        for key in ("timeout", "suppress_tools", "skip_vision", "log_prefix"):
            if key in kwargs:
                payload[key] = kwargs[key]
        return payload

    def get_available_providers(self) -> list[str]:
        return list(self.providers.keys())

    async def get_provider_models(self, provider_name: str) -> list[str]:
        if provider_name in self.providers:
            return await self.providers[provider_name].get_models()
        return []

    async def get_all_models(self) -> dict[str, list[str]]:
        """(｡•̀ᴗ-)✧"""
        all_models: dict[str, list[str]] = {}
        for provider_name, provider in self.providers.items():
            if asyncio.iscoroutinefunction(provider.get_models):
                models = await provider.get_models()
            else:
                models = provider.get_models()  # type: ignore[call-overload]
            all_models[provider_name] = [
                model for model in models if isinstance(model, str) and model
            ]
        return all_models

    async def send_message(
        self, ctx: LLMContext, messages: list[dict], **kwargs
    ) -> str | None:
        if ctx.provider not in self.providers:
            return None
        provider = self.providers[ctx.provider]
        messages = self._sanitize_outbound_messages(messages)
        kwargs = self._sanitize_provider_kwargs(provider, kwargs)
        start_time = time.time()
        response = await provider.send_message(ctx, messages, **kwargs)
        response_time = time.time() - start_time
        if response:
            return response
        logger.warning(
            f"[ProviderManager] {ctx.provider} failed after {response_time:.1f}s"
        )
        return None

    async def send_message_raw(
        self,
        ctx: LLMContext,
        messages: list[dict],
        source: str = "llm",
        **kwargs,
    ) -> dict | None:
        if ctx.provider not in self.providers:
            return None
        provider = self.providers[ctx.provider]
        messages = self._sanitize_outbound_messages(messages)
        kwargs = self._sanitize_provider_kwargs(provider, kwargs)
        start_time = time.time()
        raw = await provider.send_message_raw(ctx, messages, source=source, **kwargs)
        response_time = time.time() - start_time
        if raw is not None:
            return raw
        logger.warning(
            f"[ProviderManager] {ctx.provider} raw failed after {response_time:.1f}s"
        )
        return None

    # -- Capability-aware helpers (FC2) -----------------------------------

    def provider_supports_tools(self, provider_name: str) -> bool:
        """Check if a provider supports native function calling."""
        if provider_name not in self.providers:
            return False
        return self.providers[provider_name].capabilities.supports_native_fc

    def provider_supports_streaming_tools(self, provider_name: str) -> bool:
        """Check if a provider supports streaming tool-call events."""
        if provider_name not in self.providers:
            return False
        return self.providers[provider_name].capabilities.supports_streaming_fc

    def get_provider_capabilities(self, provider_name: str) -> dict[str, bool] | None:
        """Return capability dict for a single provider."""
        if provider_name not in self.providers:
            return None
        return self.providers[provider_name].capabilities.to_dict()

    def provider_supports_structured_system(self, provider_name: str) -> bool:
        """Return True if the provider can ingest a structured content-array
        system message. False / unknown providers fall back to legacy text.
        """
        if provider_name not in self.providers:
            return False
        return self.providers[
            provider_name
        ].capabilities.supports_structured_system_content

    def get_all_provider_capabilities(self) -> dict[str, dict[str, bool]]:
        """Return capability map for all registered providers."""
        return {name: p.capabilities.to_dict() for name, p in self.providers.items()}

    def parse_tool_calls(
        self, provider_name: str, raw_response: dict | None
    ) -> list[dict]:
        """Parse tool calls from a raw response using the provider's parser.

        Returns a canonical list of dicts: [{id, name, arguments}, ...]
        """
        if provider_name not in self.providers or raw_response is None:
            return []
        provider = self.providers[provider_name]
        if not provider.capabilities.supports_tool_call_parsing:
            return []
        return provider.parse_tool_calls(raw_response)

    async def send_message_streaming(
        self,
        ctx: LLMContext,
        messages: list[dict],
        source: str = "llm",
        **kwargs,
    ) -> AsyncGenerator[str | StreamToolEvent, None]:
        if ctx.provider not in self.providers:
            yield ""
            return
        provider = self.providers[ctx.provider]
        messages = self._sanitize_outbound_messages(messages)
        kwargs = self._sanitize_provider_kwargs(provider, kwargs)
        try:
            async for chunk in provider.send_message_streaming(
                ctx, messages, source=source, **kwargs
            ):
                yield chunk
        except asyncio.CancelledError:
            # Propagate cancellation - do NOT catch it here
            # This ensures the HTTP stream is properly closed
            raise
        except Exception as e:
            yield f"Streaming error: {str(e)}"

    async def _internal_llm_call(
        self,
        messages: list[dict],
        source: str = "internal",
        profile: dict | None = None,
        **kwargs,
    ) -> str | None:
        from app.core.llm_context import LLMContext

        ctx = LLMContext.from_profile(profile or {})
        if not ctx.provider or not ctx.model or ctx.provider not in self.providers:
            logger.info("[INT] memory/background LLM is not configured")
            return None
        runtime_parameters = {
            key: value
            for key, value in ctx.parameters.items()
            if not key.startswith("_") and key != "additional_instructions"
        }
        try:
            return await self.providers[ctx.provider].send_message(
                ctx=ctx,
                messages=messages,
                source=source,
                skip_vision=True,
                **runtime_parameters,
                **kwargs,
            )
        except Exception as exc:
            logger.info("[INT] background LLM skipped: %s", type(exc).__name__)
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
