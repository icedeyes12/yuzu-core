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


class TestToolAliases:
    def test_imagine_maps_to_image_generate(self):
        from app.commands import _TOOL_ALIASES
        assert _TOOL_ALIASES["imagine"] == "image_generate"

    def test_image_generate_maps_to_self(self):
        from app.commands import _TOOL_ALIASES
        assert _TOOL_ALIASES["image_generate"] == "image_generate"


class TestNativeToolCallParsing:
    def test_parse_raw_tool_calls_none(self):
        from app.orchestrator import _parse_raw_tool_calls
        assert _parse_raw_tool_calls("chutes", None) == []

    def test_parse_raw_tool_calls_empty(self):
        from app.orchestrator import _parse_raw_tool_calls
        assert _parse_raw_tool_calls("chutes", {}) == []

    def test_parse_raw_tool_calls_unknown_provider(self):
        from app.orchestrator import _parse_raw_tool_calls
        import json
        args_str = json.dumps({"prompt": "cat"})
        raw = {"choices": [{"message": {"content": "", "tool_calls": [{"id": "1", "function": {"name": "image_generate", "arguments": args_str}}]}}]}
        assert _parse_raw_tool_calls("nonexistent", raw) == []

    def test_parse_raw_tool_calls_with_mock_provider(self):
        """Test _parse_raw_tool_calls with a mocked provider that supports tool calls."""
        from app.orchestrator import _parse_raw_tool_calls
        from unittest.mock import MagicMock, patch
        import json

        args_str = json.dumps({"prompt": "a fluffy cat"})
        raw = {"choices": [{"message": {"content": "", "tool_calls": [{"id": "call_1", "function": {"name": "image_generate", "arguments": args_str}}]}}]}

        mock_provider = MagicMock()
        mock_provider.parse_tool_calls.return_value = [
            {"id": "call_1", "name": "image_generate", "arguments": {"prompt": "a fluffy cat"}}
        ]
        mock_manager = MagicMock()
        mock_manager.providers.get.return_value = mock_provider

        with patch("app.providers.get_ai_manager", return_value=mock_manager):
            result = _parse_raw_tool_calls("any_provider", raw)

        assert len(result) == 1
        assert result[0]["name"] == "image_generate"
        assert result[0]["arguments"]["prompt"] == "a fluffy cat"

    def test_parse_raw_tool_calls_no_tool_calls(self):
        from app.orchestrator import _parse_raw_tool_calls
        raw = {"choices": [{"message": {"content": "just text", "tool_calls": []}}]}
        assert _parse_raw_tool_calls("openrouter", raw) == []

    def test_parse_raw_tool_calls_chutes_returns_empty(self):
        from app.orchestrator import _parse_raw_tool_calls
        raw = {"choices": [{"message": {"content": "/imagine cat"}}]}
        # Chutes doesn't support native tool calls, so parse returns empty
        assert _parse_raw_tool_calls("chutes", raw) == []
