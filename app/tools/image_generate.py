import logging

import httpx

from app.core.ids import EntityType, PublicId
from app.db import Database
from app.providers.image_provider import request_image
from app.services.files import get_file_service
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

    user_id = kwargs.get("user_id")
    if not user_id:
        return error_result(
            "Missing user context", TOOL_DEFINITION, "/imagine", partner_name
        )
    row = await get_file_service().persist_bytes(
        owner_id=user_id,
        data=image_bytes,
        kind="generated_image",
        mime_type="image/png",
        original_name="generated.png",
        source="image_generate",
    )
    file_id = PublicId.encode(EntityType.FILE, row["id"])
    image_path = f"/api/v1/files/{file_id}"

    return ok_result(
        {
            "file_id": file_id,
            "image_path": image_path,
            "mime_type": row["mime_type"],
            "size": row["size_bytes"],
            "prompt": prompt,
            "model": model,
            "provider": provider,
        },
        TOOL_DEFINITION,
        partner_name=partner_name,
    )
