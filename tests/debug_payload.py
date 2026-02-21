# ==========================================================
# [FILE]        : debugl_payload.py
# [LOCATION]    : /tests/debug_payload.py
# [VERSION]     : 1.0.0
# [DESCRIPTION] : Standalone - Dump COMPLETE payload to debug_logs
# ==========================================================

import sys
import os
import json
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database import Database
from app import _build_generation_context

# Create debug_logs folder if it doesn't exist
DEBUG_LOGS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'debug_logs'))
os.makedirs(DEBUG_LOGS_DIR, exist_ok=True)

def dump_complete_payload(user_message: str, session_id: str = None, interface: str = "web"):
    """
    Dump COMPLETE payload to files in debug_logs/
    Returns dict with file paths
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_filename = f"payload_dump_{timestamp}"
    
    print("\n" + "="*80)
    print("📦 COMPLETE PAYLOAD DUMPER")
    print("="*80)
    
    # Get profile and session
    profile = Database.get_profile()
    if session_id is None:
        active_session = Database.get_active_session()
        session_id = active_session['id']
    
    print(f"📋 Session: {active_session.get('name', 'Unnamed')} ({session_id})")
    print(f"📋 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Build messages
    print("🔄 Building message context...")
    messages = _build_generation_context(profile, session_id, interface)
    
    # Append user message
    if user_message and user_message.strip():
        messages.append({"role": "user", "content": user_message})
    
    # Get provider info
    providers_config = profile.get('providers_config', {})
    preferred_provider = providers_config.get('preferred_provider', 'ollama')
    preferred_model = providers_config.get('preferred_model', 'glm-4.6:cloud')
    
    # Prepare complete data
    complete_data = {
        "dump_info": {
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id,
            "session_name": active_session.get('name', 'Unnamed'),
            "interface": interface,
            "user_message": user_message,
            "provider": preferred_provider,
            "model": preferred_model,
            "total_messages": len(messages)
        },
        "messages": messages,
        "provider_config": providers_config,
        "profile_snapshot": {
            "display_name": profile.get('display_name'),
            "partner_name": profile.get('partner_name'),
            "affection": profile.get('affection'),
            "memory_summary": profile.get('memory', {}).get('player_summary', '')[:500] + "..." if len(profile.get('memory', {}).get('player_summary', '')) > 500 else profile.get('memory', {}).get('player_summary', '')
        }
    }
    
    # File 1: Complete JSON dump
    json_path = os.path.join(DEBUG_LOGS_DIR, f"{base_filename}_full.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(complete_data, f, indent=2, ensure_ascii=False)
    print(f"✅ JSON dump: {json_path}")
    
    # File 2: Extracted text version (markdown format)
    md_path = os.path.join(DEBUG_LOGS_DIR, f"{base_filename}_extracted.md")
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(generate_markdown_dump(complete_data))
    print(f"✅ Markdown dump: {md_path}")
    
    # File 3: Raw system message only (txt)
    system_path = os.path.join(DEBUG_LOGS_DIR, f"{base_filename}_system.txt")
    system_msg = next((msg["content"] for msg in messages if msg["role"] == "system"), "")
    with open(system_path, 'w', encoding='utf-8') as f:
        f.write(system_msg)
    print(f"✅ System message: {system_path}")
    
    # Also print system message to console
    print("\n" + "="*80)
    print("🤖 SYSTEM MESSAGE (FULL):")
    print("="*80)
    print(system_msg)
    print("="*80)
    print(f"📊 System message length: {len(system_msg)} characters")
    
    return {
        "json": json_path,
        "markdown": md_path,
        "system": system_path,
        "messages": messages,
        "system_content": system_msg
    }

def generate_markdown_dump(data):
    """Generate human-readable markdown version"""
    lines = []
    
    # Header
    lines.append("# 🚀 COMPLETE LLM PAYLOAD DUMP")
    lines.append(f"\n**Generated:** {data['dump_info']['timestamp']}")
    lines.append(f"**Session:** {data['dump_info']['session_name']} (`{data['dump_info']['session_id']}`)")
    lines.append(f"**Interface:** {data['dump_info']['interface']}")
    lines.append(f"**Provider/Model:** {data['dump_info']['provider']} / {data['dump_info']['model']}")
    lines.append(f"**Total Messages:** {data['dump_info']['total_messages']}")
    lines.append(f"**User Message:** `{data['dump_info']['user_message']}`")
    
    # Profile snapshot
    lines.append("\n## 👤 Profile Snapshot")
    lines.append(f"- Display Name: {data['profile_snapshot']['display_name']}")
    lines.append(f"- Partner Name: {data['profile_snapshot']['partner_name']}")
    lines.append(f"- Affection: {data['profile_snapshot']['affection']}")
    lines.append(f"- Memory Summary: {data['profile_snapshot']['memory_summary']}")
    
    # Messages
    lines.append("\n## 📨 Complete Message List")
    
    for i, msg in enumerate(data['messages']):
        lines.append(f"\n### [{i}] Role: `{msg['role']}`")
        lines.append("---")
        
        content = msg['content']
        if isinstance(content, str):
            # Plain text
            lines.append("```text")
            lines.append(content)
            lines.append("```")
            lines.append(f"*Length: {len(content)} characters*")
        elif isinstance(content, list):
            # Multimodal
            lines.append("**MULTIMODAL CONTENT:**")
            for j, part in enumerate(content):
                if part['type'] == 'text':
                    lines.append(f"\n**Text Part {j}:**")
                    lines.append("```text")
                    lines.append(part['text'])
                    lines.append("```")
                elif part['type'] == 'image_url':
                    url = part['image_url']['url']
                    if url.startswith('data:image'):
                        lines.append(f"\n**Image Part {j}:** `[base64 image data]`")
                        lines.append(f"Preview: {url[:100]}...")
                    else:
                        lines.append(f"\n**Image Part {j}:** {url}")
    
    # Stats
    total_chars = sum(
        len(c) if isinstance(c, str) 
        else sum(len(p.get('text', '')) for p in c if p['type'] == 'text')
        for c in [m['content'] for m in data['messages']]
    )
    
    lines.append("\n## 📊 Statistics")
    lines.append(f"- Total characters: {total_chars:,}")
    lines.append(f"- Estimated tokens: ~{total_chars // 4:,}")
    lines.append(f"- JSON size: ~{len(json.dumps(data)) // 1024} KB")
    
    return "\n".join(lines)

def quick_verify_truncation():
    """Check if system message might be truncated by terminal"""
    profile = Database.get_profile()
    session = Database.get_active_session()
    messages = _build_generation_context(profile, session['id'], "web")
    
    system_msg = next((msg["content"] for msg in messages if msg["role"] == "system"), "")
    
    print("\n" + "="*80)
    print("🔍 SYSTEM MESSAGE VERIFICATION")
    print("="*80)
    print(f"Full length: {len(system_msg)} characters")
    print(f"Preview (first 500 chars):")
    print("-"*40)
    print(system_msg[:500])
    print("-"*40)
    print(f"... and {len(system_msg)-500} more characters")
    
    # Check for truncation indicators
    if len(system_msg) > 1000:
        print("\n⚠️  System message is LONG (>1000 chars)")
        print("   Terminal might truncate it. Use the dumped files to see full content.")
    
    return system_msg

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════╗
║     COMPLETE PAYLOAD DUMPER - STANDALONE MODE            ║
║     Dumps to: /debug_logs/                               ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    if len(sys.argv) > 1:
        user_message = " ".join(sys.argv[1:])
        
        print("\nPilih mode:")
        print("1. Dump complete payload (JSON + MD + TXT)")
        print("2. Just verify system message length")
        print("3. Dump with custom session")
        
        choice = input("Pilihan (1/2/3) [1]: ").strip() or "1"
        
        if choice == "2":
            quick_verify_truncation()
        elif choice == "3":
            # List available sessions
            sessions = Database.get_all_sessions()
            print("\nAvailable sessions:")
            for i, s in enumerate(sessions[:5]):  # Show first 5
                print(f"{i}. {s.get('name', 'Unnamed')} ({s['id']})")
            
            sess_idx = input("Pilih session index (enter untuk active): ").strip()
            if sess_idx and sess_idx.isdigit() and int(sess_idx) < len(sessions):
                session_id = sessions[int(sess_idx)]['id']
                dump_complete_payload(user_message, session_id=session_id)
            else:
                dump_complete_payload(user_message)
        else:
            dump_complete_payload(user_message)
    else:
        # Demo mode - use default message
        print("No message provided. Using default test message.")
        result = dump_complete_payload("Test message - hello world!")
        print(f"\n📁 Files saved to debug_logs/")
        print(f"   📄 JSON: {os.path.basename(result['json'])}")
        print(f"   📄 Markdown: {os.path.basename(result['markdown'])}")
        print(f"   📄 System: {os.path.basename(result['system'])}")