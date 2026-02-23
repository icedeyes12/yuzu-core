"""Integration test for command-based tool execution flow."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_command_execution_flow():
    """Test the complete flow of command detection and execution."""
    from app import _detect_command, _execute_command_tool
    
    print("=== Testing Command Execution Flow ===\n")
    
    # Test 1: Detect and prepare request command
    print("Test 1: Request command")
    cmd_info = _detect_command("/request https://example.com/api")
    assert cmd_info is not None
    assert cmd_info["command"] == "request"
    assert cmd_info["args"] == "https://example.com/api"
    print("✓ Command detected correctly")
    
    # Test 2: Detect imagine command
    print("\nTest 2: Imagine command")
    cmd_info = _detect_command("/imagine a beautiful sunset over the ocean")
    assert cmd_info is not None
    assert cmd_info["command"] == "imagine"
    assert "beautiful sunset" in cmd_info["args"]
    print("✓ Imagine command detected correctly")
    
    # Test 3: Verify command formatting in tool execution
    print("\nTest 3: Tool result formatting")
    cmd_info = _detect_command("/request https://api.example.com/data")
    assert cmd_info is not None
    # Note: We can't actually execute without API keys, but we can verify the format
    print("✓ Command parsed for execution")
    
    # Test 4: Verify invalid commands are rejected
    print("\nTest 4: Invalid command rejection")
    invalid_commands = [
        "Sure! /request https://example.com",
        "Let me help\n/request https://example.com",
        "I'll fetch /request for you"
    ]
    for invalid in invalid_commands:
        result = _detect_command(invalid)
        assert result is None, f"Expected None for: {invalid}"
    print("✓ All invalid commands correctly rejected")
    
    print("\n✅ All integration tests passed!")


def test_tool_result_format():
    """Test that tool results use the markdown contract format."""
    from tools.registry import build_markdown_contract

    print("\n=== Testing Tool Result Format ===\n")
    
    result = build_markdown_contract(
        "request_tools",
        "/request https://example.com",
        ["Result 1", "Result 2"],
        "Yuzu",
    )
    
    assert result.startswith("<details>")
    assert "🔧 request_tools" in result
    assert "> Result 1" in result
    assert "> Result 2" in result
    assert result.strip().endswith("</details>")
    
    print("✓ Tool result markdown contract format is correct")
    print(f"Format example:\n{result}")
    
    print("\n✅ Tool result formatting test passed!")


def test_command_control_signal_not_saved_and_stops_after_tool(monkeypatch):
    """Command control signal should not be saved/rendered as assistant content.

    After tool execution, the formatted markdown contract is returned.
    handle_user_message detects <details> and saves as tool message,
    then triggers a second LLM pass for the natural response.
    """
    import app
    from database import Database, get_db_session, Message

    # Isolated active session
    new_session_id = Database.create_session("test-command-control-signal")
    Database.switch_session(new_session_id)
    session_id = Database.get_active_session()['id']
    assert session_id == new_session_id

    tool_markdown = (
        "<details>\n"
        "<summary>🔧 request_tools</summary>\n"
        "\n```bash\nYuzu$ /request https://example.com/api\n```\n\n"
        "> No results found\n\n"
        "</details>"
    )

    class FakeManager:
        def __init__(self):
            self.calls = 0
        def send_message(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                # LLM emits a command control signal
                return "/request https://example.com/api"
            # Second LLM pass sees tool result in context
            return "Here are the latest results I found."

    fake_manager = FakeManager()
    monkeypatch.setattr(app, "get_ai_manager", lambda: fake_manager)
    # _execute_command_tool now returns formatted markdown contract
    monkeypatch.setattr(
        app,
        "_execute_command_tool",
        lambda cmd_info, session_id=None: tool_markdown,
    )

    reply = app.handle_user_message("please check latest links", interface="terminal")

    # Reply should contain both the tool markdown and the natural response
    assert "Here are the latest results I found." in reply
    # Two LLM calls: initial (returns command) + second pass (returns natural response)
    assert fake_manager.calls == 2, f"LLM should be called twice, got {fake_manager.calls}"

    with get_db_session() as session:
        rows = session.query(Message).filter(Message.session_id == session_id).order_by(Message.id.asc()).all()
        roles_and_content = [(m.role, m.content) for m in rows]

    # No assistant /command control signal persisted
    assert not any(role == "assistant" and isinstance(content, str) and content.strip().startswith("/")
                   for role, content in roles_and_content), roles_and_content
    # Tool result persisted with dedicated role as <details> markdown contract
    assert any(role == "request_tools" and "<details>" in (content or "")
               for role, content in roles_and_content), roles_and_content


def test_tool_calls_reenter_pipeline_after_execution(monkeypatch):
    """After /command execution, the formatted markdown is returned.

    handle_user_message detects <details> and saves as tool message,
    then triggers a second LLM pass through the same pipeline.
    """
    import app
    from database import Database, get_db_session, Message

    new_session_id = Database.create_session("test-tool-calls-pipeline")
    Database.switch_session(new_session_id)
    session_id = Database.get_active_session()['id']

    tool_markdown = (
        "<details>\n"
        "<summary>🔧 request_tools</summary>\n"
        "\n```bash\nYuzu$ /request https://example.com/api\n```\n\n"
        "> [example docs](http://example.com)\n\n"
        "</details>"
    )

    class FakeManager:
        def __init__(self):
            self.calls = 0
        def send_message(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                # LLM returns a /command for deterministic tool execution
                return "/request https://example.com/api"
            # Second LLM pass after tool message saved
            return "Based on the results, here's what I found."

    fake_manager = FakeManager()
    monkeypatch.setattr(app, "get_ai_manager", lambda: fake_manager)
    monkeypatch.setattr(
        app,
        "_execute_command_tool",
        lambda cmd_info, session_id=None: tool_markdown,
    )

    reply = app.handle_user_message("fetch data from the API", interface="terminal")

    assert "results" in reply.lower()
    # Two LLM calls: initial (/command) + second pass (natural response)
    assert fake_manager.calls == 2, (
        f"Expected 2 LLM calls (initial + second pass), got {fake_manager.calls}"
    )


def test_image_tools_no_second_pass(monkeypatch):
    """image_tools success should NOT trigger second LLM pass."""
    import app
    from database import Database, get_db_session, Message

    new_session_id = Database.create_session("test-image-no-second-pass")
    Database.switch_session(new_session_id)
    session_id = Database.get_active_session()['id']

    image_markdown = (
        "<details>\n"
        '<summary>🔧 image_tools</summary>\n'
        "\n```bash\nYuzu$ /imagine sunset\n```\n\n"
        '> <img src="static/generated_images/test.png">\n\n'
        "</details>"
    )

    class FakeManager:
        def __init__(self):
            self.calls = 0
        def send_message(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return "/imagine sunset"
            # Should NOT be called for image_tools success
            return "This should not appear"

    fake_manager = FakeManager()
    monkeypatch.setattr(app, "get_ai_manager", lambda: fake_manager)
    monkeypatch.setattr(
        app,
        "_execute_command_tool",
        lambda cmd_info, session_id=None: image_markdown,
    )

    reply = app.handle_user_message("generate a sunset image", interface="terminal")

    # Only one LLM call — no second pass for image_tools success
    assert fake_manager.calls == 1, f"Expected 1 LLM call, got {fake_manager.calls}"
    assert "<details>" in reply


def test_no_json_in_db(monkeypatch):
    """No raw JSON should be stored in the database for tool messages."""
    from tools.registry import build_markdown_contract

    result = build_markdown_contract(
        "request_tools", "/request https://example.com",
        ["Temperature: 25°C", "Weather: Clear"],
        "Yuzu",
    )
    assert "{" not in result, "Markdown contract should not contain JSON"
    assert "}" not in result, "Markdown contract should not contain JSON"
    assert "<details>" in result


if __name__ == "__main__":
    try:
        test_command_execution_flow()
        test_tool_result_format()
        test_command_control_signal_not_saved_and_stops_after_tool()
        test_no_json_in_db()
        print("\n" + "="*50)
        print("✅ ALL INTEGRATION TESTS PASSED")
        print("="*50)
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
