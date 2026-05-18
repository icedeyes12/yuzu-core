# FILE: tests/test_commands.py
# DESCRIPTION: Pure-function tests for app.commands.
#              Tests the <tool>...</tool> protocol parser.

from __future__ import annotations

from app.commands import (
    execute_commands,
    format_observation,
    has_tool_blocks,
    parse_image_path,
    parse_tool_blocks,
)


class TestParseToolBlocks:
    """Tests for the core <tool> block parser."""

    def test_empty_text(self):
        commands, clean_text = parse_tool_blocks("")
        assert commands == []
        assert clean_text == ""

    def test_no_tool_blocks(self):
        text = "Hello there, this is just plain text.\nNo tools here."
        commands, clean_text = parse_tool_blocks(text)
        assert commands == []
        assert "Hello there" in clean_text
        assert "No tools here" in clean_text

    def test_single_tool_block(self):
        text = """Baik saya cek dulu
<tool>
ls -la
</tool>
Mari tunggu hasilnya"""
        commands, clean_text = parse_tool_blocks(text)
        assert commands == ["ls -la"]
        assert "Baik saya cek dulu" in clean_text
        assert "Mari tunggu hasilnya" in clean_text
        assert "<tool>" not in clean_text
        assert "</tool>" not in clean_text

    def test_multiple_tool_blocks(self):
        text = """<tool>
echo "hello"
</tool>
<tool>
pwd
</tool>
<tool>
ls
</tool>"""
        commands, clean_text = parse_tool_blocks(text)
        assert len(commands) == 3
        assert commands[0] == 'echo "hello"'
        assert commands[1] == "pwd"
        assert commands[2] == "ls"

    def test_max_three_tool_blocks(self):
        """More than 3 tool blocks should be ignored."""
        text = """<tool>cmd1</tool>
<tool>cmd2</tool>
<tool>cmd3</tool>
<tool>cmd4</tool>
<tool>cmd5</tool>"""
        commands, clean_text = parse_tool_blocks(text)
        assert len(commands) == 3
        assert commands == ["cmd1", "cmd2", "cmd3"]

    def test_empty_tool_block_ignored(self):
        text = """<tool>
   
</tool>
<tool>
echo "real"
</tool>"""
        commands, clean_text = parse_tool_blocks(text)
        assert len(commands) == 1
        assert commands[0] == 'echo "real"'

    def test_multiline_command(self):
        text = """<tool>
for i in 1 2 3; do
    echo $i
done
</tool>"""
        commands, clean_text = parse_tool_blocks(text)
        assert len(commands) == 1
        assert "for i in 1 2 3" in commands[0]
        assert "echo $i" in commands[0]

    def test_whitespace_stripped(self):
        text = """<tool>
   
   ls -la   
   
</tool>"""
        commands, clean_text = parse_tool_blocks(text)
        assert commands == ["ls -la"]

    def test_preserves_conversational_text(self):
        text = """Baik saya akan cek filenya.

<tool>
cat config.json
</tool>

Ini hasilnya ya."""
        commands, clean_text = parse_tool_blocks(text)
        assert commands == ["cat config.json"]
        assert "Baik saya akan cek filenya" in clean_text
        assert "Ini hasilnya ya" in clean_text

    def test_no_nested_tool_support(self):
        """Nested <tool> tags are not supported - outer block wins."""
        text = """<tool>
outer <tool>inner</tool> command
</tool>"""
        commands, clean_text = parse_tool_blocks(text)
        # Behavior: regex is non-greedy, so it matches first <tool>...</tool>
        # The inner <tool> is just text inside the outer block
        assert len(commands) == 1
        assert "outer" in commands[0]
        # The "inner" is just text, not parsed as a separate block


class TestHasToolBlocks:
    """Tests for the has_tool_blocks helper."""

    def test_returns_true_for_tool_blocks(self):
        assert has_tool_blocks("<tool>ls</tool>") is True

    def test_returns_false_for_no_tool_blocks(self):
        assert has_tool_blocks("just text") is False

    def test_returns_false_for_empty(self):
        assert has_tool_blocks("") is False

    def test_returns_true_with_narration(self):
        assert has_tool_blocks("hello <tool>cmd</tool> world") is True


class TestFormatObservation:
    """Tests for the observation formatter."""

    def test_single_success_result(self):
        results = [
            ("bash", {
                "ok": True,
                "data": {
                    "command": "ls",
                    "exit_code": 0,
                    "stdout": "file1.txt\nfile2.txt",
                    "stderr": "",
                }
            })
        ]
        obs = format_observation(results)
        assert "<SYSTEM_OBSERVATION>" in obs
        assert "</SYSTEM_OBSERVATION>" in obs
        assert "Command 1:" in obs
        assert "TOOL: bash" in obs
        assert "STATUS: SUCCESS" in obs
        assert "COMMAND: ls" in obs
        assert "EXIT_CODE: 0" in obs
        assert "file1.txt" in obs

    def test_multiple_results(self):
        results = [
            ("bash", {"ok": True, "data": {"exit_code": 0, "stdout": "ok"}}),
            ("bash", {"ok": False, "error": "Command failed"}),
        ]
        obs = format_observation(results)
        assert "Command 1:" in obs
        assert "Command 2:" in obs
        assert "STATUS: SUCCESS" in obs
        assert "STATUS: FAILED" in obs
        assert "ERROR: Command failed" in obs

    def test_empty_results(self):
        obs = format_observation([])
        assert obs == ""


class TestParseImagePath:
    """Tests for image path extraction from tool results."""

    def test_extracts_generated_image_src(self):
        contract = (
            '<details><summary>shell_tools</summary>'
            '<img src="static/generated_images/abc.png" /></details>'
        )
        assert parse_image_path(contract) == "static/generated_images/abc.png"

    def test_returns_none_when_no_image(self):
        assert parse_image_path("<details>no image</details>") is None
        assert parse_image_path("") is None


class TestExecuteCommands:
    """Tests for command execution (integration-ish)."""

    def test_empty_commands(self):
        results = execute_commands([])
        assert results == []

    def test_invalid_command_format(self):
        """Invalid command string should return error result."""
        results = execute_commands(["   "])  # Empty/whitespace command
        assert len(results) == 1
        tool_name, result = results[0]
        assert tool_name == "unknown"
        assert result.get("ok") is False
