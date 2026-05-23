from __future__ import annotations

import json
import logging
import requests
from typing import Generator
from app.providers.base import AIProvider
from app.tools import multimodal_tools

logger = logging.getLogger(__name__)


class ChutesProvider(AIProvider):
    def __init__(self, config: dict | None = None):
        super().__init__("chutes", config)
        self.base_url = "https://llm.chutes.ai/v1/chat/completions"
        self._last_error = None
        self.available_models = [
            "Qwen/Qwen3-VL-235B-A22B-Instruct",
            "Qwen/Qwen3.5-397B-A17B-TEE",
            "Qwen/Qwen3.6-27B-TEE",
            "google/gemma-4-31B-turbo-TEE",
            "deepseek-ai/DeepSeek-V3.2-TEE",
            "moonshotai/Kimi-K2.5-TEE",
            "moonshotai/Kimi-K2.6-TEE",
            "Qwen/Qwen2.5-Coder-32B-Instruct-TEE",
        ]

    def _normalize_messages_for_chutes(self, messages: list[dict]) -> list[dict]:
        if not messages:
            return messages
        standard_roles = {"system", "user", "assistant", "tool"}
        system_contents = []
        normalized_messages = []

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

    def get_models(self) -> list[str]:
        return self.available_models

    def send_message(self, messages: list[dict], model: str, **kwargs) -> str | None:
        if not self.api_key or model not in self.available_models:
            return None

        log_prefix = kwargs.pop("log_prefix", "[CHAT]")
        kwargs.pop("model", None)
        kwargs.pop("model_name", None)

        model_hint = kwargs.get("model") or kwargs.get("model_name")
        explicit_model = model_hint and model_hint in self.available_models
        retryable_codes = {0, 400, 429, 500, 502, 503, 504}

        attempt = 0
        last_error = None
        max_attempts = 3

        while attempt < max_attempts:
            attempt += 1
            current_model = model if attempt == 1 else None

            if current_model is None:
                tried = {model}
                priority = [m for m in self.available_models if m not in tried]
                qwen_first = sorted(priority, key=lambda m: 0 if "Qwen" in m else 1)
                for candidate in qwen_first:
                    if explicit_model and candidate == model_hint:
                        continue
                    current_model = candidate
                    break

            if not current_model:
                break

            result = self._chutes_raw(current_model, messages, kwargs)
            status = result[0]
            data = result[1]

            if status == 200:
                self._last_error = None
                return data

            last_error = result[2] if len(result) > 2 else str(status)
            self._last_error = last_error
            if status not in retryable_codes:
                return None

            logger.debug(
                f"{log_prefix} {current_model} failed ({status}), retrying with another model..."
            )

        logger.debug(f"{log_prefix} All models exhausted, last error: {last_error}")
        return None

    def _chutes_raw(self, model: str, messages: list[dict], kwargs) -> tuple:
        messages = self._normalize_messages_for_chutes(list(messages))

        if kwargs.get("skip_vision") is not True:
            if self.supports_vision(model) and messages:
                last_user_message = self._get_last_user_message(messages)
                if last_user_message and multimodal_tools.has_images(last_user_message):
                    logger.debug(
                        f"[Vision] Triggered for message: {last_user_message[:100]}..."
                    )
                    vision_messages = self.format_vision_message(last_user_message)
                    messages = self._replace_last_user_message(
                        messages, last_user_message, vision_messages
                    )

        temperature = kwargs.get("temperature", 0.73)
        max_tokens = kwargs.get("max_tokens")
        top_p = kwargs.get("top_p", 0.9)
        top_k = kwargs.get("top_k", 45)
        stream = kwargs.get("stream", False)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
            "top_k": top_k,
            "stream": stream,
        }

        log_prefix = kwargs.get("log_prefix", "[CHAT]")
        logger.debug(f"{log_prefix} {model} | max_tokens={max_tokens or 'unlimited'}")

        try:
            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=kwargs.get("timeout", 120),
            )
            if response.status_code == 200:
                return (
                    200,
                    response.json()["choices"][0]["message"]["content"].strip(),
                )
            return (response.status_code, None, response.text[:200])
        except Exception as e:
            return (0, None, str(e))

    def send_message_streaming(
        self, messages: list[dict], model: str, **kwargs
    ) -> Generator[str, None, None]:
        if not self.api_key or model not in self.available_models:
            reason = (
                "missing API key"
                if not self.api_key
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
            messages = self._normalize_messages_for_chutes(messages)
            if self.supports_vision(model) and messages:
                last_user_message = self._get_last_user_message(messages)
                if last_user_message and multimodal_tools.has_images(last_user_message):
                    vision_messages = self.format_vision_message(last_user_message)
                    messages = self._replace_last_user_message(
                        messages, last_user_message, vision_messages
                    )

            temperature = kwargs.get("temperature", 0.73)
            max_tokens = kwargs.get("max_tokens")
            top_p = kwargs.get("top_p", 0.9)
            top_k = kwargs.get("top_k", 45)
            typical_p = kwargs.get("typical_p", 0.85)

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "top_p": top_p,
                "top_k": top_k,
                "typical_p": typical_p,
                "stream": True,
            }

            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=kwargs.get("timeout", 120),
                stream=True,
            )

            if response.status_code == 200:
                for line in response.iter_lines():
                    if line and line.startswith(b"data: "):
                        if line == b"data: [DONE]":
                            break
                        try:
                            json_data = json.loads(line[6:])
                            if "choices" in json_data and len(json_data["choices"]) > 0:
                                delta = json_data["choices"][0].get("delta", {})
                                if "content" in delta and delta["content"]:
                                    yield delta["content"]
                        except (json.JSONDecodeError, KeyError):
                            continue
            else:
                logger.warning(
                    "Chutes HTTP %d for model %s", response.status_code, model
                )
                yield (
                    "\n[System] Chutes API returned HTTP "
                    + str(response.status_code)
                    + ". Please try again."
                )
        except Exception as e:
            yield f"Error: {str(e)}"
