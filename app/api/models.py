from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ProblemDetail(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str | None = None
    request_id: str | None = None
    errors: list[dict[str, Any]] | None = None


class SuccessResponse[T](ApiModel):
    status: str = "success"
    data: T | None = None


class ListResponse[T](ApiModel):
    items: list[T] = []
    total: int | None = None


class PaginationMeta(ApiModel):
    has_more: bool
    limit: int
    next_cursor: str | None = None


class PaginatedResponse[T](ApiModel):
    items: list[T]
    pagination: PaginationMeta


class StatusResponse(ApiModel):
    status: str
    message: str | None = None


class MessageResponse(ApiModel):
    reply: str
    status: str = "success"


class OperationResponse(ApiModel):
    status: str
    message: str | None = None


class ConfigResponse(ApiModel):
    status: str | None = None


class ProfileResponse(ApiModel):
    status: str | None = None


class ProviderListResponse(ApiModel):
    status: str | None = None
    available_providers: list[Any] = []
    all_models: dict[str, Any] | list[Any] = {}
    current_provider: str | None = None
    current_model: str | None = None


class ModelsResponse(ApiModel):
    status: str
    models: list[str] = []
    message: str | None = None


class ProviderTestResponse(ApiModel):
    status: str
    provider: str | None = None
    connected: bool | None = None
    message: str | None = None


class SessionHistoryResponse(ApiModel):
    status: str | None = None
    active_session_id: str | None = None
    chat_history: list[Any] = []
    has_more: bool | None = None


class SessionListResponse(ApiModel):
    status: str | None = None
    sessions: list[Any] = []


class SessionMutationResponse(ApiModel):
    status: str
    session_id: str | None = None
    active_session_id: str | None = None
    active_session: dict[str, Any] | None = None
    chat_history: list[Any] = []
    has_more: bool | None = None
    message: str | None = None


class PresetResponse(ApiModel):
    status: str
    presets: list[Any] = []
    active: Any = None
    preset: Any = None


class KnowledgeListResponse(ApiModel):
    status: str | None = None
    entries: list[Any] = []


class KnowledgeEntryResponse(ApiModel):
    entry: dict[str, Any]


class MemoryResponse(ApiModel):
    status: str
    message: str | None = None
    stats: dict[str, Any] = {}


class StreamStatusResponse(ApiModel):
    active: bool | None = None
    completed: bool | None = None
    length: int = 0
    error: str | None = None
    has_error: bool | None = None
    turn_id: str | None = None


class StreamSyncResponse(ApiModel):
    valid: bool
    error: str | None = None
    length: int = 0
    checksum: str = ""
    completed: bool | None = None
    turn_id: str | None = None


class BasicHealthResponse(BaseModel):
    status: str


class StreamMetadata(ApiModel):
    type: str = "stream"
    media_type: str = "text/event-stream"
    heartbeat_interval_seconds: int = 15
    idle_timeout_seconds: int = 120


class HealthResponse(BaseModel):
    status: str
    database: str


class AuthMeResponse(ApiModel):
    user_id: str
    email: str | None = None
    user_name: str = ""
    avatar_url: str | None = None


ERROR_RESPONSES = {
    status: {"model": ProblemDetail, "description": "RFC 9457 Problem Details"}
    for status in (400, 401, 403, 404, 405, 409, 422, 429, 500, 502, 503, 504)
}
