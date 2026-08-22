from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.models import ERROR_RESPONSES
from app.api.utils import get_current_user
from app.core.ids import EntityType, PublicId
from app.services.file_service import FileNotFound, FileService
from app.services.files import get_file_service

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{file_id}", response_model=None, responses=ERROR_RESPONSES)
async def download_file(
    file_id: str,
    user_id: str = Depends(get_current_user),
    service: FileService = Depends(get_file_service),
):
    try:
        internal_id = PublicId.decode(EntityType.FILE, file_id, allow_raw_uuid=False)
        row, path = await service.open_for_owner(internal_id, user_id)
    except (ValueError, FileNotFound):
        raise HTTPException(status_code=404, detail="File not found") from None

    return FileResponse(
        path,
        media_type=row["mime_type"],
        filename=row.get("original_name") or file_id,
    )
