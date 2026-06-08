from __future__ import annotations
# FILE: app/tools/http_request.py
# DESCRIPTION: HTTP request tool for external API calls


import logging
import httpx
import socket
import ipaddress
import re
from urllib.parse import urlparse
from datetime import datetime
from pathlib import Path
from app.tools.schemas import ToolDefinition, ToolParam, ok_result, error_result

logger = logging.getLogger(__name__)

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 90


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
    is_terminal=True,
)


def is_safe_public_url(url: str) -> tuple[bool, str]:
    """Validate URL is safe public HTTPS endpoint.

    Returns:
        (is_safe, reason) tuple. Reason is empty string if valid.
    """
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


def _extract_url(args_str: str) -> tuple:
    """Extract HTTP method and URL from arguments.

    Supports formats like:
    - "https://example.com" (implicit GET)
    - "GET https://example.com"
    - "POST https://example.com"

    Returns: (method, url) tuple, defaults to GET if no method specified.
    """
    args_str = args_str.strip()

    method_match = re.match(
        r"^(GET|POST|PUT|DELETE|PATCH)\s+(.+)$", args_str, re.IGNORECASE
    )
    if method_match:
        method = method_match.group(1).upper()
        url = method_match.group(2).strip()
        return method, url

    return "GET", args_str


def get_media_dir() -> Path:
    media_dir = Path(__file__).resolve().parent.parent / "static" / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    return media_dir


async def execute(arguments, **kwargs):
    from app.db import Database

    profile = await Database.get_profile_async() or {}
    partner_name = profile.get("partner_name", "Yuzu")

    if isinstance(arguments, dict):
        args_str = arguments.get("url", "").strip()
    else:
        args_str = str(arguments).strip()

    # Extract HTTP method and URL from arguments
    method, url = _extract_url(args_str)

    # Allow method override from arguments dict
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
        )

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.request(
                method, url, timeout=TIMEOUT, follow_redirects=True
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
                media_dir = get_media_dir()

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                ext = content_type.split("/")[-1].split(";")[0]
                filename = f"{timestamp}.{'jpg' if ext == 'jpeg' else ext}"
                filepath = media_dir / filename

                filepath.write_bytes(content)

                web_path = f"static/media/{filename}"

                return ok_result(
                    {
                        "type": "image",
                        "path": web_path,
                        "content_type": content_type,
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
        logger.warning(f"[request_tools] Exception during HTTP request: {e}")
        return error_result(
            "Request failed. Please check the URL or try again later.",
            TOOL_DEFINITION,
            full_command,
            partner_name,
        )
