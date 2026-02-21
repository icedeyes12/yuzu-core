# tools/http_request.py

import os
import json
import requests
import socket
import ipaddress
from urllib.parse import urlparse
from datetime import datetime
from database import Database

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 90

SCHEMA = {
    "type": "function",
    "function": {
        "name": "request",
        "description": "Perform a public HTTPS GET request and return the response.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full HTTPS URL to fetch"
                }
            },
            "required": ["url"]
        }
    }
}


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
        url = arguments.get("url", "").strip()
    else:
        url = str(arguments).strip()

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
                f"/request {url}",
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
            f"/request {url}",
            lines,
            partner_name,
        )

    except Exception as e:
        return build_markdown_contract(
            "request_tools",
            f"/request {url}",
            [f"Error: {str(e)}"],
            partner_name,
        )