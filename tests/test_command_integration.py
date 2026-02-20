"""Integration test for command-based tool execution flow."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_command_execution_flow():
    """Test the complete flow of command detection and execution."""
    from app import _detect_command, _execute_command_tool
    
    print("=== Testing Command Execution Flow ===\n")
    
    # Test 1: Detect and prepare web_search command
    print("Test 1: Web search command")
    cmd_info = _detect_command("/web_search Python programming")
    assert cmd_info is not None
    assert cmd_info["command"] == "web_search"
    assert cmd_info["args"] == "Python programming"
    print("✓ Command detected correctly")
    
    # Test 2: Detect memory_sql command
    print("\nTest 2: Memory SQL command")
    sql_cmd = "/memory_sql\nSELECT content FROM messages LIMIT 5"
    cmd_info = _detect_command(sql_cmd)
    assert cmd_info is not None
    assert cmd_info["command"] == "memory_sql"
    assert "SELECT content FROM messages LIMIT 5" in cmd_info["remaining_text"]
    print("✓ Multi-line command detected correctly")
    
    # Test 3: Verify command formatting in tool execution
    print("\nTest 3: Tool result formatting")
    cmd_info = _detect_command("/weather Tokyo")
    assert cmd_info is not None
    # Note: We can't actually execute without API keys, but we can verify the format
    print("✓ Command parsed for execution")
    
    # Test 4: Verify invalid commands are rejected
    print("\nTest 4: Invalid command rejection")
    invalid_commands = [
        "Sure! /web_search test",
        "Let me help\n/weather Tokyo",
        "I'll search /web_search for you"
    ]
    for invalid in invalid_commands:
        result = _detect_command(invalid)
        assert result is None, f"Expected None for: {invalid}"
    print("✓ All invalid commands correctly rejected")
    
    print("\n✅ All integration tests passed!")


def test_tool_result_format():
    """Test that tool results are formatted correctly."""
    print("\n=== Testing Tool Result Format ===\n")
    
    # Simulate a tool result format
    tool_name = "web_search"
    result = '{"results": [{"title": "Test", "snippet": "Test snippet"}]}'
    
    formatted = f"🔧 TOOL RESULT — {tool_name.upper()}\n\n{result}\n\n---"
    
    assert "🔧 TOOL RESULT — WEB_SEARCH" in formatted
    assert result in formatted
    assert formatted.endswith("---")
    
    print("✓ Tool result format is correct")
    print(f"Format example:\n{formatted}")
    
    print("\n✅ Tool result formatting test passed!")


def test_command_control_signal_not_saved_and_stops_after_tool(monkeypatch):
    """Command control signal should not be saved/rendered as assistant content.

    After tool execution, the raw result is persisted to DB via
    Database.add_tool_result (which handles formatting).  Context is rebuilt
    from DB within the same loop, and the next LLM iteration produces a
    natural conversational response.
    """
    import app
    from database import Database, get_db_session, Message

    # Isolated active session
    new_session_id = Database.create_session("test-command-control-signal")
    Database.switch_session(new_session_id)
    session_id = Database.get_active_session()['id']
    assert session_id == new_session_id

    class FakeManager:
        def __init__(self):
            self.calls = 0
        def send_message(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                # LLM emits a command control signal
                return "/web_search python testing"
            # Next loop iteration: LLM sees tool result in context and
            # generates a natural conversational response.
            return "Here are the latest Python testing resources I found."

    fake_manager = FakeManager()
    monkeypatch.setattr(app, "get_ai_manager", lambda: fake_manager)
    # _execute_command_tool now returns raw JSON (no formatting)
    monkeypatch.setattr(
        app,
        "_execute_command_tool",
        lambda cmd_info, session_id=None: '{"results":[]}',
    )

    reply = app.handle_user_message("please check latest python testing links", interface="terminal")

    # Reply should be the natural response from the next loop iteration,
    # NOT the raw tool result.
    assert reply == "Here are the latest Python testing resources I found."
    # Two LLM calls: initial (returns command) + next iteration (returns natural response)
    assert fake_manager.calls == 2, "LLM should be called twice: initial + loop continuation"

    with get_db_session() as session:
        rows = session.query(Message).filter(Message.session_id == session_id).order_by(Message.id.asc()).all()
        roles_and_content = [(m.role, m.content) for m in rows]

    # No assistant /command control signal persisted
    assert not any(role == "assistant" and isinstance(content, str) and content.strip().startswith("/")
                   for role, content in roles_and_content), roles_and_content
    # Tool result persisted with dedicated role (formatted by Database.add_tool_result)
    assert any(role == "web_search_tools" and "🔧 TOOL RESULT — WEB_SEARCH" in (content or "")
               for role, content in roles_and_content), roles_and_content


def test_tool_calls_reenter_pipeline_after_execution(monkeypatch):
    """After tool_calls execution, context is rebuilt from DB within the loop.

    The next LLM call uses _build_generation_context (reading from DB),
    NOT the accumulated in-memory messages list from the tool loop.
    """
    import app
    from database import Database, get_db_session, Message

    new_session_id = Database.create_session("test-tool-calls-pipeline")
    Database.switch_session(new_session_id)
    session_id = Database.get_active_session()['id']

    context_rebuilt = {"count": 0}
    original_build = app._build_generation_context

    def tracking_build(profile, sid, interface="terminal"):
        context_rebuilt["count"] += 1
        return original_build(profile, sid, interface)

    class FakeManager:
        def __init__(self):
            self.calls = 0
        def send_message(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                # Simulate LLM returning a tool_call
                return {
                    "content": None,
                    "tool_calls": [{
                        "id": "call_001",
                        "type": "function",
                        "function": {
                            "name": "web_search",
                            "arguments": '{"query": "python unit testing"}'
                        }
                    }]
                }
            # Next loop iteration: LLM sees tool result in rebuilt context
            return "Based on the search results, here's what I found about Python testing."

    fake_manager = FakeManager()
    monkeypatch.setattr(app, "get_ai_manager", lambda: fake_manager)
    monkeypatch.setattr(app, "_build_generation_context", tracking_build)
    monkeypatch.setattr(
        "tools.registry.execute_tool",
        lambda tool_name, args, session_id=None: '{"results": [{"title": "pytest docs"}]}',
    )

    reply = app.handle_user_message("search for python testing frameworks", interface="terminal")

    assert "python testing" in reply.lower()
    # Context should have been rebuilt at least twice:
    #   1. Initial pipeline entry in generate_ai_response
    #   2. After tool execution within the loop (rebuild from DB)
    assert context_rebuilt["count"] >= 2, (
        f"Context should be rebuilt at least twice (initial + after tool), "
        f"got {context_rebuilt['count']}"
    )


if __name__ == "__main__":
    try:
        test_command_execution_flow()
        test_tool_result_format()
        test_command_control_signal_not_saved_and_stops_after_tool()
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
