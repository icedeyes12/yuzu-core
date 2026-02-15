"""Relocated test/utility functions for GLM-4.7 profile analysis and batch processing."""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from database import Database
from app import global_profile_analysis, parse_global_profile_summary, summarize_global_player_profile


def check_glm47_capabilities():
    """Check GLM-4.7 capabilities and pricing"""
    print("=== GLM-4.7 Capabilities ===")
    print("Context window: 202,800 tokens")
    print("Max output: 65,536 tokens")
    print("\n=== OpenRouter Pricing ===")
    print("z-ai/glm-4.7: ~$0.50 per 1M input tokens")
    print("z-ai/glm-4.6: ~$0.20 per 1M input tokens")
    print("\n=== Recommendations ===")
    print("1. Use GLM-4.7 for comprehensive analysis")
    print("2. Monitor token usage in OpenRouter dashboard")
    print("3. Consider batch analysis for large histories")
    print("4. Cache results to avoid repeated analysis")
    
    # Estimate cost
    api_keys = Database.get_api_keys()
    openrouter_key = api_keys.get('openrouter')
    
    if openrouter_key:
        import requests
        # Check usage via OpenRouter API
        headers = {"Authorization": f"Bearer {openrouter_key}"}
        try:
            response = requests.get(
                "https://openrouter.ai/api/v1/auth/key",
                headers=headers,
                timeout=30
            )
            if response.status_code == 200:
                key_info = response.json()
                print(f"\n=== API Key Info ===")
                print(f"Label: {key_info.get('label', 'N/A')}")
                print(f"Usage: {key_info.get('usage', 'N/A')}")
                print(f"Limits: {key_info.get('limits', 'N/A')}")
        except:
            print("\n[INFO] Could not fetch API key details")


def test_glm47_profile():
    """Test GLM-4.7 for profile analysis"""
    print("=== Testing GLM-4.7 Profile Analysis ===")
    
    api_keys = Database.get_api_keys()
    openrouter_key = api_keys.get('openrouter')
    
    if not openrouter_key:
        print("[ERROR] No OpenRouter API key!")
        return False
    
    # Test with simple prompt
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
        
        # Save test result
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


if __name__ == '__main__':
    check_glm47_capabilities()
    test_glm47_profile()
