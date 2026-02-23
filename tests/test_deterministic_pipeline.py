"""Tests for the deterministic tool execution pipeline.

Validates:
  - User message saved AFTER successful LLM response (not before).
  - No agentic looping (single LLM call per generate_ai_response invocation).
  - LLM context only contains system/user/assistant roles.
  - image_tools is TERMINAL (no second pass on success).
  - Other tools trigger exactly one second pass.
  - Tool command is a control signal only (not saved as assistant).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_user_message_saved_after_llm_response(monkeypatch):
    """User message must be persisted to DB AFTER the LLM responds, not before."""
    import app
    from database import Database, get_db_session, Message

    new_session_id = Database.create_session("test-save-order")
    Database.switch_session(new_session_id)
    session_id = Database.get_active_session()['id']

    save_order = []

    original_add_message = Database.add_message

    def tracking_add_message(role, content, session_id=None, image_paths=None):
        save_order.append(role)
        return original_add_message(role, content, session_id=session_id, image_paths=image_paths)

    monkeypatch.setattr(Database, "add_message", staticmethod(tracking_add_message))

    class FakeManager:
        def __init__(self):
            self.calls = 0
            self.messages_at_call = []

        def send_message(self, *args, **kwargs):
            self.calls += 1
            # Record what messages the LLM sees
            if args:
                messages = args[2] if len(args) > 2 else kwargs.get('messages', [])
            else:
                messages = kwargs.get('messages', [])
            self.messages_at_call.append(
                [(m['role'], m.get('content', '')[:50]) for m in messages]
            )
            return "Hello there!"

    fake_manager = FakeManager()
    monkeypatch.setattr(app, "get_ai_manager", lambda: fake_manager)

    reply = app.handle_user_message("hi there", interface="terminal")

    # DB saves happen only after the LLM responds.
    # First save: user message (persisted after LLM call), then assistant reply.
    assert save_order[0] == 'user', f"First save should be 'user', got {save_order}"
    assert save_order[1] == 'assistant', f"Second save should be 'assistant', got {save_order}"

    # Verify the user message was NOT in DB when LLM was called
    # The LLM should see user message appended in-memory, not from DB
    assert fake_manager.calls == 1
    llm_messages = fake_manager.messages_at_call[0]
    # The last message in the context should be the user message (appended in-memory)
    last_msg = llm_messages[-1]
    assert last_msg[0] == 'user', f"Last context message should be user, got {last_msg}"
    assert 'hi there' in last_msg[1], f"User message should be in context: {last_msg}"


def test_no_agentic_loop_single_llm_call(monkeypatch):
    """generate_ai_response should make exactly ONE LLM call, no looping."""
    import app
    from database import Database

    new_session_id = Database.create_session("test-no-loop")
    Database.switch_session(new_session_id)

    class FakeManager:
        def __init__(self):
            self.calls = 0

        def send_message(self, *args, **kwargs):
            self.calls += 1
            return "Just a normal response"

    fake_manager = FakeManager()
    monkeypatch.setattr(app, "get_ai_manager", lambda: fake_manager)

    profile = Database.get_profile()
    session_id = Database.get_active_session()['id']

    result = app.generate_ai_response(profile, "test message", "terminal", session_id)

    assert fake_manager.calls == 1, f"Expected exactly 1 LLM call, got {fake_manager.calls}"
    assert result == "Just a normal response"


def test_no_agentic_loop_with_tool_call(monkeypatch):
    """When LLM returns a /command, execute it and return — no second LLM call inside generate_ai_response."""
    import app
    from database import Database

    new_session_id = Database.create_session("test-no-loop-tool")
    Database.switch_session(new_session_id)

    tool_markdown = (
        "<details>\n"
        "<summary>🔧 request_tools</summary>\n"
        "\n```bash\nYuzu$ /request https://example.com\n```\n\n"
        "> Result found\n\n"
        "</details>"
    )

    class FakeManager:
        def __init__(self):
            self.calls = 0

        def send_message(self, *args, **kwargs):
            self.calls += 1
            # LLM returns a /command — deterministic tool execution
            return "/request https://example.com"

    fake_manager = FakeManager()
    monkeypatch.setattr(app, "get_ai_manager", lambda: fake_manager)
    monkeypatch.setattr(
        app,
        "_execute_command_tool",
        lambda cmd_info, session_id=None: tool_markdown,
    )

    profile = Database.get_profile()
    session_id = Database.get_active_session()['id']

    result = app.generate_ai_response(profile, "search for something", "terminal", session_id)

    # Only ONE LLM call — no loop back for second call
    assert fake_manager.calls == 1, f"Expected 1 LLM call (no loop), got {fake_manager.calls}"
    assert "<details>" in result


def test_no_agentic_loop_with_command_detection(monkeypatch):
    """When LLM returns /command, execute it and return — no second LLM call inside generate_ai_response."""
    import app
    from database import Database

    new_session_id = Database.create_session("test-no-loop-cmd")
    Database.switch_session(new_session_id)

    tool_markdown = (
        "<details>\n"
        "<summary>🔧 request_tools</summary>\n"
        "\n```bash\nYuzu$ /request https://api.example.com/data\n```\n\n"
        "> Temperature: 20°C\n\n"
        "</details>"
    )

    class FakeManager:
        def __init__(self):
            self.calls = 0

        def send_message(self, *args, **kwargs):
            self.calls += 1
            return "/request https://api.example.com/data"

    fake_manager = FakeManager()
    monkeypatch.setattr(app, "get_ai_manager", lambda: fake_manager)
    monkeypatch.setattr(
        app,
        "_execute_command_tool",
        lambda cmd_info, session_id=None: tool_markdown,
    )

    profile = Database.get_profile()
    session_id = Database.get_active_session()['id']

    result = app.generate_ai_response(profile, "fetch some data", "terminal", session_id)

    assert fake_manager.calls == 1, f"Expected 1 LLM call, got {fake_manager.calls}"
    assert "<details>" in result


def test_llm_context_only_system_user_assistant(monkeypatch):
    """LLM context must contain only system/user/assistant roles — no *_tools roles."""
    import app
    from database import Database, ALL_TOOL_ROLES
    from tools.registry import build_markdown_contract

    new_session_id = Database.create_session("test-context-roles")
    Database.switch_session(new_session_id)
    session_id = Database.get_active_session()['id']

    # Add messages with tool-specific roles to the DB
    Database.add_message('user', 'fetch data from API', session_id=session_id)
    tool_content = build_markdown_contract(
        "request_tools", "/request https://example.com",
        ["Example docs"], "Yuzu",
    )
    Database.add_message('request_tools', tool_content, session_id=session_id)
    Database.add_message('assistant', 'Here is what I found from the API.', session_id=session_id)

    captured_messages = []

    class FakeManager:
        def send_message(self, *args, **kwargs):
            if args:
                msgs = args[2] if len(args) > 2 else kwargs.get('messages', [])
            else:
                msgs = kwargs.get('messages', [])
            captured_messages.extend(msgs)
            return "response"

    monkeypatch.setattr(app, "get_ai_manager", lambda: FakeManager())

    profile = Database.get_profile()
    app.generate_ai_response(profile, "tell me more", "terminal", session_id)

    # Verify no tool-specific roles in the messages sent to LLM
    for msg in captured_messages:
        assert msg['role'] not in ALL_TOOL_ROLES, \
            f"Tool role '{msg['role']}' leaked into LLM context"
        assert msg['role'] in ('system', 'user', 'assistant'), \
            f"Unexpected role '{msg['role']}' in LLM context"

    # Verify no <details> markup leaked into LLM context
    for msg in captured_messages:
        assert '<details>' not in (msg.get('content') or ''), \
            f"Markdown contract leaked into LLM context: {(msg.get('content') or '')[:80]}"

    # Positive check: tool command must appear as 'assistant' with clean /command
    tool_as_assistant = [
        m for m in captured_messages
        if m['role'] == 'assistant' and '/request' in m.get('content', '')
    ]
    assert len(tool_as_assistant) > 0, \
        "Tool command should appear as 'assistant' role in LLM context"


def test_second_pass_for_non_image_tools(monkeypatch):
    """Non-image tools trigger exactly one second LLM pass via handle_user_message."""
    import app
    from database import Database, get_db_session, Message

    new_session_id = Database.create_session("test-second-pass")
    Database.switch_session(new_session_id)
    session_id = Database.get_active_session()['id']

    tool_markdown = (
        "<details>\n"
        "<summary>🔧 request_tools</summary>\n"
        "\n```bash\nYuzu$ /request https://example.com\n```\n\n"
        "> Example docs\n\n"
        "</details>"
    )

    class FakeManager:
        def __init__(self):
            self.calls = 0

        def send_message(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return "/request https://example.com"
            return "Here's what I found from the API."

    fake_manager = FakeManager()
    monkeypatch.setattr(app, "get_ai_manager", lambda: fake_manager)
    monkeypatch.setattr(
        app,
        "_execute_command_tool",
        lambda cmd_info, session_id=None: tool_markdown,
    )

    reply = app.handle_user_message("fetch data", interface="terminal")

    # Two LLM calls total: initial (returns command) + second pass (natural response)
    assert fake_manager.calls == 2, f"Expected 2 LLM calls, got {fake_manager.calls}"
    assert "Here's what I found from the API." in reply

    # Verify DB state: user, tool, assistant (in order)
    with get_db_session() as session:
        rows = session.query(Message).filter(
            Message.session_id == session_id
        ).order_by(Message.id.asc()).all()
        roles = [m.role for m in rows]

    assert roles == ['user', 'request_tools', 'assistant'], f"Got roles: {roles}"


def test_image_tools_terminal_no_second_pass(monkeypatch):
    """image_tools success is TERMINAL — no second LLM pass."""
    import app
    from database import Database

    new_session_id = Database.create_session("test-image-terminal")
    Database.switch_session(new_session_id)

    image_markdown = (
        "<details>\n"
        '<summary>🔧 image_tools</summary>\n'
        "\n```bash\nYuzu$ /imagine cat\n```\n\n"
        '> <img src="static/generated_images/cat.png">\n\n'
        "</details>"
    )

    class FakeManager:
        def __init__(self):
            self.calls = 0

        def send_message(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return "/imagine cat"
            return "This should not appear"

    fake_manager = FakeManager()
    monkeypatch.setattr(app, "get_ai_manager", lambda: fake_manager)
    monkeypatch.setattr(
        app,
        "_execute_command_tool",
        lambda cmd_info, session_id=None: image_markdown,
    )

    reply = app.handle_user_message("draw a cat", interface="terminal")

    # Only ONE LLM call — image_tools is terminal
    assert fake_manager.calls == 1, f"Expected 1 LLM call (terminal), got {fake_manager.calls}"
    assert "<details>" in reply
    assert "This should not appear" not in reply


def test_pending_user_message_in_context(monkeypatch):
    """User message should appear in LLM context even though it's not yet in DB."""
    import app
    from database import Database

    new_session_id = Database.create_session("test-pending-msg")
    Database.switch_session(new_session_id)

    captured_messages = []

    class FakeManager:
        def send_message(self, *args, **kwargs):
            if args:
                msgs = args[2] if len(args) > 2 else kwargs.get('messages', [])
            else:
                msgs = kwargs.get('messages', [])
            captured_messages.extend(msgs)
            return "Got it!"

    monkeypatch.setattr(app, "get_ai_manager", lambda: FakeManager())

    profile = Database.get_profile()
    session_id = Database.get_active_session()['id']

    app.generate_ai_response(profile, "hello world", "terminal", session_id)

    # The user message should be the last message in context
    user_msgs = [m for m in captured_messages if m['role'] == 'user']
    assert any('hello world' in m.get('content', '') for m in user_msgs), \
        f"User message 'hello world' not found in LLM context: {user_msgs}"


def test_no_tools_kwarg_passed_to_provider(monkeypatch):
    """Provider must never receive a 'tools' kwarg — tool schemas are not injected."""
    import app
    from database import Database

    new_session_id = Database.create_session("test-no-tools-kwarg")
    Database.switch_session(new_session_id)

    captured_kwargs = []

    class FakeManager:
        def send_message(self, *args, **kwargs):
            captured_kwargs.append(dict(kwargs))
            return "Normal response"

    monkeypatch.setattr(app, "get_ai_manager", lambda: FakeManager())

    profile = Database.get_profile()
    session_id = Database.get_active_session()['id']

    app.generate_ai_response(profile, "test message", "terminal", session_id)

    for kw in captured_kwargs:
        assert 'tools' not in kw, f"'tools' kwarg should not be passed to provider, got: {kw}"


def test_provider_always_returns_string(monkeypatch):
    """Provider responses are always strings — no dict/tool_calls handling needed."""
    import app
    from database import Database

    new_session_id = Database.create_session("test-string-response")
    Database.switch_session(new_session_id)

    class FakeManager:
        def send_message(self, *args, **kwargs):
            return "Just a plain string response"

    monkeypatch.setattr(app, "get_ai_manager", lambda: FakeManager())

    profile = Database.get_profile()
    session_id = Database.get_active_session()['id']

    result = app.generate_ai_response(profile, "hello", "terminal", session_id)

    assert isinstance(result, str), f"Expected string response, got {type(result)}"
    assert result == "Just a plain string response"
