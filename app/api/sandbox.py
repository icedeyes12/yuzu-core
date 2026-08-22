"""
My Computer API Router (Endpoints for Sandbox Tenancy & Control).
Strictly tenant-scoped under /api/v1/sandbox.
ฅ^•ﻌ•^ฅ
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.utils import get_current_user
from app.db.sandbox_instance_repository import PgSandboxInstanceRepository
from app.services.sandbox_lifecycle import SandboxLifecycleEngine
from yuzu_sandbox.proot_wrapper import RestrictedPRootBuilder

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


def get_lifecycle_engine() -> SandboxLifecycleEngine:
    repo = PgSandboxInstanceRepository()
    builder = RestrictedPRootBuilder()
    return SandboxLifecycleEngine(repo, builder)


class ProvisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distribution: str = Field(default="debian", pattern="^(debian|ubuntu)$")


class ActionConfirmation(BaseModel):
    confirmation: str = Field(
        ..., description="Confirmation keyword e.g. DELETE or RESET"
    )


@router.get("/status")
async def get_sandbox_status(
    user_id: str = Depends(get_current_user),
    engine: SandboxLifecycleEngine = Depends(get_lifecycle_engine),
) -> dict[str, Any]:
    """Get status of the caller's My Computer persistent sandbox."""
    return await engine.get_status(user_id)


@router.post("/provision")
async def provision_sandbox(
    payload: ProvisionRequest,
    user_id: str = Depends(get_current_user),
    engine: SandboxLifecycleEngine = Depends(get_lifecycle_engine),
) -> dict[str, Any]:
    """Provision a new My Computer instance for the authenticated user."""
    try:
        return await engine.provision_sandbox(
            owner_id=user_id,
            distribution=payload.distribution,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/reset")
async def reset_sandbox(
    payload: ActionConfirmation,
    user_id: str = Depends(get_current_user),
    engine: SandboxLifecycleEngine = Depends(get_lifecycle_engine),
) -> dict[str, Any]:
    """Reset and re-provision user sandbox with a fresh generation ID."""
    try:
        return await engine.reset_sandbox(user_id, confirmation=payload.confirmation)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("")
async def delete_sandbox(
    confirmation: str,
    user_id: str = Depends(get_current_user),
    engine: SandboxLifecycleEngine = Depends(get_lifecycle_engine),
) -> dict[str, Any]:
    """Permanently delete user sandbox rootfs."""
    try:
        success = await engine.delete_sandbox(user_id, confirmation=confirmation)
        if not success:
            raise HTTPException(status_code=404, detail="No sandbox found to delete")
        return {"status": "success", "message": "Sandbox deleted"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
