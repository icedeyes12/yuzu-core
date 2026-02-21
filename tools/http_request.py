# tools/http_request.py

import requests
from urllib.parse import urlparse
import socket
import ipaddress
from tools.registry import build_markdown_contract

MAX_BYTES = 2 * 1024 * 1024  # 2MB
TIMEOUT = 10


def is_safe_public_url(url: str) -> bool:
    parsed = urlparse(url)

    # Must be HTTPS
    if parsed.scheme != "https":
        return False

    if not parsed.hostname:
        return False

    try:
        ip = socket.gethostbyname(parsed.hostname)
        ip_obj = ipaddress.ip_address(ip)

        # Block private / loopback / reserved ranges
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


def execute(arguments, session_id=None):
    from database import Database

    url = arguments.strip()

    profile = Database.get_profile() or {}
    partner_name = profile.get("partner_name", "Yuzu")

    if not is_safe_public_url(url):
        return build_markdown_contract(
            "request_tools",
            f"/request {url}",
            ["Error: unsafe or invalid URL (HTTPS public endpoints only)"],
            partner_name,
        )

    try:
        resp = requests.get(url, timeout=TIMEOUT, stream=True)

        content = b""
        for chunk in resp.iter_content(8192):
            content += chunk
            if len(content) > MAX_BYTES:
                return build_markdown_contract(
                    "request_tools",
                    f"/request {url}",
                    ["Error: response too large (max 2MB)"],
                    partner_name,
                )

        text = content.decode("utf-8", errors="ignore")

        return build_markdown_contract(
            "request_tools",
            f"/request {url}",
            text.splitlines(),
            partner_name,
        )

    except Exception as e:
        return build_markdown_contract(
            "request_tools",
            f"/request {url}",
            [f"Error: {str(e)}"],
            partner_name,
        )