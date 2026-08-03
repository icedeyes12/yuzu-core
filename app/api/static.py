from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.models import ERROR_RESPONSES
from app.api.utils import get_current_user

router = APIRouter(prefix="/static", tags=["static"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _safe_file_path(base_dir: Path, filename: str) -> Path:
    # Only allow direct filenames, not nested paths or traversal tokens
    candidate_name = Path(filename)
    if (
        candidate_name.name != filename
        or candidate_name.is_absolute()
        or ".." in candidate_name.parts
        or "/" in filename
        or "\\" in filename
    ):
        raise HTTPException(status_code=404, detail="Image not found")

    file_path = (base_dir / candidate_name).resolve()
    try:
        file_path.relative_to(base_dir)
    except ValueError:
        raise HTTPException(status_code=404, detail="Image not found")

    return file_path


@router.get("/uploads/{filename}", response_model=None, responses=ERROR_RESPONSES)
async def serve_uploaded_image(
    filename: str, _user_id: str = Depends(get_current_user)
):
    try:
        uploads_dir = (BASE_DIR / "static" / "uploads").resolve()
        file_path = _safe_file_path(uploads_dir, filename)

        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        raise HTTPException(status_code=404, detail="Image not found")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")


@router.get(
    "/generated_images/{filename}", response_model=None, responses=ERROR_RESPONSES
)
async def serve_generated_image(
    filename: str, _user_id: str = Depends(get_current_user)
):
    try:
        generated_dir = (BASE_DIR / "static" / "generated_images").resolve()
        file_path = _safe_file_path(generated_dir, filename)

        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        raise HTTPException(status_code=404, detail="Image not found")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")
