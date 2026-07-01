from __future__ import annotations

import ast
import inspect

from app.legacy_markup import (
    has_legacy_tool_markup,
    parse_image_path,
    strip_legacy_tool_blocks,
)


class TestStripLegacyToolBlocks:
    """Tests for legacy XML tool-markup cleanup."""

    def test_empty_text(self):
        commands, clean_text = strip_legacy_tool_blocks("")
        assert commands == []
        assert clean_text == ""

    def test_no_tool_blocks(self):
        text = "Hello there, this is just plain text.\nNo tools here."
        commands, clean_text = strip_legacy_tool_blocks(text)
        assert commands == []
        assert "Hello there" in clean_text
        assert "No tools here" in clean_text

    def test_single_tool_block(self):
        text = """Baik saya cek dulu
<command>
ls -la
</command>
Mari tunggu hasilnya"""
        commands, clean_text = strip_legacy_tool_blocks(text)
        assert commands == ["ls -la"]
        assert "Baik saya cek dulu" in clean_text
        assert "Mari tunggu hasilnya" in clean_text
        assert "<command>" not in clean_text
        assert "</command>" not in clean_text

    def test_multiple_tool_blocks(self):
        text = """<command>
echo \"hello\"
</command>
<command>
pwd
</command>
<command>
ls
</command>"""
        commands, clean_text = strip_legacy_tool_blocks(text)
        assert len(commands) == 3
        assert commands[0] == 'echo "hello"'
        assert commands[1] == "pwd"
        assert commands[2] == "ls"

    def test_max_three_tool_blocks(self):
        text = """<command>cmd1</command>
<command>cmd2</command>
<command>cmd3</command>
<command>cmd4</command>
<command>cmd5</command>"""
        commands, clean_text = strip_legacy_tool_blocks(text)
        assert len(commands) == 3
        assert commands == ["cmd1", "cmd2", "cmd3"]

    def test_empty_tool_block_ignored(self):
        text = """<command>
   
</command>
<command>
echo \"real\"
</command>"""
        commands, clean_text = strip_legacy_tool_blocks(text)
        assert len(commands) == 1
        assert commands[0] == 'echo "real"'

    def test_multiline_command(self):
        text = """<command>
for i in 1 2 3; do
    echo $i
done
</command>"""
        commands, clean_text = strip_legacy_tool_blocks(text)
        assert len(commands) == 1
        assert "for i in 1 2 3" in commands[0]
        assert "echo $i" in commands[0]

    def test_whitespace_stripped(self):
        text = """<command>
   
   ls -la   
   
</command>"""
        commands, clean_text = strip_legacy_tool_blocks(text)
        assert commands == ["ls -la"]

    def test_preserves_conversational_text(self):
        text = """Baik saya akan cek filenya.

<command>
cat config.json
</command>

Ini hasilnya ya."""
        commands, clean_text = strip_legacy_tool_blocks(text)
        assert commands == ["cat config.json"]
        assert "Baik saya akan cek filenya" in clean_text
        assert "Ini hasilnya ya" in clean_text

    def test_no_nested_tool_support(self):
        text = """<command>
outer <command>inner</command> command
</command>"""
        commands, clean_text = strip_legacy_tool_blocks(text)
        assert len(commands) == 1
        assert "outer" in commands[0]


class TestHasLegacyToolMarkup:
    """Tests for the legacy markup detector."""

    def test_returns_true_for_tool_blocks(self):
        assert has_legacy_tool_markup("<command>ls</command>") is True

    def test_returns_false_for_no_tool_blocks(self):
        assert has_legacy_tool_markup("just text") is False

    def test_returns_false_for_empty(self):
        assert has_legacy_tool_markup("") is False

    def test_returns_true_with_narration(self):
        assert has_legacy_tool_markup("hello <command>cmd</command> world") is True


class TestParseImagePath:
    """Tests for image path extraction from tool results."""

    def test_extracts_generated_image_src(self):
        contract = (
            "<details><summary>shell_tools</summary>"
            '<img src="static/generated_images/abc.png" /></details>'
        )
        assert parse_image_path(contract) == "static/generated_images/abc.png"

    def test_returns_none_when_no_image(self):
        assert parse_image_path("<details>no image</details>") is None
        assert parse_image_path("") is None


class TestLegacyCleanupIsolation:
    """Legacy cleanup utilities must not be wired into runtime execution."""

    def test_orchestrator_does_not_import_legacy_executor(self):
        from app import orchestrator

        source = inspect.getsource(orchestrator)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and "commands" in node.module
            ):
                for alias in node.names:
                    assert alias.name not in {"execute_commands", "parse_tool_blocks"}
