from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)
PROBLEM_MEDIA_TYPE = "application/problem+json"
PROBLEM_BASE = "https://yuzu.local/problems"


def problem_detail(
    status: int,
    title: str,
    detail: str,
    request: Request,
    *,
    errors: list[dict[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"{PROBLEM_BASE}/{status}",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": str(request.url),
        "request_id": getattr(request.state, "request_id", None) or str(uuid4()),
    }
    if errors:
        body["errors"] = errors
    response_headers = dict(headers or {})
    response_headers["Content-Type"] = PROBLEM_MEDIA_TYPE
    return JSONResponse(
        status_code=status,
        content=body,
        headers=response_headers,
        media_type=PROBLEM_MEDIA_TYPE,
    )


def _title(status: int) -> str:
    return {
        400: "Bad request",
        401: "Authentication required",
        403: "Forbidden",
        404: "Not found",
        405: "Method not allowed",
        409: "Conflict",
        422: "Unprocessable entity",
        429: "Too many requests",
        500: "Internal server error",
        502: "Bad gateway",
        503: "Service unavailable",
        504: "Gateway timeout",
    }.get(status, "Request failed")


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    status = getattr(exc, "status_code", 500)
    detail = getattr(exc, "detail", "Request failed")
    if not isinstance(detail, str):
        detail = "Request failed"
    return problem_detail(
        status,
        _title(status),
        detail,
        request,
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors: list[dict[str, Any]] = []
    for error in exc.errors():
        item = dict(error)
        if isinstance(item.get("ctx"), dict):
            item["ctx"] = {key: str(value) for key, value in item["ctx"].items()}
        errors.append(item)
    return problem_detail(
        422,
        _title(422),
        "The request contains invalid or missing fields.",
        request,
        errors=errors,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled API exception", exc_info=exc)
    return problem_detail(500, _title(500), "An unexpected error occurred.", request)
