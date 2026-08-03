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
        allowed_files = {p.name: p for p in uploads_dir.iterdir() if p.is_file()}
        file_path = allowed_files.get(filename)

        if file_path is not None:
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
        allowed_files = {p.name: p for p in generated_dir.iterdir() if p.is_file()}
        file_path = allowed_files.get(filename)

        if file_path is not None:
            return FileResponse(file_path)
        raise HTTPException(status_code=404, detail="Image not found")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")
