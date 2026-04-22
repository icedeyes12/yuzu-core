# FILE: tests/test_commands.py
# DESCRIPTION: Pure-function tests for app.commands.

from __future__ import annotations

from app.commands import (
    detect_command,
    extract_markdown_image_path,
    is_markdown_image_shortcut,
    parse_image_path,
)


class TestDetectCommand:
    def test_returns_none_for_empty(self):
        assert detect_command("") is None
        assert detect_command(None) is None
        assert detect_command("   \n  ") is None

    def test_returns_none_when_no_leading_slash(self):
        assert detect_command("hello there") is None
        assert detect_command("  /imagine cat") is None  # leading whitespace

    def test_parses_command_without_args(self):
        result = detect_command("/help")
        assert result == {"command": "help", "args": "", "full_command": "/help"}

    def test_parses_command_with_args(self):
        result = detect_command("/imagine a fluffy cat\nrest of response")
        assert result == {
            "command": "imagine",
            "args": "a fluffy cat",
            "full_command": "/imagine a fluffy cat",
        }

    def test_only_inspects_first_line(self):
        text = "hello\n/imagine cat"
        assert detect_command(text) is None


class TestMarkdownImageShortcut:
    def test_detects_static_path(self):
        assert is_markdown_image_shortcut(
            "![generated](static/generated_images/foo.png)"
        )

    def test_detects_uploads_path(self):
        assert is_markdown_image_shortcut("![alt](uploads/foo.jpg)")

    def test_ignores_remote_url(self):
        assert not is_markdown_image_shortcut(
            "![alt](https://example.com/foo.png)"
        )

    def test_ignores_empty(self):
        assert not is_markdown_image_shortcut("")
        assert not is_markdown_image_shortcut(None)

    def test_extract_path_returns_first_match(self):
        text = "text ![a](x.png) and ![b](y.png)"
        assert extract_markdown_image_path(text) == "x.png"

    def test_extract_path_returns_none_when_absent(self):
        assert extract_markdown_image_path("no image here") is None


class TestParseImagePath:
    def test_extracts_generated_image_src(self):
        contract = (
            '<details><summary>image_tools</summary>'
            '<img src="static/generated_images/abc.png" /></details>'
        )
        assert parse_image_path(contract) == "static/generated_images/abc.png"

    def test_returns_none_when_no_image(self):
        assert parse_image_path("<details>no image</details>") is None
        assert parse_image_path("") is None
