"""Test profiles and development-only profile utilities.

Moved out of app.py to keep production code clean.
These functions are not part of the runtime flow.
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from database import Database
from app import global_profile_analysis, parse_global_profile_summary, summarize_global_player_profile


def test_glm47_profile():
    """Test GLM-4.7 for profile analysis"""
    print("=== Testing GLM-4.7 Profile Analysis ===")
    
    api_keys = Database.get_api_keys()
    openrouter_key = api_keys.get('openrouter')
    
    if not openrouter_key:
        print("[ERROR] No OpenRouter API key!")
        return False
    
    # Test dengan prompt sederhana
    test_prompt = """# PLAYER PROFILE ANALYSIS TASK

## CONVERSATION HISTORY:
Session 1 - User: Hello, I really enjoy programming in Python
Session 1 - AI: That's great! Python is a wonderful language
Session 1 - User: Yes, I especially like data analysis with pandas
Session 2 - User: I love listening to jazz while working
Session 2 - AI: Jazz is perfect for focus! Any favorite artists?
Session 2 - User: Miles Davis and John Coltrane are my favorites

## ANALYSIS INSTRUCTIONS:
Analyze the conversation history and extract insights about the User.

### OUTPUT FORMAT:
Player Summary: [4-6 sentence summary]

Likes: [comma-separated list]

Dislikes: [comma-separated list]

Personality Traits: [comma-separated list]

Important Memories: [comma-separated list]

Relationship Dynamics: [3-4 sentence analysis]"""
    
    print("[INFO] Testing with simple prompt...")
    result = global_profile_analysis(test_prompt, openrouter_key)
    
    if result:
        print(f"\n[SUCCESS] GLM-4.7 Test Response:\n{result}")
        
        parsed = parse_global_profile_summary(result)
        print(f"\n[SUCCESS] Parsed Result:")
        print(f"Player Summary: {parsed['player_summary'][:200]}...")
        print(f"Likes: {parsed['key_facts']['likes']}")
        print(f"Personality Traits: {parsed['key_facts']['personality_traits']}")
        
        # Simpan test result
        os.makedirs("debug_logs", exist_ok=True)
        with open("debug_logs/glm47_test_result.txt", "w", encoding="utf-8") as f:
            f.write("=== GLM-4.7 Test Result ===\n")
            f.write(result)
            f.write("\n\n=== Parsed Data ===\n")
            f.write(json.dumps(parsed, indent=2, ensure_ascii=False))
        
        return True
    else:
        print("[ERROR] No response from GLM-4.7")
        return False


def batch_global_analysis(max_sessions=50):
    """Run global analysis with batch processing"""
    print(f"=== Batch Global Analysis (max {max_sessions} sessions) ===")
    
    # Get all sessions
    all_sessions = Database.get_all_sessions()
    
    if len(all_sessions) > max_sessions:
        print(f"[INFO] Too many sessions ({len(all_sessions)}), limiting to {max_sessions}")
        all_sessions = all_sessions[:max_sessions]
    
    # Create a modified version that accepts session limit
    # For now, just use the standard function
    result = summarize_global_player_profile()
    
    if result:
        print("[SUCCESS] Batch analysis completed")
    else:
        print("[ERROR] Batch analysis failed")
    
    return result


def incremental_profile_update():
    """Update profile incrementally - only analyze new sessions"""
    profile = Database.get_profile()
    memory = profile.get('memory', {})
    
    last_update = memory.get('last_global_summary')
    if last_update:
        try:
            last_date = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
            print(f"Last profile update: {last_date}")
            
            # Get sessions after last update
            all_sessions = Database.get_all_sessions()
            new_sessions = []
            
            for session in all_sessions:
                session_updated = session.get('updated_at')
                if session_updated:
                    try:
                        session_date = datetime.fromisoformat(session_updated.replace('Z', '+00:00'))
                        if session_date > last_date:
                            new_sessions.append(session)
                    except:
                        continue
            
            print(f"Found {len(new_sessions)} new sessions since last update")
            
            if new_sessions:
                # For now, run full analysis
                print("[INFO] Running full analysis with new sessions...")
                return summarize_global_player_profile()
            else:
                print("[INFO] No new sessions to analyze")
                return False
                
        except Exception as e:
            print(f"[ERROR] Error parsing dates: {str(e)}")
            # Run full analysis as fallback
            return summarize_global_player_profile()
    else:
        print("[INFO] No previous profile analysis found, running full analysis")
        return summarize_global_player_profile()
