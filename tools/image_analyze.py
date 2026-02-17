import json
import re
import os
import base64
import requests
import hashlib
import time


SCHEMA = {
    "type": "function",
    "function": {
        "name": "image_analyze",
        "description": "Analyze an image referenced in the conversation. Use when the user references an image or visual details are required.",
        "parameters": {
            "type": "object",
            "properties": {
                "image_source": {
                    "type": "string",
                    "description": "The image URL, local path, or markdown image reference to analyze"
                }
            },
            "required": ["image_source"]
        }
    }
}

IMAGE_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'image_cache')
_memory_cache = {}
_cache_ttl = 3600


def _ensure_cache_dir():
    os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)


def _download_to_cache(url):
    """Download image to disk cache, return local path."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        return None
    hostname = parsed.hostname or ''
    if hostname in ('localhost', '127.0.0.1', '0.0.0.0', '::1', ''):
        return None

    url_hash = hashlib.sha1(url.encode('utf-8')).hexdigest()  # nosec

    for ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
        candidate = os.path.join(IMAGE_CACHE_DIR, f"{url_hash}{ext}")
        if os.path.isfile(candidate):
            return candidate

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()

        content_type = resp.headers.get('content-type', '')
        if 'png' in content_type:
            ext = '.png'
        elif 'gif' in content_type:
            ext = '.gif'
        elif 'webp' in content_type:
            ext = '.webp'
        else:
            ext = '.jpg'

        filepath = os.path.join(IMAGE_CACHE_DIR, f"{url_hash}{ext}")
        with open(filepath, 'wb') as f:
            f.write(resp.content)
        return filepath
    except Exception as e:
        print(f"[image_analyze] Download failed: {e}")
        return None


def _encode_to_base64(filepath):
    """Encode local file to base64 with mime type."""
    if not os.path.isfile(filepath):
        return None, None

    lower = filepath.lower()
    if lower.endswith('.png'):
        mime = 'image/png'
    elif lower.endswith('.gif'):
        mime = 'image/gif'
    elif lower.endswith('.webp'):
        mime = 'image/webp'
    else:
        mime = 'image/jpeg'

    with open(filepath, 'rb') as f:
        data = base64.b64encode(f.read()).decode('utf-8')
    return data, mime


def _resolve_source(source):
    """Resolve an image source (URL, local path, markdown) to a local cached file path.

    All input types follow the same pipeline:
      source → extract URL/path → download if remote → cache → return local path
    """
    # Extract URL from markdown syntax
    md_match = re.match(r'!\[[^\]]*\]\(([^)]+)\)', source)
    if md_match:
        source = md_match.group(1)

    # Strip whitespace
    source = source.strip()

    # Remote URL — always download to cache for uniform processing
    if source.startswith(('http://', 'https://')):
        _ensure_cache_dir()
        cached = _download_to_cache(source)
        return cached

    # Local file references
    if source.startswith('static/') or source.startswith('uploads/') or source.startswith('generated_images/'):
        local_path = source if source.startswith('static/') else f"static/{source}"
        if os.path.isfile(local_path):
            return local_path

    # Try as direct path
    if os.path.isfile(source):
        return source

    return None


def execute(arguments, **kwargs):
    source = arguments.get("image_source", "")
    if not source:
        return json.dumps({"error": "No image source provided"})

    filepath = _resolve_source(source)
    if not filepath:
        return json.dumps({"error": f"Could not resolve image: {source}"})

    image_base64, mime = _encode_to_base64(filepath)
    if not image_base64:
        return json.dumps({"error": f"Could not encode image: {filepath}"})

    return json.dumps({
        "image_base64": image_base64,
        "mime": mime
    })
