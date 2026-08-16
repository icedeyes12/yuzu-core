from __future__ import annotations

import json

import pytest
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api.errors import validation_exception_handler
from app.api.models import ProblemDetail, SuccessResponse
from app.api.utils import _stream_counts, release_stream_slot, try_acquire_stream_slot
from main import app


def _request(path: str = "/api/v1/test") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )


def test_success_response_model_is_reusable() -> None:
    payload = SuccessResponse[dict](data={"value": 1})
    assert payload.model_dump() == {"status": "success", "data": {"value": 1}}


def test_problem_details_model_has_rfc9457_core_fields() -> None:
    payload = ProblemDetail(
        type="https://yuzu.local/problems/422",
        title="Unprocessable entity",
        status=422,
        detail="Invalid field",
        instance="http://testserver/api/v1/test",
        request_id="req-1",
        errors=[{"loc": ["body", "message"], "msg": "required"}],
    )
    assert payload.status == 422
    assert payload.type.endswith("/422")
    assert payload.request_id == "req-1"


@pytest.mark.asyncio
async def test_validation_errors_use_problem_details() -> None:
    request = _request()
    request.state.request_id = "req-validation"
    exc = RequestValidationError(
        [
            {
                "type": "missing",
                "loc": ("body", "message"),
                "msg": "required",
                "input": {},
            }
        ]
    )
    response = await validation_exception_handler(request, exc)
    assert response.status_code == 422
    assert response.media_type == "application/problem+json"
    body = json.loads(response.body)
    assert body["type"].endswith("/422")
    assert body["request_id"] == "req-validation"
    assert body["errors"][0]["loc"] == ["body", "message"]


def test_security_headers_and_metrics_are_exposed(monkeypatch) -> None:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def no_startup(_app):
        yield

    monkeypatch.setattr(app.router, "lifespan_context", no_startup)
    monkeypatch.setattr("main.metrics.enabled", True)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/health")
        metrics = client.get("/metrics")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-request-id"]
    assert metrics.status_code == 200
    assert "yuzu_http_requests_total" in metrics.text
    assert "yuzu_http_request_duration_seconds" in metrics.text


def test_versioned_api_and_openapi_are_available_without_legacy_prefix(
    monkeypatch,
) -> None:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def no_startup(_app):
        yield

    monkeypatch.setattr(app.router, "lifespan_context", no_startup)
    with TestClient(app, raise_server_exceptions=False) as client:
        openapi = client.get("/openapi.json")
        legacy = client.get("/api/openapi.json")

    assert openapi.status_code == 200
    schema = openapi.json()
    assert "/api/v1/health" not in schema["paths"]
    assert "/v1/profile" in schema["paths"]
    assert legacy.status_code == 404


def test_stream_slots_are_bounded_and_released() -> None:
    user = "test-stream-user"
    _stream_counts.pop(user, None)
    assert try_acquire_stream_slot(user)
    assert try_acquire_stream_slot(user)
    assert not try_acquire_stream_slot(user)
    release_stream_slot(user)
    assert try_acquire_stream_slot(user)
    release_stream_slot(user)
    release_stream_slot(user)
    _stream_counts.pop(user, None)
