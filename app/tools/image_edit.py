from __future__ import annotations
# FILE: app/tools/image_edit.py
# DESCRIPTION: Edit existing images using Qwen Image Edit API


import logging
import os
import httpx
import asyncio
import base64
from pathlib import Path
from datetime import datetime
from app.tools.schemas import ToolDefinition, ToolParam, ok_result, error_result
from app.db import Database

logger = logging.getLogger(__name__)

QWEN_IMAGE_EDIT_ENDPOINT = "https://vonkaiser-qwen-image-edit-2511.chutes.ai/generate"


TOOL_DEFINITION = ToolDefinition(
    name="image_edit",
    description="Edit an existing image. Provide the image path and a prompt describing the changes. "
    "Use this when user wants to modify a previously generated or uploaded image.",
    role="image_tools",
    parameters=[
        ToolParam(
            name="prompt",
            description="What to change in the image (e.g., 'change background to beach', 'make her smile')",
            type="string",
            required=True,
        ),
        ToolParam(
            name="image_path",
            description="Path to the image to edit (e.g., 'static/generated_images/xxx.jpg' or 'static/uploads/xxx.jpg')",
            type="string",
            required=True,
        ),
    ],
    is_terminal=True,
)


def _validate_image_path(image_path: str) -> Path | None:
    """Validate image path is within allowed directories."""
    if not image_path or not isinstance(image_path, str):
        return None

    filename = os.path.basename(image_path.replace("\\", "/"))
    if not filename or filename.startswith(".") or ".." in filename:
        return None

    ext = Path(filename).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return None

    _BASE_DIR = Path(__file__).resolve().parent.parent.parent
    _ALLOWED_DIRS = [
        (_BASE_DIR / "static" / "uploads").resolve(),
        (_BASE_DIR / "static" / "generated_images").resolve(),
        (_BASE_DIR / "static").resolve(),
    ]

    for trusted_dir in _ALLOWED_DIRS:
        candidate = trusted_dir / filename
        try:
            resolved = candidate.resolve()
            if resolved.is_file():
                try:
                    rel = os.path.relpath(str(resolved), str(trusted_dir))
                    if rel.startswith(".."):
                        continue
                except ValueError:
                    continue
                if resolved.is_symlink():
                    continue
                return resolved
        except (OSError, ValueError):
            continue

    return None


def _load_image_base64(image_path: str) -> tuple[str | None, str | None]:
    """Load image and return (base64, mime) or (None, None)."""
    validated_path = _validate_image_path(image_path)
    if not validated_path:
        return None, None

    try:
        data = base64.b64encode(validated_path.read_bytes()).decode("utf-8")
    except OSError as e:
        logger.warning(f"image read failed: {e}")
        return None, None

    suffix = validated_path.suffix.lower()
    if suffix == ".png":
        mime = "image/png"
    elif suffix == ".gif":
        mime = "image/gif"
    elif suffix == ".webp":
        mime = "image/webp"
    else:
        mime = "image/jpeg"

    return data, mime


async def execute(arguments, **kwargs) -> dict:
    prompt = arguments.get("prompt", "")
    image_path = arguments.get("image_path", "")

    if not prompt:
        return error_result(
            "No prompt provided",
            TOOL_DEFINITION,
            "/image_edit",
            "Yuzu",
        )

    if not image_path:
        return error_result(
            "No image_path provided. Specify the image to edit.",
            TOOL_DEFINITION,
            f"/image_edit {prompt}",
            "Yuzu",
        )

    profile = await Database.get_profile_async() or {}
    partner_name = profile.get("partner_name", "Yuzu")

    validated_path = _validate_image_path(image_path)
    if not validated_path:
        return error_result(
            f"Invalid or inaccessible image path: {image_path}",
            TOOL_DEFINITION,
            f"/image_edit {prompt}",
            partner_name,
        )

    image_base64, mime = _load_image_base64(image_path)
    if not image_base64:
        return error_result(
            f"Failed to load image: {image_path}",
            TOOL_DEFINITION,
            f"/image_edit {prompt}",
            partner_name,
        )

    try:
        api_keys = await Database.get_api_keys_async()
        api_key = api_keys.get("chutes")
        if not api_key:
            return error_result(
                "No Chutes API key available",
                TOOL_DEFINITION,
                f"/image_edit {prompt}",
                partner_name,
            )

        logger.debug(f"[IMAGE EDIT] Editing: {image_path}")
        logger.debug(f"[IMAGE EDIT] Prompt: {prompt}")

        # Qwen Image Edit expects: {"input_args": {"prompt": "...", "image_b64s": ["..."]}}
        payload = {
            "input_args": {
                "prompt": prompt,
                "image_b64s": [image_base64],
            }
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                QWEN_IMAGE_EDIT_ENDPOINT,
                headers=headers,
                json=payload,
                timeout=300,
            )

        if response.status_code != 200:
            logger.debug(f"[IMAGE EDIT] API error {response.status_code}: {response.text[:500]}")
            return error_result(
                f"API error {response.status_code}",
                TOOL_DEFINITION,
                f"/image_edit {prompt}",
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
            safe_prompt = "edited"
        filename = f"{timestamp}_{safe_prompt}.jpg"

        filepath = (images_dir / filename).resolve()
        if not str(filepath).startswith(str(images_dir) + os.sep):
            raise ValueError("Unsafe output path")

        await asyncio.to_thread(filepath.write_bytes, response.content)

        logger.debug(f"[IMAGE EDIT] Saved: {filepath}")

        full_command = f"/image_edit {prompt}"
        return ok_result(
            {
                "image_path": f"static/generated_images/{filename}",
                "image_html": f'<img src="static/generated_images/{filename}" alt="Edited Image">',
                "original_path": image_path,
            },
            TOOL_DEFINITION,
            full_command,
            partner_name,
        )

    except Exception as e:
        logger.debug(f"[IMAGE EDIT] Exception: {str(e)}")
        profile = await Database.get_profile_async() or {}
        partner_name = profile.get("partner_name", "Yuzu")
        return error_result(
            "Image edit failed. Please try again later.",
            TOOL_DEFINITION,
            f"/image_edit {prompt}",
            partner_name,
        )
