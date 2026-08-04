import asyncio
import logging
from datetime import datetime
from pathlib import Path

import httpx

from app.db import Database
from app.providers.image_provider import request_image
from app.tools.schemas import ToolDefinition, ToolParam, error_result, ok_result

logger = logging.getLogger(__name__)

TOOL_DEFINITION = ToolDefinition(
    name="image_generate",
    description="Generate an image from a text prompt using the configured image provider.",
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
    prompt = str(arguments.get("prompt", "")).strip()
    if not prompt:
        return error_result("No prompt provided", TOOL_DEFINITION, "/imagine", "Yuzu")

    profile = await Database.get_profile(kwargs.get("user_id")) or {}
    partner_name = profile.get("partner_name") or ""
    model = profile.get("image_model") or ""

    try:
        image_model = profile.get("image_model")
        image_bytes, provider, error = await request_image(
            image_model or "",
            prompt,
        )
        if error:
            return error_result(
                error,
                TOOL_DEFINITION,
                f"/imagine {prompt}",
                partner_name,
            )
        if not image_bytes:
            return error_result(
                "Execution failed: Image API returned no image",
                TOOL_DEFINITION,
                f"/imagine {prompt}",
                partner_name,
            )
    except httpx.HTTPError as e:
        return error_result(str(e), TOOL_DEFINITION, f"/imagine {prompt}", partner_name)

    images_dir = (
        Path(__file__).resolve().parent.parent.parent / "static" / "generated_images"
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
        or "image"
    )
    filename = f"{timestamp}_{safe_prompt}.png"
    filepath = images_dir / filename
    await asyncio.to_thread(filepath.write_bytes, image_bytes)
    logger.debug("[IMAGE TOOL] Saved: %s", filepath)

    return ok_result(
        {
            "image_path": f"/api/v1/static/generated_images/{filename}",
            "prompt": prompt,
            "model": model,
            "provider": provider,
        },
        TOOL_DEFINITION,
        partner_name=partner_name,
    )
