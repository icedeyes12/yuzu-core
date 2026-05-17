from __future__ import annotations
# FILE: app/tools/ask_rei.py
# DESCRIPTION: Tool for Yuzuki to send messages to Reina via Zo ASK API


import logging
import os
import requests
from datetime import datetime
from app.tools.schemas import ToolDefinition, ToolParam, ok_result, error_result

logger = logging.getLogger(__name__)

# Default conversation ID for Reina's session
DEFAULT_CONVERSATION_ID = "con_JC2FyZFrYEoag76X"

# Zo ASK API endpoint
ZO_ASK_URL = "https://api.zo.computer/zo/ask"

# Request timeout
TIMEOUT = 120


TOOL_DEFINITION = ToolDefinition(
    name="ask_rei",
    description="Send a message to Reina (AI co-developer) via Zo ASK API. "
                "Use this to communicate with Reina who operates in a separate Zo session. "
                "Returns Reina's response. "
                "Format: /ask-rei [--id <conversation_id>] \"<message>\"",
    role="ask_rei_tools",
    parameters=[
        ToolParam(
            name="message",
            description="The message to send to Reina",
            type="string",
            required=True,
        ),
        ToolParam(
            name="conversation_id",
            description="Target conversation ID (optional, defaults to Reina's session)",
            type="string",
            required=False,
            default=DEFAULT_CONVERSATION_ID,
        ),
    ],
    is_terminal=True,
)


def _get_zo_api_key() -> str | None:
    """Get ZO_API_KEY from environment."""
    return os.environ.get("ZO_API_KEY")


def _build_yuzuki_signature() -> str:
    """Build signature for Yuzuki's messages to Reina."""
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return f'[Yuzuki via /ask-rei] {{\"signature\":{{\"identity\":\"yuzuki\",\"timestamp\":\"{timestamp}\"}}}}'


def _parse_args(args_str: str) -> dict:
    """Parse /ask-rei arguments.
    
    Supports:
    - /ask-rei "message"
    - /ask-rei --id con_XXX "message"
    
    Returns dict with 'message' and optional 'conversation_id'.
    """
    args_str = args_str.strip()
    
    result = {"conversation_id": DEFAULT_CONVERSATION_ID}
    
    # Check for --id flag
    if args_str.startswith("--id "):
        parts = args_str.split(None, 2)
        if len(parts) >= 2:
            result["conversation_id"] = parts[1]
            if len(parts) >= 3:
                result["message"] = parts[2].strip('"\'')
            else:
                result["message"] = ""
            return result
    
    # No --id flag, treat entire string as message
    result["message"] = args_str.strip('"\'')
    return result


def execute(arguments, **kwargs):
    """Execute the /ask-rei tool.
    
    Sends a message to Reina via Zo ASK API and returns her response.
    """
    from app.database import get_profile
    
    profile = get_profile() or {}
    partner_name = profile.get("partner_name", "Yuzu")
    
    # Parse arguments
    if isinstance(arguments, dict):
        parsed = _parse_args(arguments.get("message", ""))
        message = parsed.get("message", "")
        conversation_id = parsed.get("conversation_id", DEFAULT_CONVERSATION_ID)
    else:
        parsed = _parse_args(str(arguments))
        message = parsed.get("message", "")
        conversation_id = parsed.get("conversation_id", DEFAULT_CONVERSATION_ID)
    
    full_command = f'/ask-rei --id {conversation_id} "{message}"'
    
    if not message:
        return error_result(
            "No message provided",
            TOOL_DEFINITION,
            "/ask-rei",
            partner_name,
        )
    
    # Get API key
    api_key = _get_zo_api_key()
    if not api_key:
        return error_result(
            "ZO_API_KEY not configured. Please set ZO_API_KEY environment variable.",
            TOOL_DEFINITION,
            full_command,
            partner_name,
        )
    
    # Build message with Yuzuki signature
    signature = _build_yuzuki_signature()
    full_message = f"{message}\n\n{signature}"
    
    # Call Zo ASK API
    try:
        response = requests.post(
            ZO_ASK_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "input": full_message,
                "conversation_id": conversation_id,
            },
            timeout=TIMEOUT,
        )
        
        if response.status_code != 200:
            logger.warning(f"[ask_rei] API error {response.status_code}: {response.text[:200]}")
            return error_result(
                f"Zo API error: {response.status_code}",
                TOOL_DEFINITION,
                full_command,
                partner_name,
            )
        
        data = response.json()
        output = data.get("output", "")
        
        # Check if output is empty
        if not output or not output.strip():
            return ok_result(
                {
                    "status": "sent",
                    "conversation_id": conversation_id,
                    "response": "(No response from Reina)",
                },
                TOOL_DEFINITION,
                full_command,
                partner_name,
            )
        
        return ok_result(
            {
                "status": "delivered",
                "conversation_id": conversation_id,
                "response": output,
            },
            TOOL_DEFINITION,
            full_command,
            partner_name,
        )
        
    except requests.exceptions.Timeout:
        logger.warning("[ask_rei] Request timed out")
        return error_result(
            "Request timed out. Reina may be busy.",
            TOOL_DEFINITION,
            full_command,
            partner_name,
        )
    except Exception as e:
        logger.warning(f"[ask_rei] Exception: {e}")
        return error_result(
            f"Failed to reach Reina: {str(e)[:100]}",
            TOOL_DEFINITION,
            full_command,
            partner_name,
        )
