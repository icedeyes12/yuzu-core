from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator

import httpx

from app.providers.base import AIProvider, ProviderCapabilities, _rate_limit_provider
from app.tools import multimodal_tools
from app.tools.schemas import StreamToolEvent

logger = logging.getLogger(__name__)


class ChutesProvider(AIProvider):
    def __init__(self, config: dict | None = None):
        super().__init__("chutes", config)
        self.base_url = "https://llm.chutes.ai/v1/chat/completions"
        self.capabilities = ProviderCapabilities(
            supports_native_fc=True,
            supports_streaming_fc=True,
            supports_tool_call_parsing=True,
        )
        self._last_error: str | None = None
        self.available_models = [
            "google/gemma-4-31B-turbo-TEE",
            "Qwen/Qwen3.6-27B-TEE",
            "Qwen/Qwen3.5-397B-A17B-TEE",
            "Qwen/Qwen3-32B-TEE",
            "Qwen/Qwen3-235B-A22B-Thinking-2507",
            "deepseek-ai/DeepSeek-V3.2-TEE",
            "MiniMaxAI/MiniMax-M2.5-TEE",
            "moonshotai/Kimi-K2.5-TEE",
            "moonshotai/Kimi-K2.6-TEE",
            "Nemotron-3-Nano-Omni-30B-TEE",
            "Qwen/Qwen2.5-Coder-32B-Instruct-TEE",
            "unsloth/Mistral-Nemo-Instruct-2407-TEE",
            "zai-org/GLM-5-TEE",
            "zai-org/GLM-5.1-TEE",
        ]

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._require_api_key()}",
            "Content-Type": "application/json",
        }

    def _normalize_messages_for_chutes(self, messages: list[dict]) -> list[dict]:
        """Merge non-standard roles into a single assistant content and collect system prompts."""
        if not messages:
            return messages
        standard_roles = {"system", "user", "assistant", "tool"}
        system_contents: list[str] = []
        normalized_messages: list[dict] = []
        for msg in messages:
            role = msg.get("role", "")
            if role == "system":
                system_contents.append(msg.get("content", ""))
            elif role not in standard_roles:
                content = msg.get("content", "")
                normalized_content = f"[{role}]\n{content}"
                normalized_messages.append(
                    {"role": "assistant", "content": normalized_content}
                )
            else:
                normalized_messages.append(msg)
        if system_contents:
            merged_system = "\n\n".join(system_contents)
            return [{"role": "system", "content": merged_system}] + normalized_messages
        return normalized_messages

    def _prepare_payload(
        self, messages: list[dict], model: str, stream: bool, **kwargs
    ) -> tuple[dict[str, str], dict[str, Any]]:
        messages = self._normalize_messages_for_chutes(list(messages))

        if kwargs.get("skip_vision") is not True:
            if self.supports_vision(model) and messages:
                last_user_message = self._get_last_user_message(messages)
                if last_user_message and multimodal_tools.has_images(last_user_message):
                    logger.debug(
                        "[Vision] Triggered for message: %s...", last_user_message[:100]
                    )
                    vision_messages = self.format_vision_message(last_user_message)
                    messages = self._replace_last_user_message(
                        messages, last_user_message, vision_messages
                    )

        temperature = kwargs.get("temperature", 0.73)
        max_tokens = kwargs.get("max_tokens")
        top_p = kwargs.get("top_p", 0.9)
        top_k = kwargs.get("top_k", 45)
        typical_p = kwargs.get("typical_p", 0.85)

        payload: dict[str, Any] = {
            "model": self.resolve_model(model),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
            "top_k": top_k,
            "typical_p": typical_p,
            "stream": stream,
        }

        tools = kwargs.get("tools")
        if tools and not kwargs.get("suppress_tools"):
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        return self._build_headers(), payload

    def _extract_message_content(self, response_json: dict[str, Any]) -> str:
        try:
            message = response_json["choices"][0]["message"]
            content = message.get("content", "")
            return content.strip() if content else ""
        except (KeyError, IndexError, AttributeError, TypeError):
            return ""

    async def get_models(self) -> list[str]:
        return self.available_models

    async def send_message(
        self, messages: list[dict], model: str, source: str = "llm", **kwargs
    ) -> str | None:
        if model not in self.available_models:
            return None

        log_prefix = kwargs.pop("log_prefix", "[CHAT]")
        kwargs.pop("model", None)
        kwargs.pop("model_name", None)

        model_hint = kwargs.get("model") or kwargs.get("model_name")
        explicit_model = model_hint and model_hint in self.available_models
        retryable_codes = {0, 400, 429, 500, 502, 503, 504}

        attempt = 0
        last_error: str | None = None
        max_model_attempts = 3
        max_429_retries = 3
        backoff_base = 2.0

        tried_models: set[str] = set()

        while attempt < max_model_attempts:
            attempt += 1
            current_model = model if attempt == 1 else None

            if current_model is None:
                priority = [m for m in self.available_models if m not in tried_models]
                qwen_first = sorted(priority, key=lambda m: 0 if "Qwen" in m else 1)
                for candidate in qwen_first:
                    if explicit_model and candidate == model_hint:
                        continue
                    current_model = candidate
                    break

            if not current_model:
                break

            tried_models.add(current_model)

            for retry in range(max_429_retries):
                status = None
                data = None
                error_msg = None

                async with _rate_limit_provider("chutes", current_model, source):
                    result = await self._chutes_raw(current_model, messages, kwargs)
                    status = result[0]
                    data = result[1] if len(result) > 1 else None
                    error_msg = result[2] if len(result) > 2 else str(status)

                if status == 200:
                    self._last_error = None
                    return self._extract_message_content(
                        data if isinstance(data, dict) else {}
                    )

                last_error = error_msg
                self._last_error = last_error

                if status == 429:
                    if retry < max_429_retries - 1:
                        backoff = backoff_base * (2**retry)
                        logger.warning(
                            "%s 429 on %s, retry %d/%d in %ss...",
                            log_prefix,
                            current_model,
                            retry + 1,
                            max_429_retries,
                            backoff,
                        )
                        await asyncio.sleep(backoff)
                        continue
                    logger.warning(
                        "%s Max 429 retries for %s, trying another model...",
                        log_prefix,
                        current_model,
                    )
                    break

                if status not in retryable_codes:
                    return None

                break

            if attempt < max_model_attempts:
                await asyncio.sleep(0.5)
                logger.debug(
                    "%s %s failed (%s), trying another model...",
                    log_prefix,
                    current_model,
                    status,
                )

        logger.debug("%s All models exhausted, last error: %s", log_prefix, last_error)
        return None

    async def send_message_raw(
        self, messages: list[dict], model: str, source: str = "llm", **kwargs
    ) -> dict[str, Any] | None:
        headers, payload = self._prepare_payload(messages, model, False, **kwargs)

        async with _rate_limit_provider("chutes", model, source):
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.post(
                        self.resolve_base_url(self.base_url),
                        headers=headers,
                        json=payload,
                        timeout=kwargs.get("timeout", 120),
                    )
                    if response.status_code == 200:
                        result = response.json()
                        self._last_raw_response = result
                        return result
                    self._last_raw_response = None
                    return None
                except Exception:
                    self._last_raw_response = None
                    return None

    async def _chutes_raw(self, model: str, messages: list[dict], kwargs) -> tuple:
        headers, payload = self._prepare_payload(messages, model, False, **kwargs)

        log_prefix = kwargs.get("log_prefix", "[CHAT]")
        logger.debug(
            "%s %s | max_tokens=%s",
            log_prefix,
            model,
            payload["max_tokens"] or "unlimited",
        )

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.resolve_base_url(self.base_url),
                    headers=headers,
                    json=payload,
                    timeout=kwargs.get("timeout", 120),
                )
                if response.status_code == 200:
                    result = response.json()
                    self._last_raw_response = result
                    return (200, result)
                return (response.status_code, None, response.text[:200])
            except Exception as e:
                return (0, None, str(e))

    async def send_message_streaming(
        self, messages: list[dict], model: str, source: str = "llm", **kwargs
    ) -> AsyncGenerator[str | StreamToolEvent, None]:
        if model not in self.available_models:
            reason = (
                "missing API key"
                if not self.resolve_api_key()
                else f"model {model} not in available"
            )
            logger.warning("Chutes stream aborted: %s", reason)
            yield (
                "\n[System] Chutes provider error: "
                + reason
                + ". Please check configuration."
            )
            return

        try:
            headers, payload = self._prepare_payload(messages, model, True, **kwargs)
            if kwargs.get("suppress_tools"):
                payload.pop("tools", None)
                payload.pop("tool_choice", None)

            has_tools = bool(payload.get("tools"))

            async with _rate_limit_provider("chutes", model, source):
                async with httpx.AsyncClient() as client:
                    async with client.stream(
                        "POST",
                        self.resolve_base_url(self.base_url),
                        headers=headers,
                        json=payload,
                        timeout=kwargs.get("timeout", 120),
                    ) as response:
                        if response.status_code == 200:
                            if has_tools:
                                tool_call_fragments: dict[int, dict] = {}
                                async for line in response.aiter_lines():
                                    if not line or not line.startswith("data: "):
                                        continue
                                    if line == "data: [DONE]":
                                        break
                                    try:
                                        json_data = json.loads(line[6:])
                                        if (
                                            "choices" in json_data
                                            and len(json_data["choices"]) > 0
                                        ):
                                            delta = json_data["choices"][0].get(
                                                "delta", {}
                                            )
                                            if delta.get("content"):
                                                yield delta["content"]
                                            if delta.get("tool_calls"):
                                                for tc_delta in delta["tool_calls"]:
                                                    idx = tc_delta.get("index", 0)
                                                    if idx not in tool_call_fragments:
                                                        tool_call_fragments[idx] = {
                                                            "id": "",
                                                            "function": {
                                                                "name": "",
                                                                "arguments": "",
                                                            },
                                                        }
                                                    frag = tool_call_fragments[idx]
                                                    if tc_delta.get("id"):
                                                        frag["id"] = tc_delta["id"]
                                                    fn = tc_delta.get("function", {})
                                                    if fn.get("name"):
                                                        frag["function"]["name"] = fn[
                                                            "name"
                                                        ]
                                                    if fn.get("arguments"):
                                                        frag["function"][
                                                            "arguments"
                                                        ] += fn["arguments"]
                                    except (json.JSONDecodeError, KeyError):
                                        continue

                                for idx in sorted(tool_call_fragments.keys()):
                                    frag = tool_call_fragments[idx]
                                    try:
                                        args = (
                                            json.loads(frag["function"]["arguments"])
                                            if frag["function"]["arguments"]
                                            else {}
                                        )
                                    except json.JSONDecodeError:
                                        args = {}
                                    yield StreamToolEvent(
                                        type="tool_call",
                                        data={
                                            "id": frag["id"],
                                            "name": frag["function"]["name"],
                                            "arguments": args,
                                        },
                                    )
                            else:
                                async for line in response.aiter_lines():
                                    if line and line.startswith("data: "):
                                        if line == "data: [DONE]":
                                            break
                                        try:
                                            json_data = json.loads(line[6:])
                                            if (
                                                "choices" in json_data
                                                and len(json_data["choices"]) > 0
                                            ):
                                                delta = json_data["choices"][0].get(
                                                    "delta", {}
                                                )
                                                if delta.get("content"):
                                                    yield delta["content"]
                                        except (json.JSONDecodeError, KeyError):
                                            continue
                        else:
                            logger.warning(
                                "Chutes HTTP %d for model %s",
                                response.status_code,
                                model,
                            )
                            yield (
                                "\n[System] Chutes API returned HTTP "
                                + str(response.status_code)
                                + ". Please try again."
                            )

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Chutes streaming error: %s", repr(e), exc_info=True)
            error_msg = str(e)
            if not error_msg:
                error_msg = repr(e)
            yield f"Error: {type(e).__name__} - {error_msg}"

    def parse_tool_calls(self, raw_response) -> list[dict]:
        if not isinstance(raw_response, dict):
            return []
        try:
            message = raw_response.get("choices", [{}])[0].get("message", {})
            tool_calls = message.get("tool_calls", [])
            results = []
            for tc in tool_calls:
                fn = tc.get("function", {})
                arguments = fn.get("arguments", "{}")
                if isinstance(arguments, dict):
                    parsed_arguments = arguments
                else:
                    try:
                        parsed_arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        parsed_arguments = {}
                results.append(
                    {
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "arguments": parsed_arguments,
                    }
                )
            return results
        except Exception:
            return []
