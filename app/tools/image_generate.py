from __future__ import annotations
# FILE: app/tools/image_generate.py
# DESCRIPTION: Image generation tool using diffusion models


import logging
import os
import httpx
import asyncio
from pathlib import Path
from datetime import datetime
from app.tools.schemas import ToolDefinition, ToolParam, ok_result, error_result
from app.db import Database

logger = logging.getLogger(__name__)

Z_TURBO_ENDPOINT = "https://vonkaiser-z-image-turbo.chutes.ai/generate"
QWEN_IMAGE_ENDPOINT = "https://vonkaiser-qwen-image-2512.chutes.ai/generate"


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
    is_terminal=True,
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

    profile = await Database.get_profile_async() or {}
    partner_name = profile.get("partner_name", "Yuzu")

    try:
        api_keys = await Database.get_api_keys_async()
        api_key = api_keys.get("chutes")
        if not api_key:
            return error_result(
                "No Chutes API key available",
                TOOL_DEFINITION,
                f"/imagine {prompt}",
                partner_name,
            )

        image_model = profile.get("image_model", "qwen_image")
        logger.debug(f"[IMAGE TOOL] Model: {image_model}")

        if image_model == "z_turbo":
            endpoint = Z_TURBO_ENDPOINT
            payload = {"prompt": prompt}
        else:
            # Default: qwen_image
            endpoint = QWEN_IMAGE_ENDPOINT
            payload = {"prompt": prompt}

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

        images_dir = Path("static/generated_images").resolve()
        images_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_prompt = "".join(
            c
            for c in prompt[:30]
            if c.isascii() and (c.isalnum() or c in (" ", "-", "_"))
        ).strip()
        if not safe_prompt:
            safe_prompt = "image"
        ext = "jpg" if image_model == "qwen_image" else "png"
        filename = f"{timestamp}_{safe_prompt}.{ext}"

        filepath = (images_dir / filename).resolve()
        if not str(filepath).startswith(str(images_dir) + os.sep):
            raise ValueError("Unsafe output path")

        # Use asyncio.to_thread for file I/O
        await asyncio.to_thread(filepath.write_bytes, response.content)

        logger.debug(f"[IMAGE TOOL] Saved: {filepath}")

        full_command = f"/imagine {prompt}"
        return ok_result(
            {
                "image_path": f"static/generated_images/{filename}",
                "image_html": f'<img src="static/generated_images/{filename}" alt="Generated Image">',
                "model": image_model,
            },
            TOOL_DEFINITION,
            full_command,
            partner_name,
        )

    except Exception as e:
        logger.debug(f"[IMAGE TOOL] Exception: {str(e)}")
        profile = await Database.get_profile_async() or {}
        partner_name = profile.get("partner_name", "Yuzu")
        return error_result(
            "Image generation failed. Please try again later.",
            TOOL_DEFINITION,
            f"/imagine {prompt}",
            partner_name,
        )
