from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path

import httpx

from app.core.context import get_request_keyring
from app.db import Database
from app.tools.schemas import ToolDefinition, ToolParam, error_result, ok_result

logger = logging.getLogger(__name__)


TOOL_DEFINITION = ToolDefinition(
    name="image_generate",
    description="Generate an image from a text prompt using AI diffusion models. "
    "Returns the generated image displayed inline.",
    role="image_tools",
    parameters=[
        ToolParam(
            name="prompt",
            description="Detailed description of the image to generate",
            type="string",
            required=True,
        ),
    ],
)


async def execute(arguments, **kwargs):
    prompt = arguments.get("prompt", "")
    if not prompt:
        return error_result(
            "No prompt provided",
            TOOL_DEFINITION,
            "/imagine",
            "Yuzu",
        )

    profile = await Database.get_profile(kwargs.get("user_id")) or {}
    partner_name = profile.get("partner_name") or ""

    try:
        image_provider = profile.get("image_provider")
        image_model = profile.get("image_model")
        endpoint = profile.get("image_endpoint")
        keyring = get_request_keyring(image_provider) if image_provider else None
        api_key = keyring.key if keyring else None
        if not api_key or not image_provider or not image_model or not endpoint:
            return error_result(
                "NOT CONFIGURED",
                TOOL_DEFINITION,
                f"/imagine {prompt}",
                partner_name,
            )

        logger.debug(f"[IMAGE TOOL] Model: {image_model}")
        payload = {
            "prompt": prompt,
            "model": image_model,
            **(profile.get("image_extra_body") or {}),
        }

        logger.debug(f"[IMAGE TOOL] Endpoint: {endpoint}")
        logger.debug(
            f"[IMAGE TOOL] Generating image (prompt length: {len(prompt)} chars)"
        )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                endpoint, headers=headers, json=payload, timeout=300
            )

        if response.status_code != 200:
            logger.debug(f"[IMAGE TOOL] API error {response.status_code}")
            return error_result(
                f"API error {response.status_code}",
                TOOL_DEFINITION,
                f"/imagine {prompt}",
                partner_name,
            )

        images_dir = (
            Path(__file__).resolve().parent.parent.parent
            / "static"
            / "generated_images"
        ).resolve()
        images_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_prompt = (
            "".join(
                c
                for c in prompt[:30]
                if c.isascii() and (c.isalnum() or c in (" ", "-", "_"))
            )
            .strip()
            .replace(" ", "_")
        )
        if not safe_prompt:
            safe_prompt = "image"
        ext = "png"
        filename = f"{timestamp}_{safe_prompt}.{ext}"

        filepath = (images_dir / filename).resolve()
        filepath.relative_to(images_dir)

        await asyncio.to_thread(filepath.write_bytes, response.content)

        logger.debug(f"[IMAGE TOOL] Saved: {filepath}")

        return ok_result(
            {
                "image_path": f"/static/generated_images/{filename}",
                "model": image_model,
            },
            TOOL_DEFINITION["image_generate"]
            if isinstance(TOOL_DEFINITION, dict)
            else TOOL_DEFINITION,
            partner_name=partner_name,
        )

    except Exception as e:
        logger.debug(f"[IMAGE TOOL] Exception: {str(e)}")
        profile = await Database.get_profile(kwargs.get("user_id")) or {}
        partner_name = profile.get("partner_name") or ""
        return error_result(
            "Image generation failed. Please try again later.",
            TOOL_DEFINITION,
            f"/imagine {prompt}",
            partner_name,
        )
