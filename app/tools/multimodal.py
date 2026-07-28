from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)


class MultimodalTools:
    IMAGE_CACHE_DIR: Path = (
        Path(__file__).resolve().parent.parent / "static" / "image_cache"
    )

    def __init__(self):

        # Image cache for base64 encoded images
        self.image_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.cache_ttl: int = 3600  # 1 hour TTL

        # Ensure cache directory exists
        self.IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _clean_cache(self):
        """Remove expired cache entries"""
        current_time = time.time()
        expired_keys = [
            key
            for key, (timestamp, _) in self.image_cache.items()
            if current_time - timestamp > self.cache_ttl
        ]
        for key in expired_keys:
            del self.image_cache[key]

    def download_image_to_cache(self, url: str) -> str | None:
        """Download an image from *url*, save it under ``IMAGE_CACHE_DIR`` and
        return the local file path.  The filename is derived from a SHA-1 hash
        of the URL so repeated downloads are avoided."""
        # Validate URL scheme to prevent SSRF attacks
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return None
        # Block requests to localhost / private IPs
        hostname = parsed.hostname or ""
        if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1", ""):
            return None

        url_hash = hashlib.sha1(url.encode("utf-8")).hexdigest()  # nosec - not used for security

        # Check if already cached with any common extension
        for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            candidate = self.IMAGE_CACHE_DIR / f"{url_hash}{ext}"
            if candidate.is_file():
                logger.debug(f"[Vision] Using cached image → {candidate}")
                return str(candidate)

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "png" in content_type:
                ext = ".png"
            elif "gif" in content_type:
                ext = ".gif"
            elif "webp" in content_type:
                ext = ".webp"
            else:
                ext = ".jpg"

            filepath = self.IMAGE_CACHE_DIR / f"{url_hash}{ext}"
            _ = filepath.write_bytes(response.content)

            logger.debug(f"[Vision] Downloaded image → {filepath}")
            return str(filepath)
        except Exception as e:
            logger.warning(f"[WARNING] Failed to download image from {url}: {e}")
            return None

    @staticmethod
    def encode_image_to_base64(filepath: str) -> dict[str, Any] | None:
        """Read a local image file and return an OpenAI-compatible
        ``image_url`` content block with a ``data:`` URI."""
        if not os.path.isfile(filepath):
            return None

        lower = filepath.lower()
        if lower.endswith(".png"):
            mime = "image/png"
        elif lower.endswith(".gif"):
            mime = "image/gif"
        elif lower.endswith(".webp"):
            mime = "image/webp"
        else:
            mime = "image/jpeg"

        with open(filepath, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")

        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}

    def extract_image_urls(self, text: str) -> list[str]:
        url_pattern = r'https?://[^\s<>"\'{}]{1,500}'
        urls = re.findall(url_pattern, text, re.IGNORECASE)

        image_urls = []
        for url in urls:
            if self._is_url_in_code_context(text, url):
                continue

            if any(
                domain in url.lower()
                for domain in [
                    "ibb.co",
                    "imgur.com",
                    "gyazo.com",
                    "prntscr.com",
                    "prnt.sc",
                    "tinypic.com",
                    "postimg.org",
                    "imageshack.us",
                    "flickr.com",
                    "deviantart.com",
                    "artstation.com",
                    "pinterest.com",
                    "cdn.discordapp.com",
                    "media.discordapp.net",
                    "i.redd.it",
                    "i.imgur.com",
                ]
            ):
                image_urls.append(url)
            elif re.search(r"\.(jpg|jpeg|png|gif|webp|bmp|svg)(\?.*)?$", url.lower()):
                image_urls.append(url)

        return image_urls

    def _is_url_in_code_context(self, text: str, url: str) -> bool:
        url_pos = text.find(url)
        if url_pos == -1:
            return False

        before_context = text[max(0, url_pos - 20) : url_pos]
        after_context = text[
            url_pos + len(url) : min(len(text), url_pos + len(url) + 20)
        ]

        code_indicators = [
            "import ",
            "from ",
            "def ",
            "class ",
            "//",
            "#",
            '"""',
            "'''",
            "/*",
            "*/",
            "`",
            "```",
        ]

        for indicator in code_indicators:
            if indicator in before_context or indicator in after_context:
                return True

        quote_count_before = before_context.count('"') + before_context.count("'")
        quote_count_after = after_context.count('"') + after_context.count("'")

        if (quote_count_before + quote_count_after) % 2 == 1:
            return True

        return False

    def _looks_like_code(self, text: str) -> bool:
        code_indicators = [
            "import ",
            "from ",
            "def ",
            "class ",
            "if __name__",
            "```",
            "    ",
            "\t",
            "// ",
            "# ",
            "/*",
            "*/",
        ]
        return any(indicator in text for indicator in code_indicators)

    def _is_likely_actual_image(self, url: str) -> bool:
        excluded_patterns = [
            "api/v1/chat/completions",
            "v1/chat/completions",
            "github.com",
            "openrouter.ai/api",
            "llm.chutes.ai/v1",
        ]

        if any(pattern in url.lower() for pattern in excluded_patterns):
            return False

        image_domains = ["ibb.co", "imgur.com", "i.imgur.com", "cdn.discordapp.com"]
        image_extensions = [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"]

        return any(domain in url.lower() for domain in image_domains) or any(
            ext in url.lower() for ext in image_extensions
        )

    def has_images(self, text: str) -> bool:
        if "![" in text and "](" in text and ")" in text:
            image_sources = self._extract_image_sources(text)
            if image_sources:
                return True

        if "UPLOADED_IMAGES:" in text and "IMAGE_UPLOAD:" in text:
            return True

        upload_patterns = [
            "UPLOADED_IMAGES:",
            "IMAGE_UPLOAD:",
            "static/uploads/",
            "static/generated_images/",
        ]

        if any(pattern in text for pattern in upload_patterns):
            return True

        urls = self.extract_image_urls(text)

        if self._looks_like_code(text):
            return len(urls) > 0 and any(
                self._is_likely_actual_image(url) for url in urls
            )

        return len(urls) > 0

    def download_and_encode_image(self, image_url: str) -> dict[str, Any] | None:
        """Download and encode image with caching support"""
        # Clean expired cache entries
        self._clean_cache()

        # Check cache first
        if image_url in self.image_cache:
            timestamp, cached_data = self.image_cache[image_url]
            if time.time() - timestamp < self.cache_ttl:
                return cached_data

        try:
            response = requests.get(image_url, timeout=30)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "jpeg" in content_type or "jpg" in content_type:
                mime_type = "image/jpeg"
            elif "png" in content_type:
                mime_type = "image/png"
            elif "gif" in content_type:
                mime_type = "image/gif"
            elif "webp" in content_type:
                mime_type = "image/webp"
            else:
                mime_type = "image/jpeg"

            image_data = base64.b64encode(response.content).decode("utf-8")
            result = {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{image_data}"},
            }

            # Cache the result
            self.image_cache[image_url] = (time.time(), result)
            return result

        except Exception:
            return None

    def format_vision_message(
        self, user_message: str, provider: str | None = None
    ) -> list[dict[str, Any]]:
        image_sources = self._extract_image_sources(user_message)

        if not image_sources:
            return [{"role": "user", "content": user_message}]

        clean_text = self._remove_image_markdown(user_message)

        content = [{"type": "text", "text": clean_text or "What's in this image?"}]

        # Defense-in-depth: even when a single source is listed once, dedupe
        # by realpath so a duplicate reference (e.g. the same file shown via
        # both a remote URL and a local cache path) never produces two
        # image_url blocks in the payload.
        seen: set[str] = set()
        for source in image_sources[:3]:  # Limit to 3 images
            try:
                key = os.path.realpath(source)
            except (OSError, ValueError):
                key = source
            if key in seen:
                continue
            seen.add(key)

            if source.startswith(("http://", "https://")):
                # Remote URL — download to cache, then encode
                cached_path = self.download_image_to_cache(source)
                if cached_path:
                    image_content = self.encode_image_to_base64(cached_path)
                    if image_content:
                        content.append(image_content)
            else:
                # Local file path — encode directly
                image_content = self.encode_image_to_base64(source)
                if image_content:
                    logger.debug(f"[Vision] Encoded local image → {source}")
                    content.append(image_content)

        return [{"role": "user", "content": content}]

    def _extract_image_sources(self, text: str) -> list[str]:
        """Extract image sources from text.  Returns local file paths for
        on-disk images and URLs for remote images."""
        import re

        markdown_pattern = r"!\[([^\]]*)\]\(([^)]+)\)"
        matches = re.findall(markdown_pattern, text)

        image_sources = []
        for _alt, url in matches:
            if (
                "onerror=" in url
                or "onload=" in url
                or "uploaded-image-container" in url
            ):
                continue

            if url.startswith("static/uploads/") or url.startswith(
                "static/generated_images/"
            ):
                # Local file — return path directly (don't convert to localhost URL)
                image_sources.append(url)
            elif url.startswith("uploads/") or url.startswith("generated_images/"):
                image_sources.append(f"static/{url}")
            else:
                image_sources.append(url)

        return image_sources

    def _remove_image_markdown(self, text: str) -> str:
        import re

        def replace_markdown(match):
            alt_text = match.group(1)
            if alt_text and alt_text not in ["Uploaded Image", "Generated Image"]:
                return f" [Image: {alt_text}] "
            return " [Image] "

        clean_text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace_markdown, text)

        clean_text = re.sub(r"\n\s*\n", "\n\n", clean_text)
        clean_text = clean_text.strip()

        return clean_text

    def detect_image_generation_request(
        self, text: str, is_ai_response: bool = False
    ) -> bool:
        text_lower = text.lower().strip()

        if is_ai_response:
            return text_lower.startswith("/imagine") or text_lower.startswith(
                "imagine "
            )
        else:
            if "/imagine" in text_lower:
                return True

            image_keywords = [
                "generate an image",
                "create an image",
                "make a picture",
                "draw me",
                "show me an image",
                "generate image",
                "create image",
            ]
            return any(keyword in text_lower for keyword in image_keywords)

    def extract_imagine_prompt(self, text: str, is_ai_response: bool = False) -> str:
        text_lower = text.lower()

        if is_ai_response:
            if text_lower.startswith("/imagine"):
                prompt = text[8:].strip()
            elif text_lower.startswith("imagine "):
                prompt = text[8:].strip()
            else:
                prompt = text.strip()
        else:
            if "/imagine" in text_lower:
                parts = text_lower.split("/imagine", 1)
                prompt = parts[1].strip() if len(parts) > 1 else text.strip()
            else:
                prompt = text.strip()
                remove_phrases = [
                    "can you",
                    "please",
                    "could you",
                    "would you",
                    "generate an image of",
                    "create an image of",
                    "make a picture of",
                    "draw me",
                    "show me an image of",
                ]
                for phrase in remove_phrases:
                    if prompt.lower().startswith(phrase):
                        prompt = prompt[len(phrase) :].strip()
                        break

        prompt = prompt.replace('"', "").replace("'", "").strip()

        if prompt.endswith(".") and not prompt.endswith("..."):
            prompt = prompt[:-1]

        return prompt

    def generate_image(
        self,
        prompt: str,
        provider: str = "chutes",
        model: str | None = None,
        size: str = "1024x1024",
    ) -> tuple[str | None, str | None]:
        """Legacy sync image helper retained for callers outside the dispatch path."""
        return None, "Image generation requires async execution"

    def should_use_vision(
        self, user_message: str, current_provider: str, current_model: str
    ) -> bool:
        """Determine if we should switch to a vision-capable model.

        Auto-switch logic:
        - If message has images AND current model doesn't support vision → switch
        - If message has images AND current model IS vision-capable → no switch needed

        Args:
            user_message: The user's message
            current_provider: Current provider name
            current_model: Current model name

        Returns:
            True if we should switch to vision model
        """
        if not self.has_images(user_message):
            return False

        # Check if message contains code-like content (not actual image)
        if (
            "onerror=" in user_message
            or "onload=" in user_message
            or "uploaded-image-container" in user_message
            or "generated-image-container" in user_message
        ):
            return False

        if self._looks_like_code(user_message):
            return False

        return False

    def detect_uploaded_images(self, text: str) -> list[str]:
        upload_patterns = [
            r"static/uploads/\d{8}_\d{6}_\d+_[^\s\)]{0,200}",
            r"static/generated_images/\d{8}_\d{6}_[^\s\)]{0,200}",
            r"!\[Image \d+\]\([^)]{1,200}\)",
        ]

        found_images = []
        for pattern in upload_patterns:
            matches = re.findall(pattern, text)
            found_images.extend(matches)

        return found_images

    def inject_vision_context(
        self,
        messages: list[dict[str, Any]],
        current_model: str,
    ) -> list[dict[str, Any]]:
        """Deprecated — returns *messages* unchanged.

        Image embedding is now handled in ``app.prompts.build_messages()``
        which converts ``attachments`` to base64 ``image_url`` blocks at
        build time.  This method is retained as a no-op stub so existing
        callers do not break.
        """
        return messages


multimodal_tools = MultimodalTools()
