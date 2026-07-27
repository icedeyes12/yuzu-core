"""(｡•̀ᴗ-)✧"""

from __future__ import annotations

import hashlib
import json
from typing import Any

OPENAI_MESSAGE_FIELDS = {
    "system": {"role", "content", "name"},
    "user": {"role", "content", "name"},
    "assistant": {
        "role",
        "content",
        "name",
        "refusal",
        "audio",
        "tool_calls",
        "function_call",
    },
    "tool": {"role", "content", "tool_call_id"},
}
OPENAI_ROLES = frozenset(OPENAI_MESSAGE_FIELDS)
OPENAI_REQUEST_FIELDS = frozenset(
    {
        "model",
        "messages",
        "stream",
        "stream_options",
        "temperature",
        "max_tokens",
        "max_completion_tokens",
        "top_p",
        "n",
        "stop",
        "modalities",
        "prediction",
        "audio",
        "response_format",
        "seed",
        "service_tier",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "logprobs",
        "top_logprobs",
        "frequency_penalty",
        "presence_penalty",
        "reasoning_effort",
        "metadata",
        "store",
        "user",
    }
)


class OpenAIProtocolError(ValueError):
    """(｡•̀ᴗ-)✧"""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _json_object(value: Any) -> str | None:
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value) if value.strip() else {}
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))


def _deterministic_call_id(message_index: int, call_index: int, call: dict) -> str:
    seed = json.dumps(
        {
            "message": message_index,
            "call": call_index,
            "name": call.get("function", {}).get("name") or call.get("name"),
            "arguments": call.get("function", {}).get("arguments")
            or call.get("arguments", {}),
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return f"call_hist_{hashlib.sha256(seed.encode()).hexdigest()[:20]}"


def normalize_tool_calls(
    tool_calls: Any, message_index: int = 0
) -> list[dict[str, Any]]:
    """(｡•̀ᴗ-)✧"""
    if not isinstance(tool_calls, list):
        return []
    normalized: list[dict[str, Any]] = []
    for call_index, raw_call in enumerate(tool_calls):
        if not isinstance(raw_call, dict):
            continue
        function = raw_call.get("function")
        if not isinstance(function, dict):
            function = raw_call
        name = function.get("name")
        arguments = _json_object(function.get("arguments", {}))
        if not isinstance(name, str) or not name.strip() or arguments is None:
            continue
        call_id = raw_call.get("id")
        if not isinstance(call_id, str) or not call_id.strip():
            call_id = _deterministic_call_id(message_index, call_index, raw_call)
        normalized.append(
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name.strip(),
                    "arguments": arguments,
                },
            }
        )
    return normalized


def _sanitize_content(role: str, content: Any) -> Any:
    if isinstance(content, str) or content is None:
        return content
    if not isinstance(content, list):
        return str(content)
    allowed_types = {
        "system": {"text"},
        "user": {"text", "image_url", "input_audio", "file"},
        "assistant": {"text", "refusal"},
        "tool": {"text"},
    }[role]
    parts: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict) or part.get("type") not in allowed_types:
            continue
        part_type = part["type"]
        if part_type in {"text", "refusal"} and isinstance(part.get(part_type), str):
            parts.append({"type": part_type, part_type: part[part_type]})
        elif part_type == "image_url" and isinstance(part.get("image_url"), dict):
            image_url = part["image_url"]
            clean_image_url = {
                key: image_url[key] for key in ("url", "detail") if key in image_url
            }
            if isinstance(clean_image_url.get("url"), str):
                parts.append({"type": part_type, "image_url": clean_image_url})
        elif part_type == "input_audio" and isinstance(part.get("input_audio"), dict):
            audio = part["input_audio"]
            clean_audio = {
                key: audio[key] for key in ("data", "format") if key in audio
            }
            if all(isinstance(clean_audio.get(key), str) for key in ("data", "format")):
                parts.append({"type": part_type, "input_audio": clean_audio})
        elif part_type == "file" and isinstance(part.get("file"), dict):
            file_part = part["file"]
            clean_file = {
                key: file_part[key]
                for key in ("file_data", "file_id", "filename")
                if key in file_part
            }
            if clean_file:
                parts.append({"type": part_type, "file": clean_file})
    return parts


def sanitize_openai_messages(messages: Any) -> list[dict[str, Any]]:
    """(｡•̀ᴗ-)✧"""
    if not isinstance(messages, list):
        return []
    sanitized: list[dict[str, Any]] = []
    for message_index, raw_message in enumerate(messages):
        if not isinstance(raw_message, dict):
            sanitized.append({"role": "", "content": ""})
            continue
        role = raw_message.get("role", "")
        if role not in OPENAI_ROLES:
            sanitized.append(dict(raw_message))
            continue
        clean = {
            key: raw_message[key]
            for key in OPENAI_MESSAGE_FIELDS[role]
            if key in raw_message
        }
        clean["role"] = role
        if "content" in clean:
            clean["content"] = _sanitize_content(role, clean["content"])
        if role == "assistant" and "tool_calls" in clean:
            clean["tool_calls"] = normalize_tool_calls(
                clean["tool_calls"], message_index=message_index
            )
        sanitized.append(clean)
    return sanitized


def sanitize_and_validate_messages(messages: Any) -> list[dict[str, Any]]:
    """(｡•̀ᴗ-)✧"""
    clean = sanitize_openai_messages(messages)
    validate_openai_messages(clean)
    return clean


def sanitize_openai_request(
    messages: Any,
    *,
    model: str,
    stream: bool,
    tools: Any = None,
    tool_choice: Any = None,
    parallel_tool_calls: Any = None,
    **parameters: Any,
) -> dict[str, Any]:
    """(｡•̀ᴗ-)✧"""
    parameters = {
        key: value for key, value in parameters.items() if key in OPENAI_REQUEST_FIELDS
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": sanitize_openai_messages(messages),
        "stream": bool(stream),
    }
    for key, value in parameters.items():
        if value is not None:
            payload[key] = value
    if tools is not None:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    if parallel_tool_calls is not None:
        payload["parallel_tool_calls"] = bool(parallel_tool_calls)
    return payload


def sanitize_openai_payload(
    payload: Any, *, provider_extensions: set[str] | frozenset[str] = frozenset()
) -> dict[str, Any]:
    """(｡•̀ᴗ-)✧"""
    if not isinstance(payload, dict):
        raise OpenAIProtocolError(["request payload must be an object"])
    allowed = OPENAI_REQUEST_FIELDS | set(provider_extensions)
    return {
        key: value
        for key, value in payload.items()
        if key in allowed and value is not None
    }


def validate_openai_messages(messages: Any) -> None:
    """(｡•̀ᴗ-)✧"""
    errors: list[str] = []
    if not isinstance(messages, list) or not messages:
        raise OpenAIProtocolError(["messages must be a non-empty list"])

    pending_ids: set[str] = set()
    seen_call_ids: set[str] = set()
    previous_role: str | None = None

    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            errors.append(f"messages[{index}] is not an object")
            continue
        role = message.get("role")
        if role not in OPENAI_ROLES:
            errors.append(f"messages[{index}] has invalid role {role!r}")
            continue
        unknown = set(message) - OPENAI_MESSAGE_FIELDS[role]
        if unknown:
            errors.append(f"messages[{index}] has invalid fields {sorted(unknown)!r}")
        if role == "tool":
            tool_call_id = message.get("tool_call_id")
            if not isinstance(tool_call_id, str) or not tool_call_id.strip():
                errors.append(f"messages[{index}] has invalid tool_call_id")
            elif tool_call_id not in pending_ids:
                errors.append(
                    f"messages[{index}] tool_call_id {tool_call_id!r} has no matching tool call"
                )
            else:
                pending_ids.remove(tool_call_id)
            previous_role = role
            continue

        if pending_ids:
            errors.append(
                f"messages[{index}] starts before tool responses are complete: "
                f"missing {sorted(pending_ids)!r}"
            )
            pending_ids.clear()

        if role == "assistant":
            tool_calls = message.get("tool_calls")
            if tool_calls == []:
                tool_calls = None
            if tool_calls is not None:
                if previous_role not in {"user", "tool", "system"}:
                    errors.append(
                        f"messages[{index}] assistant tool_calls must immediately follow "
                        f"a user, tool, or system turn, got {previous_role!r}"
                    )
                if not isinstance(tool_calls, list):
                    errors.append(f"messages[{index}] tool_calls is not a list")
                else:
                    local_ids: set[str] = set()
                    for call_index, call in enumerate(tool_calls):
                        if not isinstance(call, dict):
                            errors.append(
                                f"messages[{index}].tool_calls[{call_index}] is not an object"
                            )
                            continue
                        call_id = call.get("id")
                        function = call.get("function")
                        if not isinstance(call_id, str) or not call_id.strip():
                            errors.append(
                                f"messages[{index}].tool_calls[{call_index}] has invalid id"
                            )
                        elif call_id in local_ids or call_id in seen_call_ids:
                            errors.append(
                                f"messages[{index}] duplicates tool_call_id {call_id!r}"
                            )
                        else:
                            local_ids.add(call_id)
                            seen_call_ids.add(call_id)
                        if call.get("type") != "function":
                            errors.append(
                                f"messages[{index}].tool_calls[{call_index}] type is not function"
                            )
                        if not isinstance(function, dict):
                            errors.append(
                                f"messages[{index}].tool_calls[{call_index}] has no function"
                            )
                        else:
                            if (
                                not isinstance(function.get("name"), str)
                                or not function["name"].strip()
                            ):
                                errors.append(
                                    f"messages[{index}].tool_calls[{call_index}] has invalid function.name"
                                )
                            if not isinstance(function.get("arguments"), str):
                                errors.append(
                                    f"messages[{index}].tool_calls[{call_index}] has invalid function.arguments"
                                )
                    pending_ids.update(local_ids)
            elif (
                "content" not in message or message.get("content") is None
            ) and not message.get("refusal"):
                errors.append(f"messages[{index}] assistant content is missing or null")
        elif role in {"system", "user"} and "content" not in message:
            errors.append(f"messages[{index}] {role} content is missing")
        previous_role = role

    if pending_ids:
        errors.append(f"missing tool responses for {sorted(pending_ids)!r}")
    if errors:
        raise OpenAIProtocolError(errors)


def validate_chat_completion_response(response: Any) -> tuple[list[str], list[str]]:
    """(｡•̀ᴗ-)✧"""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(response, dict):
        return ["response is not an object"], warnings
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ["response choices is empty or invalid"], warnings
    for index, choice in enumerate(choices):
        if not isinstance(choice, dict):
            errors.append(f"choices[{index}] is not an object")
            continue
        message = choice.get("message") or {}
        if not isinstance(message, dict):
            errors.append(f"choices[{index}].message is not an object")
            continue
        tool_calls = message.get("tool_calls") or []
        finish_reason = choice.get("finish_reason")
        if finish_reason == "tool_calls" and not tool_calls:
            errors.append(
                f"choices[{index}] has finish_reason=tool_calls without tool_calls"
            )
        if tool_calls and finish_reason not in {None, "tool_calls"}:
            warnings.append(
                f"choices[{index}] has tool_calls with finish_reason={finish_reason!r}"
            )
    return errors, warnings
