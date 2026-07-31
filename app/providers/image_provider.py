from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx

from app.core.byok import (
    CHUTES,
    DEFAULT_YUZU_PORTAL_BASE_URL,
    YUZU_PORTAL,
    get_provider_base_url,
    get_provider_key,
)

logger = logging.getLogger(__name__)

CHUTES_MODELS = {
    "z-image-turbo": (
        "https://vonkaiser-z-image-turbo.chutes.ai/generate",
        "generate",
    ),
    "qwen-image": (
        "https://vonkaiser-qwen-image-2512.chutes.ai/generate",
        "generate",
    ),
    "qwen-image-edit": (
        "https://vonkaiser-qwen-image-edit-2511.chutes.ai/generate",
        "edit",
    ),
}

PORTAL_MODELS = {"ag/gemini-3.1-flash-image", "gemini/gemini-2.5-flash-image"}


def _provider_for_model(model: str, requested_provider: str | None) -> str | None:
    if requested_provider:
        return requested_provider
    if model in CHUTES_MODELS:
        return CHUTES
    if model in PORTAL_MODELS or "/" in model:
        return YUZU_PORTAL
    return None


def _key_for(provider: str) -> str | None:
    return get_provider_key(provider)


def _portal_base_url() -> str:
    return get_provider_base_url(YUZU_PORTAL) or DEFAULT_YUZU_PORTAL_BASE_URL


def _chutes_payload(
    model: str, prompt: str, image_bytes: bytes | None
) -> dict[str, Any]:
    if model == "z-image-turbo":
        return {
            "seed": 42,
            "shift": 3,
            "width": 1024,
            "height": 1024,
            "prompt": prompt,
            "guidance_scale": 0,
            "max_sequence_length": 512,
            "num_inference_steps": 9,
        }
    if model == "qwen-image":
        return {
            "prompt": prompt,
            "seed": 42,
            "width": 1024,
            "height": 1024,
            "true_cfg_scale": 4,
            "negative_prompt": "",
            "num_inference_steps": 30,
        }
    return {
        "prompt": prompt,
        "seed": 42,
        "width": 1024,
        "height": 1024,
        "image_b64s": [base64.b64encode(image_bytes or b"").decode("ascii")],
        "true_cfg_scale": 1,
        "negative_prompt": "",
        "num_inference_steps": 4,
    }


def _portal_payload(model: str, prompt: str) -> dict[str, Any]:
    return {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": "auto",
        "quality": "auto",
        "background": "auto",
        "image_detail": "high",
        "output_format": "png",
    }


def _decode_image_response(data: Any) -> bytes | None:
    if isinstance(data, dict):
        for key in ("image", "image_b64", "b64_json"):
            value = data.get(key)
            if isinstance(value, str):
                try:
                    return base64.b64decode(value)
                except (ValueError, TypeError):
                    return None
        images = data.get("images") or data.get("data")
        if isinstance(images, list):
            for item in images:
                result = _decode_image_response(item)
                if result:
                    return result
        url = data.get("url")
        if isinstance(url, str) and url.startswith("data:image/") and "," in url:
            try:
                return base64.b64decode(url.split(",", 1)[1])
            except (ValueError, TypeError):
                return None
    return None


async def request_image(
    model: str,
    prompt: str,
    requested_provider: str | None,
    image_bytes: bytes | None = None,
) -> tuple[bytes | None, str, str | None]:
    provider = _provider_for_model(model, requested_provider)
    if provider not in {CHUTES, YUZU_PORTAL}:
        return (
            None,
            provider or "",
            f"Execution failed: Unsupported image provider/model configuration ({provider or 'missing provider'})",
        )

    key = _key_for(provider)
    if not key:
        label = "Yuzu Portal" if provider == YUZU_PORTAL else "Chutes"
        return (
            None,
            provider,
            f"Execution failed: Please set your {label} API key in the config first",
        )
    if not model:
        return None, provider, "Execution failed: Please configure an image model first"
    if provider == CHUTES and model not in CHUTES_MODELS:
        return (
            None,
            provider,
            f"Execution failed: Unsupported Chutes image model: {model}",
        )

    if provider == CHUTES:
        endpoint, _kind = CHUTES_MODELS[model]
        payload = _chutes_payload(model, prompt, image_bytes)
    else:
        endpoint = f"{_portal_base_url()}/images/generations"
        payload = _portal_payload(model, prompt)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=300,
            )
        if response.status_code != 200:
            return (
                None,
                provider,
                f"Execution failed: {provider} image API returned HTTP {response.status_code}",
            )
        if (
            response.headers.get("content-type", "")
            .split(";", 1)[0]
            .startswith("image/")
        ):
            return response.content, provider, None
        data = response.json()
        image = _decode_image_response(data)
        if image:
            return image, provider, None
        return None, provider, "Execution failed: Image API returned no decodable image"
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Image request failed for %s: %s", provider, type(exc).__name__)
        return None, provider, "Execution failed: Image request could not be completed"
