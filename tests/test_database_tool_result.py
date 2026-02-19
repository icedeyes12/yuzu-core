"""Test database tool result storage functionality."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_add_tool_result():
    """Test Database.add_tool_result() functionality."""
    from database import Database, Message, get_db_session
    
    print("=== Testing Database Tool Result Storage ===\n")
    
    # Get active session
    active_session = Database.get_active_session()
    session_id = active_session['id']
    
    # Test 1: Add a web_search tool result
    print("Test 1: Add web_search tool result")
    tool_name = "web_search"
    result_content = '{"results": [{"title": "Test", "snippet": "Sample"}]}'
    
    Database.add_tool_result(tool_name, result_content, session_id=session_id)
    
    # Verify it was stored by querying database directly
    with get_db_session() as session:
        messages = session.query(Message).filter(
            Message.session_id == session_id,
            Message.role == 'tool'
        ).all()
        
        assert len(messages) > 0, "No tool messages found in database"
        last_msg = messages[-1]
        assert last_msg.role == 'tool'
        assert "🔧 TOOL RESULT — WEB_SEARCH" in last_msg.content
        assert result_content in last_msg.content
        print("✓ Web search result stored correctly")
    
    # Test 2: Add a memory_sql tool result
    print("\nTest 2: Add memory_sql tool result")
    tool_name = "memory_sql"
    result_content = '{"rows": [{"id": 1, "content": "Test message"}]}'
    
    Database.add_tool_result(tool_name, result_content, session_id=session_id)
    
    # Verify it was stored
    with get_db_session() as session:
        messages = session.query(Message).filter(
            Message.session_id == session_id,
            Message.role == 'tool'
        ).all()
        
        assert len(messages) >= 2, "Not enough tool messages found"
        last_msg = messages[-1]
        assert last_msg.role == 'tool'
        assert "🔧 TOOL RESULT — MEMORY_SQL" in last_msg.content
        assert result_content in last_msg.content
        print("✓ Memory SQL result stored correctly")
    
    # Test 3: Verify formatting
    print("\nTest 3: Verify result formatting")
    with get_db_session() as session:
        tool_messages = session.query(Message).filter(
            Message.session_id == session_id,
            Message.role == 'tool'
        ).all()
        
        assert len(tool_messages) >= 2, "Expected at least 2 tool messages"
        
        for msg in tool_messages:
            assert msg.content.startswith('🔧 TOOL RESULT —'), f"Wrong header: {msg.content[:30]}"
            assert msg.content.endswith('---'), f"Wrong footer: {msg.content[-10:]}"
            print(f"✓ Tool result formatted correctly: {msg.content[:50]}...")
    
    # Test 4: Verify session_id defaults to active session
    print("\nTest 4: Test default session_id behavior")
    Database.add_tool_result("test_tool", '{"test": "data"}')
    
    with get_db_session() as session:
        all_tool_msgs = session.query(Message).filter(
            Message.role == 'tool'
        ).all()
        assert len(all_tool_msgs) >= 3, "Expected at least 3 tool messages"
        print("✓ Default session_id works correctly")
    
    print("\n✅ All database tool result tests passed!")


if __name__ == "__main__":
    try:
        test_add_tool_result()
        print("\n" + "="*50)
        print("✅ DATABASE TOOL RESULT TESTS PASSED")
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
