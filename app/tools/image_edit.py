import asyncio
import base64
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from app.db import Database
from app.providers.image_provider import request_image
from app.tools.schemas import ToolDefinition, ToolParam, error_result, ok_result

logger = logging.getLogger(__name__)

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
)


def _validate_image_path(image_path: str) -> Path | None:
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


async def execute(arguments, **kwargs) -> dict[str, Any]:
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

    profile = await Database.get_profile(kwargs.get("user_id")) or {}
    partner_name = profile.get("partner_name") or ""

    validated_path = _validate_image_path(image_path)
    if not validated_path:
        return error_result(
            f"Invalid or inaccessible image path: {image_path}",
            TOOL_DEFINITION,
            f"/image_edit {prompt}",
            partner_name,
        )

    image_base64, _mime = _load_image_base64(image_path)
    if not image_base64:
        return error_result(
            f"Failed to load image: {image_path}",
            TOOL_DEFINITION,
            f"/image_edit {prompt}",
            partner_name,
        )

    try:
        image_model = profile.get("image_model")
        image_bytes = await asyncio.to_thread(validated_path.read_bytes)
        output_bytes, provider, error = await request_image(
            image_model or "",
            prompt,
            image_bytes=image_bytes,
        )
        if error:
            return error_result(
                error,
                TOOL_DEFINITION,
                f"/edit {prompt}",
                partner_name,
            )
        if not output_bytes:
            return error_result(
                "Execution failed: Image API returned no image",
                TOOL_DEFINITION,
                f"/edit {prompt}",
                partner_name,
            )

        logger.debug(f"[IMAGE EDIT] Editing: {image_path}")
        logger.debug(f"[IMAGE EDIT] Prompt: {prompt}")

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
            safe_prompt = "edited"
        filename = f"{timestamp}_{safe_prompt}.jpg"

        filepath = (images_dir / filename).resolve()
        _ = filepath.relative_to(images_dir)

        _ = await asyncio.to_thread(filepath.write_bytes, output_bytes)

        logger.debug(f"[IMAGE EDIT] Saved: {filepath}")

        full_command = f"/image_edit {prompt}"
        return ok_result(
            {
                "image_path": f"/static/generated_images/{filename}",
                "original_path": image_path,
                "image_html": f'<img src="/static/generated_images/{filename}" alt="Edited Image">',
                "model": image_model,
            },
            TOOL_DEFINITION,
            full_command,
            partner_name,
        )

    except Exception as e:
        logger.debug(f"[IMAGE EDIT] Exception: {str(e)}")
        partner_name = profile.get("partner_name") or ""
        return error_result(
            "Image edit failed. Please try again later.",
            TOOL_DEFINITION,
            f"/image_edit {prompt}",
            partner_name,
        )
