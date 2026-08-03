from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.models import ERROR_RESPONSES, BasicHealthResponse, HealthResponse
from app.db.connection import get_async_pool

router = APIRouter(tags=["health"])


@router.api_route(
    "/health",
    methods=["GET"],
    response_model=BasicHealthResponse,
    responses={200: {"description": "Service is alive"}, **ERROR_RESPONSES},
)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/health/ready",
    response_model=HealthResponse,
    responses={
        503: {"model": HealthResponse, "description": "Database is unavailable"}
    },
)
async def readiness() -> HealthResponse | JSONResponse:
    try:
        pool = await get_async_pool()
        async with pool.connection() as conn:
            await conn.execute("SELECT 1")
        return HealthResponse(status="ok", database="ok")
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "database": "unavailable"},
        )
