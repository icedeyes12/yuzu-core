# tools/http_request.py

import os
import json
import requests
import socket
import ipaddress
import re
from urllib.parse import urlparse
from datetime import datetime
from database import Database

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 90

# validate public https url
def is_safe_public_url(url: str) -> bool:
    parsed = urlparse(url)

    if parsed.scheme != "https":
        return False

    if not parsed.hostname:
        return False

    try:
        ip = socket.gethostbyname(parsed.hostname)
        ip_obj = ipaddress.ip_address(ip)

        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_reserved
        ):
            return False
    except Exception:
        return False

    return True


def _extract_url(args_str: str) -> tuple:
    """Extract HTTP method and URL from arguments.
    
    Supports formats like:
    - "https://example.com" (implicit GET)
    - "GET https://example.com"
    - "POST https://example.com"
    
    Returns: (method, url) tuple, defaults to GET if no method specified.
    """
    args_str = args_str.strip()
    
    # Check for explicit HTTP method
    method_match = re.match(r'^(GET|POST|PUT|DELETE|PATCH)\s+(.+)$', args_str, re.IGNORECASE)
    if method_match:
        method = method_match.group(1).upper()
        url = method_match.group(2).strip()
        return method, url
    
    # No method specified, default to GET
    return "GET", args_str


# resolve absolute media directory
def get_media_dir():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    media_dir = os.path.join(project_root, "static", "media")
    os.makedirs(media_dir, exist_ok=True)
    return media_dir


# execute request tool
def execute(arguments, session_id=None):
    from tools.registry import build_markdown_contract

    profile = Database.get_profile() or {}
    partner_name = profile.get("partner_name", "Yuzu")

    if isinstance(arguments, dict):
        args_str = arguments.get("url", "").strip()
    else:
        args_str = str(arguments).strip()

    # Extract HTTP method and URL from arguments
    method, url = _extract_url(args_str)

    if not url:
        return build_markdown_contract(
            "request_tools",
            "/request",
            ["Error: No URL provided"],
            partner_name,
        )

    if not is_safe_public_url(url):
        return build_markdown_contract(
            "request_tools",
            f"/request {args_str}",
            ["Error: unsafe or invalid URL (HTTPS public endpoints only)"],
            partner_name,
        )

    try:
        # Use the extracted method (currently only GET is fully supported)
        if method == "POST":
            resp = requests.post(url, timeout=TIMEOUT, stream=True)
        elif method == "PUT":
            resp = requests.put(url, timeout=TIMEOUT, stream=True)
        elif method == "DELETE":
            resp = requests.delete(url, timeout=TIMEOUT, stream=True)
        else:
            # Default to GET
            resp = requests.get(url, timeout=TIMEOUT, stream=True)

        content = b""
        for chunk in resp.iter_content(8192):
            content += chunk
            if len(content) > MAX_BYTES:
                return build_markdown_contract(
                    "request_tools",
                    f"/request {args_str}",
                    ["Error: response too large (max 2MB)"],
                    partner_name,
                )

        content_type = resp.headers.get("Content-Type", "")
        size = len(content)

        if content_type.startswith("image/"):
            media_dir = get_media_dir()

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            ext = content_type.split("/")[-1].split(";")[0]
            filename = f"{timestamp}.{'jpg' if ext == 'jpeg' else ext}"
            filepath = os.path.join(media_dir, filename)

            with open(filepath, "wb") as f:
                f.write(content)

            web_path = f"static/media/{filename}"

            return build_markdown_contract(
                "request_tools",
                f"/request {args_str}",
                [
                    f'<img src="{web_path}" alt="Fetched Image">',
                    f"Content-Type: {content_type}",
                    f"Size: {size} bytes"
                ],
                partner_name,
            )

        try:
            text = content.decode("utf-8", errors="ignore")
            lines = text.splitlines()[:200]
        except Exception:
            lines = ["Binary content received (non-text, non-image)"]

        return build_markdown_contract(
            "request_tools",
            f"/request {args_str}",
            lines,
            partner_name,
        )

    except Exception as e:
        return build_markdown_contract(
            "request_tools",
            f"/request {args_str}",
            [f"Error: {str(e)}"],
            partner_name,
        )