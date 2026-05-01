# FILE: app/providers.py
# DESCRIPTION: AI provider configuration and client management

from __future__ import annotations

import requests
import json
import time
import logging
from typing import Generator

from app.database import Database
from app.tools import multimodal_tools

logger = logging.getLogger(__name__)

class AIProvider:
    def __init__(self, name: str, config: dict | None = None):
        self.name = name
        self.config = config or {}
        self.is_available = True
    
    def get_models(self) -> list[str]:
        raise NotImplementedError
    
    def send_message(self, messages: list[dict], model: str, **kwargs) -> str | None:
        """Send a message. Supports tools=[] kwarg for function calling.
        
        Returns:
            str: Natural text response. Tool execution is handled by caller
                 via parse_tool_calls() on the raw response.
        """
        raise NotImplementedError
    
    def send_message_streaming(self, messages: list[dict], model: str, **kwargs) -> Generator[str, None, None]:
        raise NotImplementedError
    
    def parse_tool_calls(self, raw_response) -> list[dict]:
        """Parse tool_calls from a provider-specific response object.

        Returns list of {"name": str, "arguments": dict, "id": str} or empty list.
        Override per-provider since response shapes differ.
        """
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
        """Get the last user message from messages list"""
        for msg in reversed(messages):
            if msg['role'] == 'user':
                return msg['content'] if isinstance(msg['content'], str) else None
        return None
    
    def _replace_last_user_message(self, messages: list[dict], old_message: str, new_messages: list[dict]) -> list[dict]:
        """Replace the last user message with new vision-formatted messages"""
        new_message_list = []
        replaced = False
        
        for msg in messages:
            if msg['role'] == 'user' and msg['content'] == old_message and not replaced:
                new_message_list.extend(new_messages)
                replaced = True
            else:
                new_message_list.append(msg)
        
        return new_message_list

class OllamaProvider(AIProvider):
    def __init__(self, config: dict | None = None):
        super().__init__("ollama", config)
        self.base_url = self.config.get('base_url', "http://127.0.0.1:11434")
        self.available_models = [
            "smollm:360m",
            "smollm2:360m",
            "glm-4.6:cloud",
            "qwen3-vl:235b-cloud",
            "qwen3-coder:480b-cloud",
            "kimi-k2:1t-cloud",
            "kimi-k2.5:cloud",
            "gpt-oss:120b-cloud",
            "gpt-oss:20b-cloud",
            "deepseek-v3.1:671b-cloud"
        ]
    
    def get_models(self) -> list[str]:
        return self.available_models
    
    def send_message(self, messages: list[dict], model: str, **kwargs) -> str | None:
        if model not in self.available_models:
            return None
            
        try:
            temperature = kwargs.get('temperature', 0.69)
            top_p = kwargs.get('top_p', 0.7)
            top_k = kwargs.get('top_k', 40)
            typical_p = kwargs.get('typical_p', 0.8)
            num_ctx = kwargs.get('num_ctx', 8192)
            
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "top_p": top_p,
                    "top_k": top_k,
                    "typical_p": typical_p,
                    "num_ctx": num_ctx
                }
            }
            
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=kwargs.get('timeout', 180)
            )
            
            if response.status_code == 200:
                result = response.json()
                return result['message']['content'].strip()
            else:
                return None
                
        except Exception:
            return None
    
    def send_message_streaming(self, messages: list[dict], model: str, **kwargs) -> Generator[str, None, None]:
        if model not in self.available_models:
            yield ""
            return
            
        try:
            temperature = kwargs.get('temperature', 0.69)
            top_p = kwargs.get('top_p', 0.7)
            top_k = kwargs.get('top_k', 40)
            typical_p = kwargs.get('typical_p', 0.8)
            num_ctx = kwargs.get('num_ctx', 8192)
            
            payload = {
                "model": model,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": temperature,
                    "top_p": top_p,
                    "top_k": top_k,
                    "typical_p": typical_p,
                    "num_ctx": num_ctx
                }
            }
            
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=kwargs.get('timeout', 180),
                stream=True
            )
            
            if response.status_code == 200:
                for line in response.iter_lines():
                    if line:
                        try:
                            json_data = json.loads(line.decode('utf-8'))
                            if 'message' in json_data and 'content' in json_data['message']:
                                yield json_data['message']['content']
                        except json.JSONDecodeError:
                            continue
            else:
                yield ""
                
        except Exception as e:
            yield f"Error: {str(e)}"

class CerebrasProvider(AIProvider):
    def __init__(self, config: dict | None = None):
        super().__init__("cerebras", config)
        self.base_url = "https://api.cerebras.ai/v1/chat/completions"
        self.api_key = self._load_api_key()
        self.is_available = bool(self.api_key)
        self.available_models = [
            "qwen-3-235b-a22b-instruct-2507",
            "qwen-3-235b-a22b-thinking-2507",
            "qwen-3-coder-480b",
            "qwen-3-32b",
            "gpt-oss-120b",
            "llama-3.3-70b",
            "llama-4-scout-17b-16e-instruct",
            "llama3.1-8b"
        ]
    
    def _load_api_key(self):
        try:
            api_key = Database.get_api_key('cerebras')
            return api_key
        except Exception:
            return None

    def get_models(self) -> list[str]:
        return self.available_models

    def send_message(self, messages: list[dict], model: str, **kwargs) -> str | None:
        if not self.api_key or model not in self.available_models:
            return None

        try:
            # Normalize messages (convert custom tool roles to assistant)
            messages = self._normalize_messages(messages)

            temperature = kwargs.get('temperature', 0.69)
            max_tokens = kwargs.get('max_tokens')
            top_p = kwargs.get('top_p', 0.7)
            top_k = kwargs.get('top_k', 40)
            typical_p = kwargs.get('typical_p', 0.8)

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "top_p": top_p,
                "top_k": top_k,
                "typical_p": typical_p,
                "stream": False
            }

            # Debug: Log summary (not full payload)
            # Count only new messages (not historical context from DB)
            sum(1 for m in messages if m.get('role') == 'user' and m == messages[-1])
            logger.debug(f"[Cerebras] {model} | new_msg=1 | max_tokens={max_tokens or 'unlimited'}")

            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=kwargs.get('timeout', 120)
            )

            # Debug: Log response
            if response.status_code != 200:
                logger.debug(f"[Cerebras] Error {response.status_code}: {response.text[:200]}")
            else:
                logger.debug(f"[Cerebras] OK {response.status_code}")

            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content'].strip()
            else:
                return None
                
        except Exception:
            return None
    
    def send_message_streaming(self, messages: list[dict], model: str, **kwargs) -> Generator[str, None, None]:
        if not self.api_key or model not in self.available_models:
            yield ""
            return

        try:
            # Normalize messages (convert custom tool roles to assistant)
            messages = self._normalize_messages(messages)

            temperature = kwargs.get('temperature', 0.69)
            max_tokens = kwargs.get('max_tokens')
            top_p = kwargs.get('top_p', 0.7)
            top_k = kwargs.get('top_k', 40)
            typical_p = kwargs.get('typical_p', 0.8)

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "top_p": top_p,
                "top_k": top_k,
                "typical_p": typical_p,
                "stream": True
            }

            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=kwargs.get('timeout', 120),
                stream=True
            )
            
            if response.status_code == 200:
                for line in response.iter_lines():
                    if line:
                        try:
                            if line.startswith(b'data: '):
                                json_data = json.loads(line[6:])
                                if 'choices' in json_data and len(json_data['choices']) > 0:
                                    delta = json_data['choices'][0].get('delta', {})
                                    if 'content' in delta and delta['content']:
                                        yield delta['content']
                        except (json.JSONDecodeError, KeyError):
                            continue
            else:
                yield ""
                
        except Exception as e:
            yield f"Error: {str(e)}"

class OpenRouterProvider(AIProvider):
    def __init__(self, config: dict | None = None):
        super().__init__("openrouter", config)
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        self.api_key = self._load_api_key()
        self.is_available = bool(self.api_key)
        self.available_models = [
            "deepseek/deepseek-chat-v3-0324:free",
            "deepseek/deepseek-chat-v3.1:free", 
            "deepseek/deepseek-r1:free",
            "google/gemini-flash-1.5-8b:free",
            "google/gemini-flash-1.5:free",
            "meituan/longcat-flash-chat:free",
            "openai/gpt-4o-mini:free",
            "openai/gpt-4o-mini-2024-07-18:free",
            "qwen/qwen3-235b-a22b:free",
            "qwen/qwen3-vl-235b-a22b-instruct:free",
            "tngtech/deepseek-r1-chimera:free",
            "tngtech/deepseek-r1t2-chimera:free",
            "z-ai/glm-4.5-air:free",
            "z-ai/glm-4.5-air-2507:free",
            "x-ai/grok-4.1-fast:free",
            
            "deepseek/deepseek-chat-v3-0324",
            "deepseek/deepseek-chat-v3.1",
            "deepseek/deepseek-v3.2",
            "deepseek/deepseek-v3.2-exp",
            "deepseek/deepseek-v3.2-speciale",
            "google/gemma-3-12b",
            "xiaomi/mimo-v2-flash",
            "minimax/minimax-m2",
            "moonshotai/kimi-k2.5",
            "moonshotai/kimi-k2-0905",
            "openai/gpt-oss-120b",
            "qwen/qwen3-235b-a22b-2507",
            "qwen/qwen3-coder",
            "qwen/qwen3.5-397b-a17b",
            "qwen/qwen3.5-plus-02-15",
            "tngtech/deepseek-r1t2-chimera",
            "z-ai/glm-4.6",
            "z-ai/glm-4.7"
        ]
    
    def _load_api_key(self):
        try:
            api_key = Database.get_api_key('openrouter')
            return api_key
        except Exception:
            return None

    def _normalize_messages(self, messages: list[dict]) -> list[dict]:
        """Normalize messages: convert custom tool roles to standard 'assistant' role."""
        if not messages:
            return messages

        standard_roles = {'system', 'user', 'assistant', 'tool'}
        normalized = []

        for msg in messages:
            role = msg.get('role', '')
            if role not in standard_roles:
                # Custom tool role - convert to assistant
                content = msg.get('content', '')
                normalized_content = f"[{role}]\n{content}"
                normalized.append({
                    'role': 'assistant',
                    'content': normalized_content
                })
            else:
                normalized.append(msg)

        return normalized

    def get_models(self) -> list[str]:
        return self.available_models

    def send_message(self, messages: list[dict], model: str, **kwargs) -> str | None:
        if not self.api_key or model not in self.available_models:
            return None

        try:
            # Normalize messages (convert custom tool roles to assistant)
            messages = self._normalize_messages(messages)

            if self.supports_vision(model) and messages:
                last_user_message = self._get_last_user_message(messages)
                if last_user_message and multimodal_tools.has_images(last_user_message):
                    vision_messages = self.format_vision_message(last_user_message)
                    messages = self._replace_last_user_message(messages, last_user_message, vision_messages)
            
            temperature = kwargs.get('temperature', 0.73)
            max_tokens = kwargs.get('max_tokens')
            top_p = kwargs.get('top_p', 0.9)
            top_k = kwargs.get('top_k', 40)
            typical_p = kwargs.get('typical_p', 0.8)
            
            # Free tier rate limiting
            if model.endswith(':free'):
                max_tokens = min(max_tokens, 2048)
                temperature = min(temperature, 0.8)
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/icedeyes12/yuzu-companion",
                "X-Title": "Yuzu-Companion"
            }
            
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "top_p": top_p,
                "top_k": top_k,
                "typical_p": typical_p,
                "stream": False
            }
            # Add tools if provided (for function calling)
            tools = kwargs.get('tools')
            if tools:
                payload["tools"] = tools

            # Debug: Log summary (not full payload)
            logger.debug(f"[OpenRouter] {model} | max_tokens={max_tokens or 'unlimited'}")

            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=kwargs.get('timeout', 180)
            )

            # Debug: Log response
            if response.status_code != 200:
                logger.debug(f"[OpenRouter] Error {response.status_code}: {response.text[:200]}")
            else:
                logger.debug(f"[OpenRouter] OK {response.status_code}")

            if response.status_code == 200:
                result = response.json()
                message = result['choices'][0]['message']
                content = message.get('content', '')
                return content.strip() if content else ''
            else:
                if response.status_code == 402:
                    return "OpenRouter free tier limit reached. Please try a different model or add credits."
                elif response.status_code == 429:
                    return "Rate limit exceeded. Please wait a moment and try again."
                else:
                    return None
                
        except Exception:
            return None
    
    def send_message_streaming(self, messages: list[dict], model: str, **kwargs) -> Generator[str, None, None]:
        if not self.api_key or model not in self.available_models:
            yield ""
            return
        
        try:
            if self.supports_vision(model) and messages:
                last_user_message = self._get_last_user_message(messages)
                if last_user_message and multimodal_tools.has_images(last_user_message):
                    vision_messages = self.format_vision_message(last_user_message)
                    messages = self._replace_last_user_message(messages, last_user_message, vision_messages)
            
            temperature = kwargs.get('temperature', 0.73)
            max_tokens = kwargs.get('max_tokens')
            top_p = kwargs.get('top_p', 0.9)
            top_k = kwargs.get('top_k', 40)
            typical_p = kwargs.get('typical_p', 0.8)
            
            # Free tier rate limiting
            if model.endswith(':free'):
                max_tokens = min(max_tokens, 2048)
                temperature = min(temperature, 0.8)
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/icedeyes12/yuzu-companion",
                "X-Title": "Yuzu-Companion"
            }
            
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "top_p": top_p,
                "top_k": top_k,
                "typical_p": typical_p,
                "stream": True
            }
            
            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=kwargs.get('timeout', 180),
                stream=True
            )
            
            if response.status_code == 200:
                for line in response.iter_lines():
                    if line:
                        try:
                            if line.startswith(b'data: '):
                                if line == b'data: [DONE]':
                                    break
                                json_data = json.loads(line[6:])
                                if 'choices' in json_data and len(json_data['choices']) > 0:
                                    delta = json_data['choices'][0].get('delta', {})
                                    if 'content' in delta and delta['content']:
                                        yield delta['content']
                        except (json.JSONDecodeError, KeyError):
                            continue
            else:
                yield ""
                
        except Exception as e:
            yield f"Error: {str(e)}"

    def parse_tool_calls(self, raw_response) -> list[dict]:
        """Parse tool_calls from OpenRouter API response.
        
        Returns list of {"name": str, "arguments": dict, "id": str}.
        """
        if not isinstance(raw_response, dict):
            return []
        try:
            message = raw_response.get("choices", [{}])[0].get("message", {})
            tool_calls = message.get("tool_calls", [])
            results = []
            for tc in tool_calls:
                fn = tc.get("function", {})
                results.append({
                    "id": tc.get("id", ""),
                    "name": fn.get("name", ""),
                    "arguments": json.loads(fn.get("arguments", "{}")),
                })
            return results
        except Exception:
            return []

class ChutesProvider(AIProvider):
    def __init__(self, config: dict | None = None):
        super().__init__("chutes", config)
        self.base_url = "https://llm.chutes.ai/v1/chat/completions"
        self.api_key = self._load_api_key()
        self.is_available = bool(self.api_key)
        self._last_error = None  # Track last error for retry logic
        self.available_models = [
            "Qwen/Qwen3-VL-235B-A22B-Instruct",
            "Qwen/Qwen3.5-397B-A17B-TEE",
            "deepseek-ai/DeepSeek-V3-0324",
            "deepseek-ai/DeepSeek-V3.1",
            "deepseek-ai/DeepSeek-V3.1-Terminus",
            "deepseek-ai/DeepSeek-V3.2-Exp",
            "moonshotai/Kimi-K2-Instruct-0905",
            "moonshotai/Kimi-K2.5-TEE",
            "moonshotai/Kimi-K2.6-TEE",
            "tngtech/DeepSeek-TNG-R1T-Chimera",
            "tngtech/DeepSeek-TNG-R1T2-Chimera",
            "Qwen/Qwen3-Next-80B-A3B-Instruct",
            "Qwen/Qwen3-30B-A3B",
            "Qwen/Qwen3-235B-A22B-Thinking-2507",
            "Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8-TEE",
            "zai-org/GLM-4.5-TEE",
            "zai-org/GLM-4.6-TEE",
            "zai-org/GLM-4.7-TEE",
            "deepseek-ai/DeepSeek-R1"
        ]
    
    def _normalize_messages_for_chutes(self, messages: list[dict]) -> list[dict]:
        """Normalize messages for Chutes API: ensure single system message at the beginning
        and convert custom tool roles to standard 'assistant' role."""
        if not messages:
            return messages

        # Standard OpenAI-compatible roles
        standard_roles = {'system', 'user', 'assistant', 'tool'}

        # Collect all system messages and normalize other messages
        system_contents = []
        normalized_messages = []

        for msg in messages:
            role = msg.get('role', '')

            if role == 'system':
                system_contents.append(msg.get('content', ''))
            elif role not in standard_roles:
                # Custom tool role (e.g., image_tools, request_tools) - convert to assistant
                content = msg.get('content', '')
                normalized_content = f"[{role}]\n{content}"
                normalized_messages.append({
                    'role': 'assistant',
                    'content': normalized_content
                })
            else:
                # Standard role - keep as-is
                normalized_messages.append(msg)

        # Merge all system messages into one
        if system_contents:
            merged_system = '\n\n'.join(system_contents)
            return [{'role': 'system', 'content': merged_system}] + normalized_messages
        else:
            return normalized_messages
    
    def _load_api_key(self):
        try:
            api_key = Database.get_api_key('chutes')
            return api_key
        except Exception:
            return None
    
    def get_models(self) -> list[str]:
        return self.available_models
    
    def send_message(self, messages: list[dict], model: str, **kwargs) -> str | None:
        """Send a message.
        
        log_prefix: defaults to "[CHAT]" for user-facing calls.
                    Callers that want "[INT]" should pass log_prefix="[INT]".
        """
        if not self.api_key or model not in self.available_models:
            return None

        log_prefix = kwargs.pop("log_prefix", "[CHAT]")

        # Prevent duplicate 'model' kwarg if caller passed it
        kwargs.pop('model', None)
        kwargs.pop('model_name', None)

        # Determine if model was explicitly requested (user picked it) vs auto-selected
        model_hint = kwargs.get('model') or kwargs.get('model_name')
        explicit_model = model_hint and model_hint in self.available_models

        # Retryable error codes — try another Chutes model before giving up
        retryable_codes = {0, 400, 429, 500, 502, 503, 504}

        attempt = 0
        last_error = None

        # Try up to 3 Chutes models before falling back
        max_attempts = 3

        while attempt < max_attempts:
            attempt += 1
            current_model = model if attempt == 1 else None

            # On retry, pick next available model (skip if it was explicitly requested)
            if current_model is None:
                tried = set()
                if attempt > 1:
                    # Already tried model on first attempt
                    tried.add(model)
                # Try models in order of preference (Qwen first)
                priority = [m for m in self.available_models if m not in tried]
                # Prefer Qwen models for better tool-calling support
                qwen_first = sorted(priority, key=lambda m: 0 if 'Qwen' in m else 1)
                for candidate in qwen_first:
                    if explicit_model and candidate == model_hint:
                        continue
                    tried.add(candidate)
                    current_model = candidate
                    break

            if not current_model:
                break

            result = self._chutes_raw(current_model, messages, kwargs)
            status = result[0]
            data = result[1]

            if status == 200:
                self._last_error = None  # Clear error on success
                return data

            last_error = result[2] if len(result) > 2 else str(status)
            self._last_error = last_error  # Store for retry logic

            # Only retry on retryable errors
            if status not in retryable_codes:
                return None

            logger.debug(f"{log_prefix} {current_model} failed ({status}), retrying with another model...")

        logger.debug(f"{log_prefix} All models exhausted, last error: {last_error}")
        return None

    def _chutes_raw(self, model: str, messages: list[dict], kwargs) -> tuple:
        """Single Chutes API call. Returns (status_code, content_or_None, error_detail)."""
        messages = self._normalize_messages_for_chutes(list(messages))

        if kwargs.get('skip_vision') is True:
            pass
        elif self.supports_vision(model) and messages:
            last_user_message = self._get_last_user_message(messages)
            if last_user_message:
                has_img = multimodal_tools.has_images(last_user_message)
                if has_img:
                    logger.debug(f"[Vision] Triggered for message: {last_user_message[:100]}...")
                    vision_messages = self.format_vision_message(last_user_message)
                    messages = self._replace_last_user_message(messages, last_user_message, vision_messages)

        temperature = kwargs.get('temperature', 0.73)
        max_tokens = kwargs.get('max_tokens')
        top_p = kwargs.get('top_p', 0.9)
        top_k = kwargs.get('top_k', 45)
        stream = kwargs.get('stream', False)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
            "top_k": top_k,
            "stream": stream
        }
        # NOTE: Chutes does NOT support native tool calling.
        # Strip tools to avoid confusing the model - rely on /command detection instead.
        # tools = kwargs.get('tools')
        # if tools:
        #     payload["tools"] = tools

        log_prefix = kwargs.pop('log_prefix', '[CHAT]')
        logger.debug(f"{log_prefix} {model} | max_tokens={max_tokens or 'unlimited'}")

        try:
            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=kwargs.get('timeout', 120),
            )
            if response.status_code == 200:
                return (200, response.json()['choices'][0]['message']['content'].strip())
            else:
                return (response.status_code, None, response.text[:200])
        except Exception as e:
            return (0, None, str(e))
    
    def send_message_streaming(self, messages: list[dict], model: str, **kwargs) -> Generator[str, None, None]:
        if not self.api_key or model not in self.available_models:
            yield ""
            return
        
        try:
            # Normalize messages for Chutes API (system message must be first)
            messages = self._normalize_messages_for_chutes(messages)
            
            if self.supports_vision(model) and messages:
                last_user_message = self._get_last_user_message(messages)
                if last_user_message and multimodal_tools.has_images(last_user_message):
                    vision_messages = self.format_vision_message(last_user_message)
                    messages = self._replace_last_user_message(messages, last_user_message, vision_messages)
            
            temperature = kwargs.get('temperature', 0.73)
            max_tokens = kwargs.get('max_tokens')
            top_p = kwargs.get('top_p', 0.9)
            top_k = kwargs.get('top_k', 45)
            typical_p = kwargs.get('typical_p', 0.85)
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "top_p": top_p,
                "top_k": top_k,
                "typical_p": typical_p,
                "stream": True
            }
            
            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=kwargs.get('timeout', 120),
                stream=True
            )
            
            if response.status_code == 200:
                for line in response.iter_lines():
                    if line:
                        try:
                            if line.startswith(b'data: '):
                                if line == b'data: [DONE]':
                                    break
                                json_data = json.loads(line[6:])
                                if 'choices' in json_data and len(json_data['choices']) > 0:
                                    delta = json_data['choices'][0].get('delta', {})
                                    if 'content' in delta and delta['content']:
                                        yield delta['content']
                        except (json.JSONDecodeError, KeyError):
                            continue
            else:
                logger.error(f"[ERROR] Chutes streaming API error {response.status_code}: {response.text}")
                yield ""
                
        except Exception as e:
            logger.error(f"[ERROR] Chutes send_message_streaming exception: {str(e)}")
            yield f"Error: {str(e)}"

class AIProviderManager:
    def __init__(self):
        self.providers = {}
        self.load_providers()
    
    def load_providers(self):
        ollama = OllamaProvider()
        if ollama.test_connection():
            self.providers["ollama"] = ollama
        
        cerebras = CerebrasProvider()
        if cerebras.is_available:
            self.providers["cerebras"] = cerebras
        
        openrouter = OpenRouterProvider()
        if openrouter.is_available:
            self.providers["openrouter"] = openrouter
        
        chutes = ChutesProvider()
        if chutes.is_available:
            self.providers["chutes"] = chutes
    
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
    
    def send_message(self, provider_name: str, model: str, messages: list[dict], **kwargs) -> str | None:
        if provider_name not in self.providers:
            return None
        
        provider = self.providers[provider_name]
        start_time = time.time()
        response = provider.send_message(messages, model, **kwargs)
        response_time = time.time() - start_time
        if response:
            return response
        logger.warning(f"[ProviderManager] {provider_name} failed after {response_time:.1f}s")
        return None
    
    def send_message_streaming(self, provider_name: str, model: str, messages: list[dict], **kwargs) -> Generator[str, None, None]:
        if provider_name not in self.providers:
            yield ""
            return
        
        provider = self.providers[provider_name]
        start_time = time.time()
        
        try:
            for chunk in provider.send_message_streaming(messages, model, **kwargs):
                yield chunk
            
            time.time() - start_time
            # REMOVED: No print statement to avoid timing duplication
            
        except Exception as e:
            yield f"Streaming error: {str(e)}"

    # Preferred models for internal (non-chat) LLM calls
    _PREFERRED_MODELS = [
        "Qwen/Qwen3-Next-80B-A3B-Instruct",
        "Qwen/Qwen3-235B-A22B-Instruct-2507-TEE",
    ]

    def _best_model(self, provider: str) -> str | None:
        """Pick the best available model for internal LLM tasks."""
        if provider not in self.providers:
            return None
        provider_obj = self.providers[provider]
        models = provider_obj.get_models()
        if not models:
            return None
        
        for preferred in self._PREFERRED_MODELS:
            if preferred in models:
                return preferred
        return models[0] if models else None

    def _internal_llm_call(self, messages: list[dict], **kwargs) -> str | None:
        """Dedicated internal LLM call for memory extractor, summarizer, etc.
        
        Uses Chutes only, with ordered model preference:
          1. Qwen/Qwen3-Next-80B-A3B-Instruct  (primary, retry 2x)
          2. Qwen/Qwen3-235B-A22B-Instruct-2507-TEE  (fallback, retry 1x)
        
        Retry logic:
          - Retry only on connection errors (timeout, network issues)
          - Do NOT retry on specific errors (rate limit, auth, 4xx)
        """
        if 'chutes' not in self.providers:
            return None
        provider = self.providers['chutes']
        
        MAIN_MODEL = "Qwen/Qwen3-Next-80B-A3B-Instruct"
        FALLBACK_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507-TEE"
        
        def _is_connection_error(error: str | None) -> bool:
            """Check if error is a connection/network issue (retryable)."""
            if not error:
                return True  # No error info, assume retryable
            error_lower = error.lower()
            # Connection errors are retryable
            retryable = ['timeout', 'connection', 'network', 'refused', 'reset', 'socket', 'timed out']
            return any(r in error_lower for r in retryable)
        
        # Try main model (3 attempts: initial + 2 retries)
        for attempt in range(3):
            result = provider.send_message(messages, MAIN_MODEL, log_prefix="[INT]", skip_vision=True, **kwargs)
            if result:
                logger.debug(f"[INT] chutes/{MAIN_MODEL} OK (attempt {attempt + 1})")
                return result
            
            # Get last error from provider (if available)
            last_error = getattr(provider, '_last_error', None)
            if not _is_connection_error(last_error):
                logger.debug(f"[INT] chutes/{MAIN_MODEL} failed (non-retryable error)")
                break
            
            if attempt < 2:
                logger.debug(f"[INT] chutes/{MAIN_MODEL} failed (attempt {attempt + 1}), retrying...")
                time.sleep(0.5)
        
        logger.debug(f"[INT] chutes/{MAIN_MODEL} exhausted, trying fallback...")
        
        # Try fallback model (2 attempts: initial + 1 retry)
        for attempt in range(2):
            result = provider.send_message(messages, FALLBACK_MODEL, log_prefix="[INT]", skip_vision=True, **kwargs)
            if result:
                logger.debug(f"[INT] chutes/{FALLBACK_MODEL} OK (attempt {attempt + 1})")
                return result
            
            last_error = getattr(provider, '_last_error', None)
            if not _is_connection_error(last_error):
                logger.debug(f"[INT] chutes/{FALLBACK_MODEL} failed (non-retryable error)")
                break
            
            if attempt < 1:
                logger.debug(f"[INT] chutes/{FALLBACK_MODEL} failed (attempt {attempt + 1}), retrying...")
                time.sleep(0.5)
        
        logger.debug("[INT] all internal models failed")
        return None

    def auto_send_message(self, messages: list[dict], **kwargs) -> str | None:
        """Auto-select Chutes model for internal LLM calls.
        
        Same logic as _internal_llm_call:
          1. Qwen/Qwen3-Next-80B-A3B-Instruct  (retry 2x)
          2. Qwen/Qwen3-235B-A22B-Instruct-2507-TEE  (retry 1x)
        """
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
