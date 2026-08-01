from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.utils import get_current_user
from app.core.logging_config import get_logger
from app.core.presets import (
    active_preset,
    list_presets,
    sync_top_level_with_active,
)
from app.core.presets import (
    delete_preset as delete_preset_helper,
)
from app.core.presets import (
    set_active_preset as set_active_preset_helper,
)
from app.core.presets import (
    upsert_preset as upsert_preset_helper,
)
from app.db import get_profile_async, update_profile_async

log = get_logger(__name__)

router = APIRouter(tags=["presets"])


class PresetUpsertRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    payload: dict[str, object] = Field(default_factory=dict)
    make_active: bool = False


class PresetActivateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


class PresetDeleteRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


async def _load_model_parameters(user_id: str) -> dict[str, object]:
    profile = await get_profile_async(user_id)
    return profile.get("model_parameters") or {}


async def _save_model_parameters(
    model_parameters: dict[str, object], user_id: str
) -> None:
    _ = await update_profile_async({"model_parameters": model_parameters}, user_id)


@router.get("/presets/list")
async def api_list_presets(user_id: str = Depends(get_current_user)):
    model_parameters = await _load_model_parameters(user_id)
    return {
        "presets": list_presets(model_parameters),
        "active": active_preset(model_parameters),
    }


@router.post("/presets/upsert")
async def api_upsert_preset(
    request: PresetUpsertRequest, user_id: str = Depends(get_current_user)
):
    try:
        model_parameters = await _load_model_parameters(user_id)
        presets, target = upsert_preset_helper(
            model_parameters,
            request.name,
            request.payload,
            make_active=request.make_active,
        )
        if request.make_active:
            model_parameters = sync_top_level_with_active(model_parameters)
            model_parameters["presets"] = presets
        else:
            model_parameters["presets"] = presets
        await _save_model_parameters(model_parameters, user_id)
        return {"status": "success", "preset": target, "presets": presets}
    except Exception as exc:
        log.error("upsert_preset failed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/presets/activate")
async def api_activate_preset(
    request: PresetActivateRequest, user_id: str = Depends(get_current_user)
):
    try:
        model_parameters = await _load_model_parameters(user_id)
        presets, target = set_active_preset_helper(model_parameters, request.name)
        if target is None:
            raise HTTPException(status_code=404, detail="Preset not found")
        model_parameters = sync_top_level_with_active(model_parameters)
        model_parameters["presets"] = presets
        await _save_model_parameters(model_parameters, user_id)
        return {"status": "success", "active": target, "presets": presets}
    except HTTPException:
        raise
    except Exception as exc:
        log.error("activate_preset failed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/presets/delete")
async def api_delete_preset(
    request: PresetDeleteRequest, user_id: str = Depends(get_current_user)
):
    try:
        model_parameters = await _load_model_parameters(user_id)
        presets, removed = delete_preset_helper(model_parameters, request.name)
        if not removed:
            raise HTTPException(status_code=404, detail="Preset not found")
        model_parameters = sync_top_level_with_active(model_parameters)
        model_parameters["presets"] = presets
        await _save_model_parameters(model_parameters, user_id)
        return {"status": "success", "presets": presets}
    except HTTPException:
        raise
    except Exception as exc:
        log.error("delete_preset failed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")
