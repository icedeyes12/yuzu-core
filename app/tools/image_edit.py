import base64
import logging
from typing import Any

from app.core.ids import EntityType, PublicId
from app.db import Database
from app.providers.image_provider import request_image
from app.services.files import get_file_service, resolve_private_file
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
            description="Private file URL returned by upload or image generation",
            type="string",
            required=True,
        ),
    ],
)


def _load_image_base64(validated_path) -> tuple[str | None, str | None]:
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

    user_id = kwargs.get("user_id")
    validated_path = (
        await resolve_private_file(image_path, user_id) if user_id else None
    )
    if not validated_path:
        return error_result(
            f"Invalid or inaccessible image path: {image_path}",
            TOOL_DEFINITION,
            f"/image_edit {prompt}",
            partner_name,
        )

    image_base64, _mime = _load_image_base64(validated_path)
    if not image_base64:
        return error_result(
            f"Failed to load image: {image_path}",
            TOOL_DEFINITION,
            f"/image_edit {prompt}",
            partner_name,
        )

    try:
        image_model = profile.get("image_model")
        image_bytes = validated_path.read_bytes()
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

        row = await get_file_service().persist_bytes(
            owner_id=user_id,
            data=output_bytes,
            kind="generated_image",
            mime_type="image/jpeg",
            original_name="edited.jpg",
            source="image_edit",
        )
        file_id = PublicId.encode(EntityType.FILE, row["id"])
        output_path = f"/api/v1/files/{file_id}"

        full_command = f"/image_edit {prompt}"
        return ok_result(
            {
                "file_id": file_id,
                "image_path": output_path,
                "prompt": prompt,
                "original_path": image_path,
                "mime_type": row["mime_type"],
                "size": row["size_bytes"],
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
