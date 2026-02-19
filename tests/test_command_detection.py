"""Test command detection and execution for the strict tool command protocol."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_detect_command_valid():
    """Test detection of valid commands on first line."""
    # Import here to avoid database initialization on module load
    from app import _detect_command
    
    # Test simple command
    result = _detect_command("/web_search latest news")
    assert result is not None
    assert result["command"] == "web_search"
    assert result["args"] == "latest news"
    assert result["full_command"] == "/web_search latest news"
    print("✓ Simple command detection works")
    
    # Test command with no args
    result = _detect_command("/image_analyze")
    assert result is not None
    assert result["command"] == "image_analyze"
    assert result["args"] == ""
    print("✓ Command without args detection works")
    
    # Test multi-line command (memory_sql)
    sql_text = "/memory_sql\nSELECT * FROM messages"
    result = _detect_command(sql_text)
    assert result is not None
    assert result["command"] == "memory_sql"
    assert "SELECT * FROM messages" in result["remaining_text"]
    print("✓ Multi-line command detection works")


def test_detect_command_invalid():
    """Test rejection of invalid command formats."""
    from app import _detect_command
    
    # Test command not on first line
    result = _detect_command("Let me search.\n/web_search news")
    assert result is None
    print("✓ Command not on first line correctly rejected")
    
    # Test command with text before it
    result = _detect_command("Sure! /web_search news")
    assert result is None
    print("✓ Command with text before correctly rejected")
    
    # Test text starting with slash but not a command
    result = _detect_command("Sure, I'll help you /search for that")
    assert result is None
    print("✓ Text with slash in middle correctly rejected")
    
    # Test empty input
    result = _detect_command("")
    assert result is None
    print("✓ Empty input correctly rejected")
    
    # Test None input
    result = _detect_command(None)
    assert result is None
    print("✓ None input correctly rejected")


def test_command_parsing():
    """Test parsing of different command formats."""
    from app import _detect_command
    
    # /imagine command
    result = _detect_command("/imagine a beautiful sunset")
    assert result["command"] == "imagine"
    assert result["args"] == "a beautiful sunset"
    print("✓ /imagine command parsing works")
    
    # /weather command
    result = _detect_command("/weather Tokyo")
    assert result["command"] == "weather"
    assert result["args"] == "Tokyo"
    print("✓ /weather command parsing works")
    
    # /memory_search command
    result = _detect_command("/memory_search last week conversation")
    assert result["command"] == "memory_search"
    assert result["args"] == "last week conversation"
    print("✓ /memory_search command parsing works")


if __name__ == "__main__":
    print("=== Testing Command Detection ===\n")
    
    try:
        test_detect_command_valid()
        print()
        test_detect_command_invalid()
        print()
        test_command_parsing()
        print("\n✅ All command detection tests passed!")
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

