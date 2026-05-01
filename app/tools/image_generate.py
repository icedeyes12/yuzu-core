from __future__ import annotations
# FILE: app/tools/image_generate.py
# DESCRIPTION: Image generation tool using diffusion models


import logging
import os
import requests
from datetime import datetime
from app.tools.schemas import ToolDefinition, ToolParam, ok_result, error_result
from app.db_pg_models import get_profile, get_api_keys

logger = logging.getLogger(__name__)

HUNYUAN_ENDPOINT = "https://chutes-hunyuan-image-3.chutes.ai/generate"
Z_TURBO_ENDPOINT = "https://chutes-z-image-turbo.chutes.ai/generate"
QWEN_IMAGE_ENDPOINT = "https://image.chutes.ai/generate"


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


def execute(arguments, **kwargs):
    prompt = arguments.get("prompt", "")
    if not prompt:
        return error_result(
            "No prompt provided",
            TOOL_DEFINITION,
            "/imagine",
            "Yuzu",
        )

    profile = get_profile() or {}
    partner_name = profile.get("partner_name", "Yuzu")

    try:
        api_keys = get_api_keys()
        api_key = api_keys.get('chutes')
        if not api_key:
            return error_result(
                "No Chutes API key available",
                TOOL_DEFINITION,
                f"/imagine {prompt}",
                partner_name,
            )

        image_model = profile.get("image_model", "hunyuan")
        logger.debug(f"[IMAGE TOOL] Model: {image_model}")

        if image_model == "qwen_image":
            endpoint = QWEN_IMAGE_ENDPOINT
            payload = {
                "model": "Qwen-Image-2512",
                "prompt": prompt,
                "negative_prompt": "cartoon, anime, bad anatomy, blurry, distorted, low quality, watermark, text",
                "guidance_scale": 7.5,
                "width": 1024,
                "height": 1024,
                "num_inference_steps": 20,
            }
        elif image_model == "z_turbo":
            endpoint = Z_TURBO_ENDPOINT
            payload = {"prompt": prompt}
        else:
            endpoint = HUNYUAN_ENDPOINT
            payload = {"prompt": prompt}

        logger.debug(f"[IMAGE TOOL] Endpoint: {endpoint}")
        logger.debug(f"[IMAGE TOOL] Generating image (prompt length: {len(prompt)} chars)")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        response = requests.post(
            endpoint,
            headers=headers,
            json=payload,
            timeout=300
        )

        if response.status_code != 200:
            logger.debug(f"[IMAGE TOOL] API error {response.status_code}")
            return error_result(
                f"API error {response.status_code}",
                TOOL_DEFINITION,
                f"/imagine {prompt}",
                partner_name,
            )

        images_dir = os.path.abspath(os.path.join("static", "generated_images"))
        os.makedirs(images_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_prompt = "".join(
            c for c in prompt[:30] if c.isascii() and (c.isalnum() or c in (" ", "-", "_"))
        ).strip()
        if not safe_prompt:
            safe_prompt = "image"
        ext = "jpg" if image_model == "qwen_image" else "png"
        filename = f"{timestamp}_{safe_prompt}.{ext}"

        candidate_path = os.path.join(images_dir, filename)
        filepath = os.path.abspath(os.path.normpath(candidate_path))
        if not filepath.startswith(images_dir + os.sep):
            raise ValueError("Unsafe output path")

        with open(filepath, 'wb') as f:
            f.write(response.content)

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
        profile = get_profile() or {}
        partner_name = profile.get("partner_name", "Yuzu")
        return error_result(
            "Image generation failed. Please try again later.",
            TOOL_DEFINITION,
            f"/imagine {prompt}",
            partner_name,
        )
