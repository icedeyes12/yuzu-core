"""Test database tool result storage functionality."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_add_tool_result():
    """Test Database.add_tool_result() functionality with tool-specific roles."""
    from database import Database, Message, get_db_session, TOOL_ROLES
    from tools.registry import build_markdown_contract
    
    print("=== Testing Database Tool Result Storage ===\n")
    
    # Get active session
    active_session = Database.get_active_session()
    session_id = active_session['id']
    
    # Test 1: Add a request tool result — should use 'request_tools' role
    print("Test 1: Add request tool result")
    tool_name = "request"
    result_content = build_markdown_contract(
        "request_tools", "/request https://example.com",
        ["[Test](http://example.com)", "  Sample snippet"],
        "Yuzu",
    )
    
    Database.add_tool_result(tool_name, result_content, session_id=session_id)
    
    # Verify it was stored with tool-specific role
    with get_db_session() as session:
        messages = session.query(Message).filter(
            Message.session_id == session_id,
            Message.role == 'request_tools'
        ).all()
        
        assert len(messages) > 0, "No request_tools messages found in database"
        last_msg = messages[-1]
        assert last_msg.role == 'request_tools'
        assert "<details>" in last_msg.content
        assert "🔧 request_tools" in last_msg.content
        print("✓ Request result stored with role 'request_tools'")
    
    # Test 2: Add an image_generate tool result — should use 'image_tools' role
    print("\nTest 2: Add image_generate tool result")
    tool_name = "image_generate"
    result_content = build_markdown_contract(
        "image_tools", "/imagine sunset",
        ['<img src="static/generated_images/sunset.png">'],
        "Yuzu",
    )
    
    Database.add_tool_result(tool_name, result_content, session_id=session_id)
    
    # Verify it was stored with correct role
    with get_db_session() as session:
        messages = session.query(Message).filter(
            Message.session_id == session_id,
            Message.role == 'image_tools'
        ).all()
        
        assert len(messages) > 0, "No image_tools messages found"
        last_msg = messages[-1]
        assert last_msg.role == 'image_tools'
        assert "<details>" in last_msg.content
        assert "🔧 image_tools" in last_msg.content
        print("✓ Image generate result stored with role 'image_tools'")
    
    # Test 3: Verify formatting — all tool messages start with <details>
    print("\nTest 3: Verify result formatting")
    with get_db_session() as session:
        tool_messages = session.query(Message).filter(
            Message.session_id == session_id,
            Message.role.in_(list(TOOL_ROLES.values()))
        ).all()
        
        assert len(tool_messages) >= 2, "Expected at least 2 tool messages"
        
        for msg in tool_messages:
            assert msg.content.strip().startswith('<details>'), f"Wrong format: {msg.content[:30]}"
            assert msg.content.strip().endswith('</details>'), f"Wrong end: {msg.content[-20:]}"
            print(f"✓ Tool result formatted correctly: {msg.content[:50]}...")
    
    # Test 4: Verify session_id defaults to active session
    print("\nTest 4: Test default session_id behavior")
    fallback_content = build_markdown_contract(
        "test_tool_tools", "/test_tool data",
        ["test data"],
        "Yuzu",
    )
    Database.add_tool_result("test_tool", fallback_content)
    
    with get_db_session() as session:
        all_tool_msgs = session.query(Message).filter(
            Message.role == 'test_tool_tools'
        ).all()
        assert len(all_tool_msgs) >= 1, "Expected at least 1 test_tool_tools message"
        print("✓ Default session_id works correctly and unknown tools get fallback role")
    
    print("\n✅ All database tool result tests passed!")


def test_tool_role_mapping():
    """Test that TOOL_ROLES mapping is correct and complete."""
    from database import TOOL_ROLES, ALL_TOOL_ROLES
    
    print("=== Testing Tool Role Mapping ===\n")
    
    # Verify all required tools have roles
    required_tools = ['image_generate', 'imagine', 'request']
    
    for tool in required_tools:
        assert tool in TOOL_ROLES, f"Tool '{tool}' missing from TOOL_ROLES"
        print(f"✓ {tool} → {TOOL_ROLES[tool]}")
    
    # Verify expected role names
    assert TOOL_ROLES['image_generate'] == 'image_tools'
    assert TOOL_ROLES['imagine'] == 'image_tools'
    assert TOOL_ROLES['request'] == 'request_tools'
    
    # Verify removed tools are not present
    assert 'web_search' not in TOOL_ROLES
    assert 'weather' not in TOOL_ROLES
    assert 'image_analyze' not in TOOL_ROLES
    assert 'memory_sql' not in TOOL_ROLES
    assert 'memory_search' not in TOOL_ROLES
    
    # Verify ALL_TOOL_ROLES contains all values
    assert set(ALL_TOOL_ROLES) == set(TOOL_ROLES.values())
    print(f"\n✓ ALL_TOOL_ROLES contains {len(ALL_TOOL_ROLES)} roles")
    
    print("\n✅ Tool role mapping test passed!")


def test_tool_results_in_chat_history():
    """Test that tool results are included in chat history for rendering."""
    from database import Database, Message, get_db_session, TOOL_ROLES
    from tools.registry import build_markdown_contract
    
    print("=== Testing Tool Results in Chat History ===\n")
    
    active_session = Database.get_active_session()
    session_id = active_session['id']
    
    # Add a tool result
    content = build_markdown_contract(
        "request_tools", "/request https://example.com",
        ["Response: OK"],
        "Yuzu",
    )
    Database.add_tool_result("request", content, session_id=session_id)
    
    # Verify it appears in get_chat_history (used for rendering)
    history = Database.get_chat_history(session_id=session_id)
    tool_msgs = [m for m in history if m['role'] == 'request_tools']
    assert len(tool_msgs) > 0, "Request tool result not in get_chat_history"
    print("✓ Tool results included in get_chat_history (rendering)")
    
    # Verify it appears in get_chat_history_for_ai (used for context builder)
    ai_history = Database.get_chat_history_for_ai(session_id=session_id)
    ai_tool_msgs = [m for m in ai_history if m['role'] == 'request_tools']
    assert len(ai_tool_msgs) > 0, "Request tool result not in get_chat_history_for_ai"
    print("✓ Tool results included in get_chat_history_for_ai (context builder)")
    
    print("\n✅ Tool results in chat history test passed!")


def test_context_builder_maps_tool_roles():
    """Test that _build_generation_context maps tool roles to 'assistant' for LLM API."""
    from database import Database, ALL_TOOL_ROLES
    from tools.registry import build_markdown_contract
    
    print("=== Testing Context Builder Tool Role Mapping ===\n")
    
    active_session = Database.get_active_session()
    session_id = active_session['id']
    
    # Add a tool result so it's in the DB
    content = build_markdown_contract(
        "request_tools", "/request https://test-unique-url.example.org/data",
        ["No results"],
        "Yuzu",
    )
    Database.add_tool_result("request", content, session_id=session_id)
    
    # Import and call the context builder
    from app import _build_generation_context
    profile = Database.get_profile()
    messages = _build_generation_context(profile, session_id, "terminal")
    
    # Verify no tool-specific roles leaked through to LLM messages
    for msg in messages:
        assert msg['role'] not in ALL_TOOL_ROLES, \
            f"Tool-specific role '{msg['role']}' leaked into LLM messages"
    
    # Verify tool results are present as 'assistant' role with clean /command (no <details> markup)
    tool_command_found = False
    for msg in messages:
        content = msg.get('content', '')
        # No <details> markup should leak into LLM context
        assert '<details>' not in content, \
            f"Markdown contract leaked into LLM context: {(content or '')[:80]}"
        # The original /command should appear as 'assistant'
        if '/request https://test-unique-url.example.org/data' in content:
            assert msg['role'] == 'assistant', \
                f"Tool command should have role 'assistant' for LLM, got '{msg['role']}'"
            tool_command_found = True
    
    assert tool_command_found, "Tool command not found in context builder output"
    print("✓ Tool roles correctly mapped to 'assistant' with clean /command in context builder")
    
    print("\n✅ Context builder tool role mapping test passed!")


if __name__ == "__main__":
    try:
        test_add_tool_result()
        test_tool_role_mapping()
        test_tool_results_in_chat_history()
        test_context_builder_maps_tool_roles()
        print("\n" + "="*50)
        print("✅ ALL DATABASE TOOL RESULT TESTS PASSED")
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
