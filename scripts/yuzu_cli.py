#!/usr/bin/env python3
"""
Simple CLI to chat with yuzu-companion.
Usage:
    yuzu "hai apa kabar"           # send message, show reply
    yuzu -h 10                      # show last 10 messages
    yuzu -s 37 "hai"                # use specific session (default: 37)
"""

import argparse
import requests

DEFAULT_URL = "http://localhost:5000"
DEFAULT_SESSION = 37
DEFAULT_TIMEOUT_GET = 10
DEFAULT_TIMEOUT_POST = 120


def get_history(session_id: int, limit: int = 20, url: str = DEFAULT_URL, timeout: int = DEFAULT_TIMEOUT_GET) -> list[dict]:
    """Get last N messages from session."""
    # Switch to session first, then get profile (which includes history)
    requests.post(f"{url}/api/sessions/switch", json={"session_id": session_id}, timeout=timeout)
    resp = requests.get(f"{url}/api/get_profile", timeout=timeout)
    data = resp.json()
    history = data.get("chat_history", [])
    # Filter out system messages first, then apply limit
    history = [m for m in history if m.get("role") != "system"]
    return history[-limit:] if limit else history


def send_message(session_id: int, message: str, url: str = DEFAULT_URL, 
                 signature: str = "", timeout: int = DEFAULT_TIMEOUT_POST,
                 interface: str = "Maintenance Terminal") -> str:
    """Send message to yuzu-companion."""
    # Prepend signature if provided
    if signature:
        message = f"[{signature}] {message}"
    
    # Switch session first
    requests.post(f"{url}/api/sessions/switch", json={"session_id": session_id}, timeout=timeout)
    
    # Send message with interface
    payload = {
        "message": message,
        "interface": interface
    }
    
    resp = requests.post(
        f"{url}/api/send_message",
        json=payload,
        timeout=timeout
    )
    data = resp.json()
    return data.get("reply", "(no reply)")


def format_history(history: list[dict], max_len: int = 0) -> str:
    """Format history for display. max_len=0 means no truncation."""
    lines = []
    for msg in history:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        # Skip system messages (connection notifications, etc)
        if role == "system":
            continue
        if max_len > 0 and len(content) > max_len:
            content = content[:max_len] + "..."
        lines.append(f"[{role}] {content}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Chat with yuzu-companion")
    parser.add_argument("message", nargs="?", help="Message to send")
    parser.add_argument("-s", "--session", type=int, default=DEFAULT_SESSION, help="Session ID")
    parser.add_argument("-H", "--history", type=int, metavar="N", help="Show last N messages")
    parser.add_argument("-u", "--url", default=DEFAULT_URL, help="API URL")
    parser.add_argument("--sig", "--signature", dest="signature", default="", help="Add [signature] prefix to message")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_GET, help="Timeout for GET requests (history)")
    parser.add_argument("--post-timeout", type=int, default=DEFAULT_TIMEOUT_POST, help="Timeout for POST requests (send message)")
    args = parser.parse_args()

    # Show history mode
    if args.history:
        history = get_history(args.session, args.history, args.url, args.timeout)
        if not history:
            print("(no history)")
            return
        print(format_history(history))  # no truncation
        return

    # Send message mode
    if args.message:
        # Show last 5 messages for context first
        history = get_history(args.session, 5, args.url, args.timeout)
        if history:
            print("=== Last 5 messages ===")
            print(format_history(history))  # no truncation
            print()

        # Send message
        sig_display = f"[{args.signature}] " if args.signature else ""
        print(f"=== Sending to session {args.session} ===")
        print(f"[user] {sig_display}{args.message}")
        print()

        reply = send_message(args.session, args.message, args.url, args.signature, args.post_timeout)
        print(f"[yuzu] {reply}")
        return

    # No args - show help
    parser.print_help()


if __name__ == "__main__":
    main()
