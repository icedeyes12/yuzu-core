from __future__ import annotations

import ipaddress
import logging
import re
import socket
from urllib.parse import urlparse

import httpx

from app.core.ids import EntityType, PublicId
from app.services.files import get_file_service
from app.tools.schemas import ToolDefinition, ToolParam, error_result, ok_result

logger = logging.getLogger(__name__)

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 90


def _network_error_category(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        return "upstream_http_error"
    if isinstance(exc, httpx.RequestError):
        return "network_error"
    return "tool_execution_error"


TOOL_DEFINITION = ToolDefinition(
    name="http_request",
    description="Make HTTP requests to public HTTPS endpoints. "
    "Use for web searches, fetching data from public APIs, or retrieving content. "
    "Only accepts public HTTPS URLs. Returns text content or downloaded images.",
    role="request_tools",
    parameters=[
        ToolParam(
            name="url",
            description="The full HTTPS URL to request",
            type="string",
            required=True,
        ),
        ToolParam(
            name="method",
            description="HTTP method to use",
            type="string",
            required=False,
            default="GET",
            enum=["GET", "POST", "PUT", "DELETE"],
        ),
    ],
)


def is_safe_public_url(url: str) -> tuple[bool, str]:
    parsed = urlparse(url)

    if parsed.scheme != "https":
        return False, "URL must use HTTPS scheme"

    if not parsed.hostname:
        return False, "Invalid URL - missing hostname"

    try:
        ip = socket.gethostbyname(parsed.hostname)
        ip_obj = ipaddress.ip_address(ip)

        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_reserved
        ):
            return False, f"IP address is private/unsafe: {ip}"
    except Exception:
        return (
            False,
            f"DNS resolution failed - domain '{parsed.hostname}' may not exist or is down",
        )

    return True, ""


def _extract_url(args_str: str) -> tuple[str, str]:
    args_str = args_str.strip()

    method_match = re.match(
        r"^(GET|POST|PUT|DELETE|PATCH)\s+(.+)$", args_str, re.IGNORECASE
    )
    if method_match:
        method = method_match.group(1).upper()
        url = method_match.group(2).strip()
        return method, url

    return "GET", args_str


async def execute(
    arguments: dict[str, str] | str, **kwargs: object
) -> dict[str, object]:
    from app.db import Database

    profile = await Database.get_profile(kwargs.get("user_id")) or {}
    partner_name = profile.get("partner_name", "Yuzu")

    if isinstance(arguments, dict):
        args_str = arguments.get("url", "").strip()
    else:
        args_str = str(arguments).strip()

    method, url = _extract_url(args_str)

    if isinstance(arguments, dict) and arguments.get("method"):
        method = arguments["method"].upper()

    full_command = f"/request {method} {url}" if method != "GET" else f"/request {url}"

    if not url:
        return error_result(
            "No URL provided",
            TOOL_DEFINITION,
            "/request",
            partner_name,
        )

    is_safe, reason = is_safe_public_url(url)
    if not is_safe:
        return error_result(
            f"Request failed: {reason}",
            TOOL_DEFINITION,
            f"/request {args_str}",
            partner_name,
            category="validation_error",
        )

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.request(
                method, url, timeout=TIMEOUT, follow_redirects=True
            )

            if resp.is_error:
                return error_result(
                    f"Upstream returned HTTP {resp.status_code}",
                    TOOL_DEFINITION,
                    full_command,
                    partner_name,
                    category="upstream_http_error",
                    data={
                        "schema_kind": "http",
                        "url": url,
                        "method": method,
                        "status_code": resp.status_code,
                    },
                )

            content = b""
            async for chunk in resp.aiter_bytes(8192):
                content += chunk
                if len(content) > MAX_BYTES:
                    return error_result(
                        "Response too large (max 2MB)",
                        TOOL_DEFINITION,
                        full_command,
                        partner_name,
                    )

            content_type = resp.headers.get("Content-Type", "")
            size = len(content)

            if content_type.startswith("image/"):
                user_id = kwargs.get("user_id")
                if not isinstance(user_id, str):
                    return error_result(
                        "Authenticated user is required to persist media",
                        TOOL_DEFINITION,
                        full_command,
                        partner_name,
                        category="authorization_error",
                    )
                mime_type = content_type.split(";", 1)[0].strip()
                row = await get_file_service().persist_bytes(
                    owner_id=user_id,
                    data=content,
                    kind="attachment",
                    mime_type=mime_type,
                    source="http_request",
                )
                file_id = PublicId.encode(EntityType.FILE, row["id"])
                return ok_result(
                    {
                        "schema_kind": "http",
                        "url": url,
                        "method": method,
                        "status_code": resp.status_code,
                        "type": "image",
                        "file_id": file_id,
                        "path": f"/api/v1/files/{file_id}",
                        "content_type": mime_type,
                        "size_bytes": size,
                    },
                    TOOL_DEFINITION,
                    full_command,
                    partner_name,
                )

            try:
                text = content.decode("utf-8", errors="ignore")
                lines = text.splitlines()[:200]
            except Exception:
                lines = ["Binary content received (non-text, non-image)"]

            return ok_result(
                {
                    "schema_kind": "http",
                    "url": url,
                    "method": method,
                    "status_code": resp.status_code,
                    "type": "text",
                    "content": "\n".join(lines),
                    "content_type": content_type,
                    "size_bytes": size,
                    "truncated": len(lines) >= 200,
                },
                TOOL_DEFINITION,
                full_command,
                partner_name,
            )

    except Exception as e:
        category = _network_error_category(e)
        logger.warning(
            "[request_tools] HTTP failure category=%s type=%s url=%s: %s",
            category,
            type(e).__name__,
            url,
            e,
            exc_info=True,
        )
        return error_result(
            f"Request failed ({category}). Please try again later.",
            TOOL_DEFINITION,
            full_command,
            partner_name,
            category=category,
            data={"schema_kind": "http", "url": url, "method": method},
        )
