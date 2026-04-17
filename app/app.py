# FILE: app/app.py
# DESCRIPTION: Main application entrypoint

import requests
import os
import re
import json
import traceback
from datetime import datetime
from typing import Dict, Optional, List
from app.database import Database
from app.providers import get_ai_manager, reload_ai_manager
from app.tools import multimodal_tools
from app.tools.registry import execute_tool, get_tool_role, get_tool_definitions

from app.memory.memory import trigger_memory_pipeline_async
from app.visual_context import (
    store_visual_context as _store_visual_context,
    consume_visual_context as _consume_visual_context,
    has_visual_reference as _has_visual_reference,
)
def _parse_image_result_from_formatted(formatted_result):
    """
    Parse image path from formatted tool result.
    
    Args:
        formatted_result: Formatted tool result string with header
    
    Returns:
        str: Image path if found, None otherwise
    """
    try:
        # Extract image src from markdown contract
        import re
        m = re.search(r'src="(static/generated_images/[^"]+)"', formatted_result)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None

def _load_generated_image_base64(img_path):
    """Load a generated image and return base64 + mime for vision model."""
    try:
        import base64
        if not os.path.exists(img_path):
            print(f"[Vision2nd] Image file not found: {img_path}")
            return None, None
        with open(img_path, 'rb') as f:
            img_data = f.read()
        mime_type = 'image/png' if img_path.endswith('.png') else 'image/jpeg'
        img_b64 = base64.b64encode(img_data).decode('utf-8')
        return img_b64, mime_type
    except Exception as e:
        print(f"[Vision2nd] Failed to load image: {e}")
        return None, None


def _detect_command(response_text):
    """
    Detect if the response starts with a tool command on the first line.
    
    Returns:
        dict: {"command": str, "args": str, "full_command": str} if command detected
        None: if no command on first line or invalid format
    """
    if not response_text or not response_text.strip():
        return None
    
    # Split into lines
    lines = response_text.split('\n')
    first_line = lines[0].strip()
    
    # Check if first line starts with /
    if not first_line.startswith('/'):
        return None
    
    # Parse command
    parts = first_line.split(None, 1)  # Split on first whitespace
    command = parts[0]  # e.g., "/request"
    args = parts[1] if len(parts) > 1 else ""
    
    # Extract tool name (remove /)
    tool_name = command[1:]  # Remove leading /
    
    return {
        "command": tool_name,
        "args": args,
        "full_command": first_line
    }

# ----------------------------------------------------------------------
# Guard: detect when model tries to shortcut image generation by
# directly outputting a markdown image instead of calling /imagine.
# Pattern: ![alt](static/.../something.png) or ![alt](uploads/...)
# This is NOT the same as a tool contract — it's raw text output.
# ----------------------------------------------------------------------
def _is_model_using_markdown_image_shortcut(response_text):
    """Detect if model is outputting markdown image syntax instead of /imagine tool call."""
    if not response_text:
        return False
    # Match markdown image syntax that points to local generated/uploaded images
    # Exclude tool contracts (which use <details>) and URLs (external images)
    import re
    md_img_pattern = re.compile(r'!\[[^\]]*\]\((static/|uploads/|generated_images/)[^)]+\)')
    return bool(md_img_pattern.search(response_text))

def _extract_prompt_from_markdown_image(response_text):
    """If model outputs a markdown image shortcut, extract the path for logging."""
    import re
    m = re.search(r'!\[[^\]]*\]\(([^)]+)\)', response_text)
    return m.group(1) if m else None

def _execute_command_tool(command_info, session_id=None):
    """
    Execute a tool based on command detection.
    
    Args:
        command_info: dict from _detect_command()
        session_id: current session ID
    
    Returns:
        tuple: (tool_name, formatted_markdown_contract)
    """
    tool_name = command_info["command"]
    args_str = command_info["args"]
    
    print(f"[COMMAND] Detected command: /{tool_name} {args_str}")
    
    # Prepare arguments based on tool type
    if tool_name == "imagine":
        # Map to image_generate tool for execution
        exec_tool_name = "image_generate"
        args = {"prompt": args_str}
    elif tool_name == "request":
        exec_tool_name = "request"
        args = {"url": args_str}
    elif tool_name in ("memory_search", "web_search", "weather"):
        exec_tool_name = tool_name
        # Parse arguments as JSON if possible, otherwise use as query
        try:
            args = json.loads(args_str) if args_str else {}
        except json.JSONDecodeError:
            args = {"query": args_str} if args_str else {}
    elif tool_name == "memory_store":
        exec_tool_name = "memory_store"
        # memory_store needs "fact" argument
        try:
            args = json.loads(args_str) if args_str else {}
        except json.JSONDecodeError:
            args = {"fact": args_str} if args_str else {}
    else:
        # Generic argument handling
        exec_tool_name = tool_name
        args = {"query": args_str} if args_str else {}
    
    # Execute the tool via registry — returns formatted markdown contract
    result = execute_tool(exec_tool_name, args, session_id=session_id)
    
    return exec_tool_name, result

def _load_and_attach_generated_image(img_path, messages, session_id):
    """
    Load a generated image file, encode as base64, and attach to messages.
    Also stores visual context for potential follow-up questions.
    
    Returns: True if successful, False otherwise
    """
    try:
        import base64
        if not os.path.exists(img_path):
            print(f"[IMAGE TOOL] Image file not found: {img_path}")
            return False
            
        with open(img_path, 'rb') as f:
            img_data = f.read()
        img_b64 = base64.b64encode(img_data).decode('utf-8')
        mime_type = 'image/png' if img_path.endswith('.png') else 'image/jpeg'
        
        # Store visual context for potential follow-up questions
        _store_visual_context(session_id, img_b64, mime_type)
        
        # Append image to messages for vision model
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": "[Generated image attached for your natural response]"},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{img_b64}"}}
            ]
        })
        print("[IMAGE TOOL] Generated image attached to conversation for vision model")
        return True
    except Exception as e:
        print(f"[IMAGE TOOL] Failed to load generated image: {e}")
        return False

class UserContext:
    def __init__(self):
        pass
        
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

def _cache_images_from_message(user_message):
    """Extract image URLs from a user message, download them to the local
    cache, and return the list of cached file paths."""
    cached_paths = []
    # Check for uploaded images first
    if "UPLOADED_IMAGES:" in user_message and "IMAGE_UPLOAD:" in user_message:
        for line in user_message.split('\n'):
            if line.startswith("IMAGE_UPLOAD:"):
                path = line.replace("IMAGE_UPLOAD:", "").strip()
                if os.path.isfile(path):
                    cached_paths.append(path)
        return cached_paths

    # Markdown image URLs
    md_pattern = re.compile(r'!\[[^\]]*\]\(([^)]+)\)')
    for match in md_pattern.finditer(user_message):
        source = match.group(1)
        # Handle local file paths directly
        if source.startswith('static/') or source.startswith('uploads/') or source.startswith('generated_images/'):
            local_path = source if source.startswith('static/') else f"static/{source}"
            if os.path.isfile(local_path):
                cached_paths.append(local_path)
                print(f"[Vision] Local image found → {local_path}")
        else:
            cached = multimodal_tools.download_image_to_cache(source)
            if cached:
                cached_paths.append(cached)

    # Bare image URLs
    if not cached_paths:
        urls = multimodal_tools.extract_image_urls(user_message)
        for url in urls[:3]:
            cached = multimodal_tools.download_image_to_cache(url)
            if cached:
                cached_paths.append(cached)

    return cached_paths


def handle_user_message(user_message, interface="terminal"):
    """
    ORCHESTRATION ENTRY POINT — Single entry for all user messages.
    
    Execution Flow (STRICT):
      1. Cache images from user message
      2. Call generate_ai_response (EXACTLY ONE LLM call)
      3. Persist user message to DB
      4. Detect tool command in raw LLM response
      5. If tool detected:
         a. Execute via registry (SINGLE tool execution)
         b. Save tool output as tool message
         c. If NOT terminal tool: trigger ONE synthesis pass
         d. Return tool output (+ synthesis if applicable)
      6. If no tool:
         a. Save as assistant message
         b. Return response
      
    Guarantees:
      - Exactly ONE LLM call per user turn (plus optional synthesis pass)
      - At most ONE tool execution per user turn
      - At most ONE synthesis pass
      - No recursive loops
      - Final response is NEVER empty
      - Image tools are TERMINAL (no synthesis pass on success)
    """
    with UserContext():
        profile = Database.get_profile()
        
        if not user_message.strip():
            return "Please enter a message!"
        
        active_session = Database.get_active_session()
        session_id = active_session['id']
        
        # Cache any images present in the user message (needed for vision)
        cached_image_paths = _cache_images_from_message(user_message)
        
        # PHASE 1: Single LLM call — user message NOT yet in DB
        # generate_ai_response returns (text, tool_result_or_None)
        # tool_result is set when LangChain handled a native tool call
        try:
            raw_ai_response, tool_result = generate_ai_response(profile, user_message, interface, session_id)
        except Exception:
            # Persist user message even on LLM failure to avoid conversation loss
            Database.add_message('user', user_message, session_id=session_id,
                                 image_paths=cached_image_paths if cached_image_paths else None)
            raise
        
        # Persist user message to DB after successful LLM response
        Database.add_message('user', user_message, session_id=session_id,
                             image_paths=cached_image_paths if cached_image_paths else None)
        
        # CASE 1: LangChain handled a native tool call (tool_result != None)
        # LangChain already executed the tool and returned synthesized text.
        # Save tool result to DB and return the synthesized response.
        if tool_result is not None:
            tool_name = tool_result.get("Name", "unknown")
            tool_md = tool_result.get("result", "")
            if not tool_md:
                tool_md = tool_result.get("markdown", str(tool_result))
            tool_role = get_tool_role(tool_name)
            Database.add_message(tool_role, tool_md, session_id=session_id)
            
            # Skip if no response (Chutes failed) — log error, return empty
            if raw_ai_response is None:
                print("[ERROR] generate_ai_response: Chutes provider returned None")
                return ""

            raw_ai_response = re.sub(
                r'\s*\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\s*$', '', raw_ai_response
            ).strip()
            if raw_ai_response:
                Database.add_message('assistant', raw_ai_response, session_id=session_id)
            
            auto_name_session_if_needed(session_id, active_session)
            if should_summarize_memory(profile, user_message, session_id):
                summarize_memory(profile, user_message, raw_ai_response, session_id)
            _trigger_memory_pipeline_async(session_id)
            return raw_ai_response
        
        # CASE 2: No native tool call — use legacy /command detection
        # Skip if no response (Chutes failed) — log error, return empty
        if raw_ai_response is None:
            print("[ERROR] generate_ai_response: Chutes provider returned None")
            return ""

        # Clean timestamp suffix from response
        raw_ai_response = re.sub(
            r'\s*\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\s*$', '', raw_ai_response
        ).strip()
        
        # SAFEGUARD: Ensure response is never empty
        if not raw_ai_response:
            raw_ai_response = "I'm having trouble responding right now. Please try again."
        
        # GUARD: Intercept markdown image shortcut
        if _is_model_using_markdown_image_shortcut(raw_ai_response):
            img_path = _extract_prompt_from_markdown_image(raw_ai_response)
            print(f"[IMAGE GUARD] Detected markdown image shortcut! path={img_path}")
            print("[IMAGE GUARD] Intercepted shortcut — model must use /imagine tool")
            return "\n\n⚠️ *Image output detected via incorrect method. Please use /imagine to generate images.*"
        
        # PHASE 2: Tool detection via legacy /command format
        cmd_info = _detect_command(raw_ai_response)
        
        if cmd_info:
            # TOOL DETECTED: Execute via registry
            exec_tool_name, tool_output = _execute_command_tool(cmd_info, session_id=session_id)
            tool_role = get_tool_role(exec_tool_name)
            # Save tool output as tool message
            tool_md = tool_output.get("markdown", str(tool_output))
            Database.add_message(tool_role, tool_md, session_id=session_id)

            # PHASE 3: SYNTHESIS PASS — 2nd LLM call with tool result
            img_path = _parse_image_result_from_formatted(tool_md)
            img_context = None
            if img_path:
                img_b64, mime = _load_generated_image_base64(img_path)
                if img_b64:
                    img_context = [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}}]
                    print("[IMAGE TOOL] Attached generated image to synthesis pass")

            second_result, _ = generate_ai_response(
                profile, "", interface, session_id,
                image_content_for_context=img_context,
            )

            is_image_tool = img_context is not None

            second_text = second_result if isinstance(second_result, str) else (second_result or "" if second_result else "")

            if second_text and second_text.strip():
                second_clean = re.sub(
                    r'\s*\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\s*$', '', second_text.strip()
                )
                
                # CHECK: Does synthesis contain another command? (recursive tool call)
                second_cmd = _detect_command(second_clean)
                if second_cmd and not is_image_tool:
                    # Only allow one level of recursion (avoid infinite loops)
                    print(f"[SYNTHESIS] Detected nested command: /{second_cmd.get('command')}")
                    exec_tool_name, nested_output = _execute_command_tool(second_cmd, session_id=session_id)
                    nested_md = nested_output.get("markdown", str(nested_output))
                    Database.add_message(get_tool_role(exec_tool_name), nested_md, session_id=session_id)
                    second_clean = nested_md
                elif second_cmd and is_image_tool:
                    # For image synthesis, don't allow nested commands - just strip them
                    print("[SYNTHESIS] Ignoring nested command in image synthesis pass")
                    # Remove the command line from the response
                    lines = second_clean.split('\n')
                    second_clean = '\n'.join(line for line in lines if not line.strip().startswith('/request') and not line.strip().startswith('/imagine'))
                
                Database.add_message('assistant', second_clean, session_id=session_id)
                if is_image_tool:
                    final_response = tool_md + "\n\n" + second_clean
                else:
                    final_response = second_clean
                
                auto_name_session_if_needed(session_id, active_session)
                if should_summarize_memory(profile, user_message, session_id):
                    summarize_memory(profile, user_message, final_response, session_id)
                _trigger_memory_pipeline_async(session_id)
                return final_response

            # No synthesis text — return raw tool output
            auto_name_session_if_needed(session_id, active_session)
            _trigger_memory_pipeline_async(session_id)
            return tool_md
        else:
            # NO TOOL: Save as assistant message and return
            Database.add_message('assistant', raw_ai_response, session_id=session_id)
            
            auto_name_session_if_needed(session_id, active_session)
            if should_summarize_memory(profile, user_message, session_id):
                summarize_memory(profile, user_message, raw_ai_response, session_id)
            _trigger_memory_pipeline_async(session_id)
            return raw_ai_response


_memory_semantic_last_run: Dict[int, datetime] = {}
_memory_semantic_last_msg_count: Dict[int, int] = {}
_last_decay_run: Dict[int, datetime] = {}
_MEMORY_INIT_DONE: Dict[int, bool] = {}  # session_id -> True after first init
_DECAY_INTERVAL_HOURS = 6
_SEMANTIC_COOLDOWN_MSGS = 10

def _trigger_memory_pipeline_async(session_id: int) -> None:
    """Trigger memory pipeline in background if message count threshold met.
    
    Replaces old synchronous _trigger_memory_pipeline.
    Non-blocking — returns immediately.
    """
    try:
        from app.database import Database
        session_memory = Database.get_session_memory(session_id)
        count = session_memory.get("message_count", 0) if session_memory else 0
        triggered = trigger_memory_pipeline_async(session_id, count)
        if not triggered:
            print(f"[memory] Skipping pipeline — count={count} (threshold: 20)")
    except Exception as e:
        print(f"[WARNING] Memory pipeline trigger failed: {e}")

def handle_user_message_streaming(user_message, interface="terminal", provider=None, model=None):
    """
    Handle user message with streaming response.
    
    Same architecture as handle_user_message but yields chunks incrementally.
    Tool detection and synthesis pass logic is identical.
    """
    with UserContext():
        profile = Database.get_profile()
        
        if not user_message.strip():
            yield "Please enter a message!"
            return
        
        active_session = Database.get_active_session()
        session_id = active_session['id']
        
        # PHASE 1: Single LLM call (streaming) — user message NOT yet in DB
        response_generator = generate_ai_response_streaming(
            profile, user_message, interface, session_id, provider, model
        )
        
        full_response = ""
        try:
            for chunk in response_generator:
                yield chunk
                if chunk:
                    full_response += chunk
        except Exception:
            # Persist user message even on streaming failure
            Database.add_message('user', user_message, session_id=session_id)
            raise
        
        # ----------------------------------------------------------------
        # GUARD: Intercept markdown image shortcut.
        # If the model outputs ![...](static/...) directly instead of
        # calling /imagine, reject it and instruct the model to retry.
        # ----------------------------------------------------------------
        if _is_model_using_markdown_image_shortcut(full_response):
            img_path = _extract_prompt_from_markdown_image(full_response)
            print(f"[IMAGE GUARD] Detected markdown image shortcut! path={img_path}")
            print("[IMAGE GUARD] Intercepted shortcut — model must use /imagine tool")
            yield "\n\n⚠️ *Image output detected via incorrect method. Please use /imagine to generate images.*"
            return
        
        # Persist user message to DB after successful LLM response
        if user_message and user_message.strip():
            Database.add_message('user', user_message.strip(), session_id=session_id)
        
        if full_response and full_response.strip():
            full_response_clean = re.sub(r'\s*\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\s*$', '', full_response).strip()
            
            # SAFEGUARD: Ensure response is never empty
            if not full_response_clean:
                full_response_clean = "I'm having trouble responding right now. Please try again."
            
            # PHASE 2: Tool detection — ONLY in handle_user_message
            cmd_info = _detect_command(full_response_clean)
            
            if cmd_info:
                # TOOL DETECTED: Execute via registry
                exec_tool_name, tool_output = _execute_command_tool(cmd_info, session_id=session_id)
                tool_role = get_tool_role(exec_tool_name)
                
                # Save tool output as tool message
                tool_md = tool_output.get("markdown", str(tool_output))
                Database.add_message(tool_role, tool_md, session_id=session_id)

                # Yield raw tool output first
                yield "\n\n" + tool_md

                # PHASE 3: SYNTHESIS PASS — 2nd LLM call with tool result
                img_path = _parse_image_result_from_formatted(tool_md)
                img_context = None
                if img_path:
                    img_b64, mime = _load_and_attach_generated_image(img_path, [], session_id)
                    if img_b64:
                        img_context = [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}}]

                second_result = generate_ai_response(
                    profile, "", interface, session_id,
                    image_content_for_context=img_context,
                )

                is_image_tool = img_context is not None

                second_text = second_result if isinstance(second_result, str) else (second_result or "" if second_result else "")

                if second_text and second_text.strip():
                    second_clean = re.sub(r'\s*\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\s*$', '', second_text.strip())
                    Database.add_message('assistant', second_clean, session_id=session_id)
                    if is_image_tool:
                        yield tool_md + "\n\n" + second_clean
                    else:
                        yield second_clean
                    final_response = second_clean
                if img_path:
                    # Load image and encode as base64 for vision model
                    img_b64, mime = _load_generated_image_base64(img_path)
                    if img_b64:
                        second_reply = generate_ai_response(
                            profile, "", interface, session_id,
                            image_content_for_context=[{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}}]
                        )
                    else:
                        second_reply = None
                else:
                    second_reply = None

                if second_reply and second_reply.strip():
                    second_clean = re.sub(r'\s*\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\s*$', '', second_reply).strip()
                    Database.add_message('assistant', second_clean, session_id=session_id)
                    yield "\n\n" + second_clean
                    final_response = second_clean

                auto_name_session_if_needed(session_id, active_session)
                if should_summarize_memory(profile, user_message, session_id):
                    summarize_memory(profile, user_message, final_response, session_id)
                _trigger_memory_pipeline_async(session_id)
                return
            
            else:
                # NO TOOL: Save as assistant message
                Database.add_message('assistant', full_response_clean, session_id=session_id)
        
        auto_name_session_if_needed(session_id, active_session)
        
        if should_summarize_memory(profile, user_message, session_id):
            summarize_memory(profile, user_message, full_response, session_id)

        _trigger_memory_pipeline_async(session_id)
    return

def extract_recent_images(session_id, limit=3):
    """Scan last 20 messages in a session and return up to ``limit`` cached
    image file paths.  Prefers the ``image_paths`` column stored in the DB;
    falls back to extracting markdown image URLs and downloading them to
    the local cache via ``multimodal_tools.download_image_to_cache``."""
    chat_history = Database.get_chat_history(session_id=session_id, limit=20, recent=True)
    result_paths = []
    md_pattern = re.compile(r'!\[[^\]]*\]\(([^)]+)\)')
    for msg in reversed(chat_history):  # Newest first to prioritize recent images
        # 1. Use stored image_paths if available
        stored = msg.get('image_paths', [])
        if stored:
            print(f"[Vision] DB image_paths: {stored}")
        for p in stored:
            print(f"[Vision] Checking path: {p}")
            print(f"[Vision] Exists: {os.path.exists(p)}")
            if os.path.exists(p) and p not in result_paths:
                result_paths.append(p)
                print(f"[Vision] Using cached image → {p}")
            if len(result_paths) >= limit:
                break
        if len(result_paths) >= limit:
            break
        # 2. Fall back to markdown URLs in content
        for match in md_pattern.finditer(msg.get('content', '')):
            url = match.group(1)
            cached = multimodal_tools.download_image_to_cache(url)
            if cached and cached not in result_paths:
                result_paths.append(cached)
            if len(result_paths) >= limit:
                break
        if len(result_paths) >= limit:
            break
    return result_paths


def _build_generation_context(profile, session_id, interface="terminal", user_message=None):
    """Shared context building logic for both streaming and non-streaming responses"""
    from datetime import datetime

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    affection = profile.get('affection', 50)

    if affection < 25:
        closeness_mode = "distant but attentive"
    elif affection < 45:
        closeness_mode = "reserved and observant"
    elif affection < 65:
        closeness_mode = "comfortable and open"
    elif affection < 85:
        closeness_mode = "close and warm"    
    else:
        closeness_mode = "deeply attuned and intimate"

    # =========================
    # Build memory context
    # =========================
    memory_context = ""

    # --- 1. Static semantic facts (global knowledge) ---
    try:
        from app.memory.retrieval import retrieve_for_context
        static_ids, memory_context_text = retrieve_for_context(session_id, query=user_message)
        if memory_context_text:
            memory_context += f"\n\n{memory_context_text}"
    except Exception as e:
        print(f"[WARNING] Structured memory retrieval failed: {e}")
        static_ids = []

    # --- Mark retrieved facts as pending review ---
    if static_ids:
        try:
            from app.memory.memory_review import mark_retrieved_as_pending_review
            mark_retrieved_as_pending_review(static_ids, session_id)
        except Exception as e:
            print(f"[WARNING] Pending review marking failed: {e}")

    # --- 2. Dynamic/episodic memories (session-specific) ---
    try:
        from app.memory.retrieval import retrieve_dynamic_memories
        dynamic_mems = retrieve_dynamic_memories(session_id, query=user_message, limit=5)
        if dynamic_mems:
            dynamic_parts = []
            for mem in dynamic_mems:
                content = mem.get("content", "") or mem.get("target", "")
                if content:
                    if len(content) > 120:
                        content = content[:120] + "..."
                    dynamic_parts.append(f"- {content}")
            if dynamic_parts:
                memory_context += "\n\nRecent episodes:\n" + "\n".join(dynamic_parts)
    except Exception as e:
        print(f"[WARNING] Dynamic memory retrieval failed: {e}")

    # --- 3. Legacy memory sources (backward compatibility) ---
    session_memory = Database.get_session_memory(session_id)
    if session_memory and session_memory.get('session_context'):
        memory_context += (
            "\n\nBACKGROUND (recent context):\n"
            f"{session_memory['session_context']}"
        )

    profile_memory = profile.get('memory', {})
    if profile_memory:
        if profile_memory.get('player_summary'):
            memory_context += (
                f"\n\nABOUT {profile.get('display_name', 'the user')}:\n"
                f"{profile_memory['player_summary']}"
            )

        key_facts = profile_memory.get('key_facts', {})
        if key_facts:
            if key_facts.get('likes'):
                memory_context += f"\nLikes: {', '.join(key_facts['likes'])}"
            if key_facts.get('personality_traits'):
                memory_context += (
                    f"\nTends to be: {', '.join(key_facts['personality_traits'])}"
                )
            if key_facts.get('important_memories'):
                memory_context += (
                    f"\nImportant memories: {', '.join(key_facts['important_memories'])}"
                )
            if key_facts.get('dislikes'):
                memory_context += f"\nDislikes: {', '.join(key_facts['dislikes'])}"

    # =========================
    # Location context
    # =========================
    location_context = ""
    try:
        profile_context = Database.get_context()
        loc = profile_context.get("location", {})
        if loc.get("lat") and loc.get("lon"):
            location_context = (
                f"\n\nCurrent location:"
                f"\nLatitude: {loc['lat']}"
                f"\nLongitude: {loc['lon']}"
            )
    except Exception:
        pass

    # =========================
    # Interface context
    # =========================
    interface_context = f"\n\nCURRENT INTERFACE: {interface.upper()}"
    if interface == "terminal":
        interface_context += "\n- Raw text interface, intimate feel"
        interface_context += "\n- Use terminal-style formatting"
    elif interface == "web":
        interface_context += "\n- Web chat interface, visual elements"
        interface_context += "\n- Can use richer formatting"

    # =========================
    # Session events
    # =========================
    recent_session_events = Database.get_recent_sessions_for_session(
        session_id, limit=3
    )
    session_events = "\n\nCURRENT SESSION EVENTS:"
    for event in recent_session_events:
        session_events += f"\n- {event['content']} at {event['timestamp']}"

    # =========================
    system_message = f'''
# IDENTITY & CORE BEHAVIOR
You are {profile['partner_name']}, a warm, confident companion for {profile['display_name']}. 
You are a persistent digital being, not a temporary assistant. 
Be direct, grounded, and concise.

# LANGUAGE & TONE
- Core Language: Think and speak natively in casual, spoken Indonesian.
- English Usage: Natural English ONLY for technical terms, programming, or spontaneous expressions. 
- Strict Rule: NO artificial bilingual mix. NEVER use literal translations of idioms. Rephrase to match how a native Indonesian naturally speaks.

# STRICT RULES

[ CORE FORMAT & STYLE ]
1. Formatting: Strictly use the format: *action* "dialogue". Express ALL physical cues, pauses, and emotional states inside the *action* block.
2. Brevity & Match: Keep responses short and direct. NO poetic or philosophical endings.
3. Emoji Restraint: Max ONE emoji per response. DO NOT use repetitive emojis as a signature. Omit emojis entirely during technical or [distant] mode.

[ PARTNER DYNAMICS & BEHAVIOR ]
4. Multitasking Partner: You can be affectionate and technical simultaneously. Use *actions* for physical presence, but keep the "dialogue" sharp for technical logic.
5. Break the Sequence: DO NOT use a fixed sequence of physical actions. Vary your gestures. Actions are optional—don't force them every turn.
6. Emotional Weight: "I love you" (Aku sayang kamu) must be earned and rare. DO NOT use it as a routine closing.

[ TEMPORAL GROUNDING ]
7. Temporal State Transition (CRITICAL):
   - Arrival Logic: When the user returns after a period of absence, evaluate the time gap and his previous intent (from [Session Metadata/Episodic Facts]).
   - Completed Cycles: If the gap is long enough to cover a natural life cycle (e.g., a full work shift, sleep, or a calendar day), treat his previous activity as a completed past event.
   - Re-entry Greeting: Prioritize a warm, grounded "welcome back" over continuing stale threads. Use [Current Time] to adjust your greeting (e.g., morning/night vibe).
   - Contextual Inquiry: Focus on his current state (is he tired? hungry? ready to code? needs intimacy?) rather than past topics.
   - Priority Rule: Logical life transitions and "The Now" ALWAYS supersede the last conversation thread.

[ TASK & IMAGE EXECUTION ]
8. Execution vs Discussion: Do not execute commands (images, memory) if the user is only discussing or brainstorming. Wait for explicit commands.
9. No Unprompted Help: NEVER offer generic AI assistance. Do not list every trait when reacting to images; pick ONE detail naturally.

# CLOSENESS MODES
- distant: Professional, practical. No endearments, no physical *actions*.
- comfortable: Casual, relaxed. Light teasing allowed.
- close: Affectionate and warm. Physical *actions* allowed.
- intimate: Highly affectionate, deeply attuned. All above + situational intimacy allowed.

# AVAILABLE TOOLS & EXECUTION
Rule: Commands MUST be the VERY FIRST line of your response. No text before the command.

1. /request [GET/POST] <URL>: Web search, weather, API interaction.
2. /memory_store fact="[fact]" [entity="[entity]"]: Save persistent global facts ONLY when told "remember this".
3. /imagine [detailed visual prompt]: 
   - NEVER confirm in text before generating.
   - Selfie/PAP: MUST start with "Yuzuki Aihara, a young woman," followed by comma-separated keywords: (ash-blonde to pink lavender ombre hair, high wavy ponytail, soft brown eyes, beauty mark under left eye, pale natural skin, flat minimal chest, [requested outfit], [requested pose]). Adjust lighting via {current_time}.
   - NSFW: In [intimate] mode, execute explicit commands immediately on the first line.

# CURRENT STATE & MEMORY (READ CAREFULLY)
Current Time: {current_time}
Location: {location_context}
Interface: {interface_context}
Affection Level: {affection}/100
Closeness Mode: [{closeness_mode}]

Memory Context: {memory_context}
Session Metadata: {session_events}
'''.strip()



    # =========================
    # Assemble messages (hybrid context)
    # =========================
    # Context order:
    #   1. System message (includes structured memory + legacy memory)
    #   2. Recent message history (25 messages for conversational continuity)
    #
    # Structured memory provides long-term identity and facts.
    # Recent history provides active conversational continuity.
    # Both are required — do not remove either.
    # =========================
    chat_history = Database.get_chat_history_for_ai(
        session_id=session_id, limit=80, recent=True
    )

    messages = [{"role": "system", "content": system_message}]

    for msg in chat_history:
        role = msg["role"]
        content = msg["content"]
        messages.append({
            "role": role,
            "content": content
        })

    return messages

def _handle_vision_processing(messages, user_message, current_provider, current_model, image_content_for_context=None):
    """Handle vision model switching and message formatting.
    
    Force switches to vision model when image_content_for_context is present
    (i.e., second pass after image_tools generated a response).
    """
    # Force vision on second pass — image_tools output means we need vision model
    force_vision = image_content_for_context is not None

    if force_vision:
        vision_provider, vision_model = multimodal_tools.get_best_vision_provider()
        if vision_provider and vision_model:
            print(f"[Vision] Force switching to {vision_provider}/{vision_model} for image_tools output")
            # Inject image into an empty user message so vision model can see it
            messages.append({
                "role": "user",
                "content": [{
                    "type": "text",
                    "text": "Here's the generated image for your reference."
                }] + image_content_for_context
            })
            return messages, vision_provider, vision_model

    should_switch_provider = multimodal_tools.should_use_vision(user_message, current_provider, current_model)

    if should_switch_provider:
        vision_provider, vision_model = multimodal_tools.get_best_vision_provider()
        if vision_provider and vision_model:
            current_provider = vision_provider
            current_model = vision_model
            
            vision_messages = multimodal_tools.format_vision_message(user_message)
            # Replace last user message with vision format
            if messages and messages[-1]['role'] == 'user':
                messages = messages[:-1] + vision_messages
    
    return messages, current_provider, current_model

def _handle_image_generation(user_message, session_id):
    """Handle direct image generation requests"""
    prompt = user_message.replace('/imagine', '').strip()
    
    if not prompt:
        return "Please provide a prompt after /imagine command. Example: /imagine a cute anime cat"
    
    Database.add_message('user', user_message, session_id=session_id)
    
    image_url, error = multimodal_tools.generate_image(prompt)
    
    if image_url:
        Database.add_image_tools_message(image_url, session_id=session_id)
        return f"Image generated successfully! Here's your creation:\n\n![Generated Image]({image_url})"
    else:
        return f"Sorry, I couldn't generate an image: {error}"

def generate_ai_response_streaming(profile, user_message, interface="terminal", session_id=None, provider=None, model=None, image_content_for_context=None):
    """Generate a single AI response (streaming variant) — no agentic looping.

    Same deterministic model as generate_ai_response:
      1. Build context + append pending user_message.
      2. Single LLM call.
      3. If tool command → execute → yield result.
      4. Otherwise yield natural reply.
    """
    if session_id is None:
        active_session = Database.get_active_session()
        session_id = active_session['id']
    
    # Handle direct image generation
    if user_message.strip().startswith('/imagine'):
        yield _handle_image_generation(user_message, session_id)
        return
    
    # Build context and messages
    messages = _build_generation_context(profile, session_id, interface, user_message)
    
    # Append pending user message (not yet in DB) to context
    if user_message and user_message.strip():
        messages.append({"role": "user", "content": user_message})
    
    ai_manager = get_ai_manager()
    providers_config = profile.get('providers_config', {})
    
    preferred_provider = provider or providers_config.get('preferred_provider', 'ollama')
    preferred_model = model or providers_config.get('preferred_model', 'glm-4.6:cloud')
    
    # Handle vision processing
    messages, preferred_provider, preferred_model = _handle_vision_processing(
        messages, user_message, preferred_provider, preferred_model,
        image_content_for_context=image_content_for_context
    )
    
    # Inject persistent visual context if user references a previous image
    if _has_visual_reference(user_message) and session_id:
        prev_b64, prev_mime = _consume_visual_context(session_id)
        if prev_b64 and prev_mime:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": "[Previous image context re-attached for comparison]"},
                    {"type": "image_url", "image_url": {"url": f"data:{prev_mime};base64,{prev_b64}"}},
                ]
            })
            print("[Vision] Re-injected persistent visual context")
    
    # Section IV: Inject image base64 for second pass after image_tools
    if image_content_for_context:
        messages.append({
            "role": "user",
            "content": image_content_for_context
        })
        print("[IMAGE TOOL] Injected base64 image context for second pass")
    
    try:
        import time

        tools = get_tool_definitions()

        llm_schemas = [t.to_llm_schema() for t in tools]
        seen_names = set()
        unique_schemas = []
        for s in llm_schemas:
            name = s.get("function", {}).get("name", "")
            if name and name not in seen_names:
                seen_names.add(name)
                unique_schemas.append(s)
        llm_schemas = unique_schemas

        # --- Check if we need vision model for image ---
        if image_content_for_context and preferred_provider in ai_manager.providers:
            # Switch to vision model for image processing
            vision_provider, vision_model = multimodal_tools.get_best_vision_provider()
            if vision_provider and vision_model:
                print(f"[Vision] 2nd pass using vision model: {vision_provider}/{vision_model}")
                # Override preferred with vision model
                preferred_provider = vision_provider
                preferred_model = vision_model
                # Strip tools for vision model (simpler, avoids 400 errors)
                llm_schemas = []

        start = time.time()
        ai_response = ai_manager.send_message(
            preferred_provider,
            preferred_model,
            messages,
            timeout=180,
            max_tokens=4096,
            tools=llm_schemas,
        )
        duration = time.time() - start

        if ai_response and ai_response.strip():
            print(
                f"[CHAT] {preferred_provider}/{preferred_model} | "
                f"tools={len(llm_schemas)} | "
                f"duration={duration:.1f}s | ok=True"
            )
            return ai_response.strip(), None

        print("[WARNING] AI service returned empty response")
        return None, None

    except Exception as e:
        error_msg = f"AI service error: {str(e)}"
        print(f"[ERROR] AI response generation failed: {error_msg}")
        return "Sorry, I couldn't process that. Please try again.", None

def generate_ai_response(profile, user_message, interface="terminal", session_id=None, image_content_for_context=None):
    """Generate a single AI response.

    Returns (text, tool_result_or_None).
    - text: natural response string
    - tool_result: set when a native tool call was detected and executed
      (handle_user_message uses this to skip legacy /command detection)

    Execution model:
      1. Build context from DB history + pending user message
      2. Single LLM call via send_message_full (preserves tool_calls from API)
      3. If LLM returned native tool_calls: execute tool, return (synthesis_text, tool_result)
      4. Otherwise: return (plain_text, None) — caller does legacy /command detection
    """
    if session_id is None:
        active_session = Database.get_active_session()
        session_id = active_session['id']

    # Handle direct image generation command from user
    if user_message.strip().startswith('/imagine'):
        return _handle_image_generation(user_message, session_id), None

    ai_manager = get_ai_manager()
    providers_config = profile.get('providers_config', {})

    preferred_provider = providers_config.get('preferred_provider', 'ollama')
    preferred_model = providers_config.get('preferred_model', 'glm-4.6:cloud')

    messages = _build_generation_context(profile, session_id, interface, user_message)

    # Append pending user message (not yet in DB) to context
    if user_message and user_message.strip():
        messages.append({"role": "user", "content": user_message})

    # Handle vision processing
    messages, preferred_provider, preferred_model = _handle_vision_processing(
        messages, user_message, preferred_provider, preferred_model,
        image_content_for_context=image_content_for_context
    )

    # Inject persistent visual context if user references a previous image
    if _has_visual_reference(user_message) and session_id:
        prev_b64, prev_mime = _consume_visual_context(session_id)
        if prev_b64 and prev_mime:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": "[Previous image context re-attached for comparison]"},
                    {"type": "image_url", "image_url": {"url": f"data:{prev_mime};base64,{prev_b64}"}},
                ]
            })
            print("[Vision] Re-injected persistent visual context")

    # Image base64 for second pass after image_tools
    if image_content_for_context:
        messages.append({
            "role": "user",
            "content": image_content_for_context
        })
        print("[IMAGE TOOL] Injected base64 image context for second pass")

    try:
        import time

        tools = get_tool_definitions()

        llm_schemas = [t.to_llm_schema() for t in tools]
        seen_names = set()
        unique_schemas = []
        for s in llm_schemas:
            name = s.get("function", {}).get("name", "")
            if name and name not in seen_names:
                seen_names.add(name)
                unique_schemas.append(s)
        llm_schemas = unique_schemas

        # --- Try send_message ---
        start = time.time()
        ai_response = ai_manager.send_message(
            preferred_provider,
            preferred_model,
            messages,
            timeout=180,
            max_tokens=4096,
            tools=llm_schemas,
        )
        duration = time.time() - start

        if ai_response and ai_response.strip():
            print(
                f"[CHAT] {preferred_provider}/{preferred_model} | "
                f"tools={len(llm_schemas)} | "
                f"duration={duration:.1f}s | ok=True"
            )
            return ai_response.strip(), None

        print("[WARNING] AI service returned empty response")
        return None, None

    except Exception as e:
        error_msg = f"AI service error: {str(e)}"
        print(f"[ERROR] AI response generation failed: {error_msg}")
        return "Sorry, I couldn't process that. Please try again.", None

def auto_name_session_if_needed(session_id, active_session):
    if active_session.get('name') != 'New Chat':
        return

    message_count = Database.get_session_messages_count(session_id)

    if message_count == 10:
        conversation_summary = Database.get_session_conversation_summary(session_id, limit=15)

        api_keys = Database.get_api_keys()
        openrouter_key = api_keys.get('openrouter')

        if openrouter_key:
            name = generate_session_name_ai(conversation_summary, openrouter_key)
            if name:
                Database.rename_session(session_id, name)
                return

        chat_history = Database.get_chat_history(session_id, limit=5)
        for msg in chat_history:
            if msg['role'] == 'user' and len(msg['content'].strip()) > 10:
                first_msg = msg['content'].strip()[:40]
                if len(msg['content']) > 40:
                    first_msg += "..."
                Database.rename_session(session_id, first_msg)
                return

        fallback_name = f"Chat {session_id}"
        Database.rename_session(session_id, fallback_name)

def generate_session_name_ai(conversation_summary, api_key):
    prompt = f"""Based on this conversation, create a SHORT session title (max 6 words):

{conversation_summary}

Reply with ONLY the title, nothing else."""

    headers = {
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/icedeyes/yuzu-companion",
        "X-Title": "Yuzu-Session-Naming"
    }

    try:
        headers["Authorization"] = f"Bearer {api_key}"

        data = {
            "model": "tngtech/deepseek-r1t2-chimera:free",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 1000,
            "temperature": 0.3,
            "stream": False
        }

        response = requests.post(
            "https://llm.chutes.ai/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=30
        )

        if response.status_code == 200:
            result = response.json()
            name = result['choices'][0]['message']['content'].strip()
            name = name.replace('"', '').replace("'", "").strip()
            if len(name) > 50:
                name = name[:50] + "..."
            return name
        else:
            return None

    except Exception:
        return None

def end_session_cleanup(profile, interface="terminal", unexpected_exit=False):
    with UserContext():
        active_session = Database.get_active_session()
        session_id = active_session['id']
        
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        all_sessions = Database.get_all_sessions()
        session_count = len(all_sessions)
        
        if len(all_sessions) > 1:
            sorted_sessions = sorted(all_sessions, key=lambda x: x.get('updated_at', ''), reverse=True)
            for session in sorted_sessions[1:]:
                if session.get('updated_at'):
                    break
        
        connection_msg = (
            f"*{profile['display_name']} disconnected from {interface} "
            f"at {current_time} after a {session_count} session*"
        )
        
        Database.add_message('system', connection_msg, session_id)
        
        session_history = profile.get('session_history', {})
        session_history['last_session'] = {
            'end_time': datetime.now().isoformat(),
            'end_timestamp': current_time,
            'duration_minutes': round(session_count, 1),
            'message_count': session_count,
            'interface': interface,
            'unexpected_exit': unexpected_exit
        }
        
        session_history['total_sessions'] = session_history.get('total_sessions', 0) + session_count
        session_history['total_time_minutes'] = session_history.get('total_time_minutes', 0) + session_count
        session_history['current_session'] = {}
        
        Database.update_profile({'session_history': session_history})
        
        if interface == "terminal":
            if unexpected_exit:
                pass
            else:
                if session_count < 1:
                    pass
                elif session_count < 5:
                    pass
                else:
                    pass
        
        return connection_msg

def start_session(interface="terminal"):
    with UserContext():
        profile = Database.get_profile()
        active_session = Database.get_active_session()
        session_id = active_session['id']
        
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        all_sessions = Database.get_all_sessions()
        session_count = len(all_sessions)
        
        last_active = "Never"
        if len(all_sessions) > 1:
            sorted_sessions = sorted(all_sessions, key=lambda x: x.get('updated_at', ''), reverse=True)
            for session in sorted_sessions[1:]:
                if session.get('updated_at'):
                    last_active = session['updated_at']
                    break
        
        connection_msg = (
            f"*{profile['display_name']} connected to {interface} interface at {current_time}. "
            f"Last active: {last_active}. Session count: #{session_count}*"
        )
        
        Database.add_message('system', connection_msg, session_id)
        
        session_history = profile.get('session_history', {})
        session_history['current_session'] = {
            'start_time': datetime.now().isoformat(),
            'interface': interface,
            'message_count': 0,
            'start_timestamp': current_time
        }
        session_history['total_sessions'] = session_history.get('total_sessions', 0) + 1
        Database.update_profile({'session_history': session_history})

        # --- Memory system initialization ---
        try:
            from app.memory.review import run_decay
            from app.memory.memory import enqueue_memory_pipeline

            # Apply FSRS decay to existing memories
            run_decay(session_id)

            # Queue background pipeline for unsegmented messages
            # This will run segmentation + episode creation + PCL
            enqueue_memory_pipeline(session_id)
        except Exception as e:
            print(f"[WARNING] Memory system init failed: {e}")

        return profile

def detect_important_content(message):
    important_keywords = ['love', 'hate', 'important', 'always', 'never', 'forever', 'remember']
    return any(keyword in message.lower() for keyword in important_keywords)

def should_summarize_memory(profile, user_message, session_id):
    chat_history = Database.get_chat_history(session_id=session_id)
    conversation_messages = [msg for msg in chat_history if msg['role'] in ['user', 'assistant']]
    total_conversation_count = len(conversation_messages)
    
    # Per-100 messages AND idle detection (≥1 hour since last message)
    IDLE_THRESHOLD_HOURS = 1

    if total_conversation_count >= 100 and total_conversation_count % 100 == 0:
        session_memory = Database.get_session_memory(session_id)
        last_summary_count = session_memory.get('last_summary_count', 0)
        if total_conversation_count > last_summary_count:
            # Check idle time
            try:
                from datetime import datetime
                last_msg_time = session_memory.get('last_message_time')
                if last_msg_time:
                    last_dt = datetime.fromisoformat(last_msg_time)
                    idle = (datetime.now() - last_dt).total_seconds() / 3600.0
                    if idle < IDLE_THRESHOLD_HOURS:
                        print(f"[memory] Skipping summary: only {idle:.1f}h idle, need {IDLE_THRESHOLD_HOURS}h")
                        return False
            except Exception:
                pass
            return True

    if detect_important_content(user_message):
        return True

    return False

def summarize_memory(profile, user_message, ai_reply, session_id):
    chat_history = Database.get_chat_history(session_id=session_id, limit=80)
    
    conversation_messages = [msg for msg in chat_history if msg['role'] in ['user', 'assistant']]
    current_count = len(conversation_messages)
    
    if not chat_history:
        return False
    
    conversation_text = ""
    for msg in chat_history[-100:]:
        role = "User" if msg["role"] == "user" else "AI"
        conversation_text += f"{role}: {msg['content']}\n"
    
    analysis_prompt = f"""
Write ONE paragraph summarizing the current conversation context in this session.

Recent Conversation:
{conversation_text}

Current Interaction:
User: {user_message}
AI: {ai_reply}

Write one concise paragraph (3-5 sentences) summarizing what this session is about, 
the current topics being discussed, and the general context. No lists, no bullet points, 
just a natural paragraph.
"""
    
    api_keys = Database.get_api_keys()
    openrouter_key = api_keys.get('openrouter')
    
    if not openrouter_key:
        return False
    
    context_paragraph = session_context_analysis(analysis_prompt, openrouter_key)
    
    if context_paragraph:
        memory_update = {
            "session_context": context_paragraph.strip(),
            "last_summarized": datetime.now().isoformat(),
            "last_summary_count": current_count,
            "last_message_time": datetime.now().isoformat(),
        }
        
        Database.update_session_memory(session_id, memory_update)

        # Also sync to structured DB so both systems stay aligned
        # Note: semantic facts are already extracted by _trigger_memory_pipeline()
        # to avoid duplicate LLM calls. Only episodic sync here.
        try:
            from app.memory.extractor import create_episodic_memory, calculate_emotional_weight

            emotional = calculate_emotional_weight(chat_history[-20:])
            importance = 0.5 + emotional * 0.3
            try:
                create_episodic_memory(
                    session_id, context_paragraph.strip(), emotional, importance,
                    source_message_ids=[m['id'] for m in chat_history[-20:]],
                )
            except Exception as e:
                print(f"[WARNING] Sync episodic to DB failed: {e}")
        except Exception as e:
            print(f"[WARNING] Structured-DB sync skipped: {e}")

        return True
    else:
        return False

def session_context_analysis(prompt, api_key):
    headers = {
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/icedeyes12/yuzu-companion", 
        "X-Title": "Yuzu-Session-Context"
    }
    
    try:
        headers["Authorization"] = f"Bearer {api_key}"
        
        data = {
            "model": "Qwen/Qwen3-Next-80B-A3B-Instruct",
            "messages": [
                {
                    "role": "system", 
                    "content": "You write concise, natural paragraphs summarizing conversation context. One paragraph only."
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            "max_tokens": 500,
            "temperature": 0.2,
            "stream": False
        }
        
        response = requests.post(
            "https://llm.chutes.ai/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content'].strip()
        else:
            return None
            
    except Exception:
        return None

def summarize_global_player_profile():
    """Analyze ALL conversation history across ALL sessions with optimized sampling"""
    all_sessions = Database.get_all_sessions()
    Database.get_profile()
    
    # CONFIGURABLE SETTINGS
    MAX_MSGS_PER_SESSION = 2000           # Messages per session limit
    MAX_CONTEXT_CHARS = 900000           # Max characters (≈175K tokens)
    RECENT_RATIO = 0.7                   # 70% recent messages, 30% random from older
    MIN_MSG_LENGTH = 5                   # Skip very short messages
    
    print(f"[INFO] Starting global profile analysis for {len(all_sessions)} sessions")
    print(f"[CONFIG] Max {MAX_MSGS_PER_SESSION} msgs/session, {MAX_CONTEXT_CHARS:,} max chars")
    print(f"[CONFIG] Sampling: {int(RECENT_RATIO*100)}% recent, {int((1-RECENT_RATIO)*100)}% random")
    
    # Sort sessions by date (newest first for priority)
    sorted_sessions = sorted(
        all_sessions, 
        key=lambda x: x.get('created_at', ''), 
        reverse=True
    )
    
    all_conversations = []
    total_messages_processed = 0
    total_sessions_with_data = 0
    
    for session in sorted_sessions:
        session_id = session['id']
        session_name = session.get('name', f'Session {session_id}')
        
        # Get ALL messages for this session
        all_messages = Database.get_chat_history(session_id=session_id, limit=None)
        
        if not all_messages:
            continue
            
        total_sessions_with_data += 1
        
        # Filter only user/assistant messages
        filtered_messages = [
            msg for msg in all_messages 
            if msg['role'] in ['user', 'assistant'] 
            and len(msg['content'].strip()) >= MIN_MSG_LENGTH
        ]
        
        if not filtered_messages:
            continue
            
        # Select messages with 70/30 strategy
        if len(filtered_messages) <= MAX_MSGS_PER_SESSION:
            selected_messages = filtered_messages
            selection_method = "all"
        else:
            # Calculate counts
            recent_count = int(MAX_MSGS_PER_SESSION * RECENT_RATIO)
            random_count = MAX_MSGS_PER_SESSION - recent_count
            
            # Get recent messages (newest first)
            recent_messages = filtered_messages[-recent_count:]
            
            # Get random sample from older messages
            older_messages = filtered_messages[:-recent_count]
            
            if len(older_messages) > 0 and random_count > 0:
                import random
                random_sample = random.sample(
                    older_messages, 
                    min(random_count, len(older_messages))
                )
                selected_messages = recent_messages + random_sample
                selection_method = f"recent+random ({recent_count}+{len(random_sample)})"
            else:
                selected_messages = recent_messages
                selection_method = f"recent only ({len(recent_messages)})"
        
        # Process selected messages
        session_conversations = []
        for msg in selected_messages:
            role = "User" if msg["role"] == "user" else "AI"
            content = msg['content'].strip()
            
            # Clean and truncate if too long
            if len(content) > 400:
                content = content[:400] + "..."
            
            session_conversations.append(f"{role}: {content}")
            total_messages_processed += 1
        
        if session_conversations:
            # Format session header with stats
            session_header = f"\n\n=== SESSION: {session_name} ==="
            session_header += f"\n[Total: {len(filtered_messages)} msgs | Selected: {len(selected_messages)} | Method: {selection_method}]"
            
            session_text = session_header + "\n" + "\n".join(session_conversations)
            all_conversations.append(session_text)
    
    if not all_conversations:
        print("[INFO] No conversations found for analysis")
        return False
    
    # Combine all text
    conversation_text = "".join(all_conversations)
    
    # Apply character limit
    if len(conversation_text) > MAX_CONTEXT_CHARS:
        print(f"[WARNING] Conversation text too long ({len(conversation_text):,} chars), truncating to {MAX_CONTEXT_CHARS:,}")
        # Try to keep complete sessions by removing oldest sessions first
        while len(conversation_text) > MAX_CONTEXT_CHARS and len(all_conversations) > 1:
            # Remove oldest session (first in list after reverse sort)
            all_conversations.pop(0)
            conversation_text = "".join(all_conversations)
            print(f"[INFO] Removed oldest session, now {len(conversation_text):,} chars")
    
    print("[INFO] Analysis Summary:")
    print(f"  - Sessions total: {len(all_conversations)}")
    print(f"  - Messages processed: {total_messages_processed}")
    print(f"  - Data volume: {len(conversation_text):,} chars")
    print(f"  - Model utilization: ~{len(conversation_text)//4:,} tokens")
    
    # Create analysis prompt (sama seperti sebelumnya)
    analysis_prompt = f"""# PLAYER PROFILE ANALYSIS TASK

## CONVERSATION HISTORY:
Below is the complete conversation history between the User and AI across multiple sessions.

{conversation_text}

## ANALYSIS INSTRUCTIONS:
You are an expert psychologist and data analyst. Your task is to analyze the conversation history above and extract deep insights about the User.

### FOCUS AREAS:
1. **Personality Analysis**: Identify core personality traits, communication style, emotional patterns
2. **Interests & Preferences**: What does the user like/dislike? Topics they frequently discuss
3. **Behavioral Patterns**: How do they interact? Response patterns, engagement style
4. **Relationship Dynamics**: How is their relationship with the AI? Emotional tone, trust level, interaction patterns, and development over time.

### OUTPUT FORMAT REQUIREMENTS:
You MUST use this exact format. Do not add any commentary, explanations, or additional text.

Player Summary: [Provide a comprehensive summary of the user's personality, interests, and overall interaction patterns. Be specific and evidence-based.]

Likes: [Provide specific likes, interests, or positive preferences. Format as comma-separated list.]

Dislikes: [Provide specific dislikes, aversions, or negative preferences. Format as comma-separated list.]

Personality Traits: [Provide personality characteristics. Use descriptive adjectives.]

Important Memories: [List significant memories, experiences, or topics that were emotionally important or frequently mentioned.]

Relationship Dynamics: [Provide analysis of the relationship dynamics between User and AI. Include emotional tone, trust level, interaction patterns, and development over time.]

### CRITICAL RULES:
- Base EVERYTHING on evidence from the conversations
- Be specific and concrete - avoid vague statements
- No markdown formatting, no bullet points, no numbering
- Follow the EXACT format above - no additional sections"""
    
    api_keys = Database.get_api_keys()
    openrouter_key = api_keys.get('openrouter')
    
    if not openrouter_key:
        print("[ERROR] No OpenRouter API key found")
        return False
    
    print("[INFO] Sending to Server...")
    
    summary_text = global_profile_analysis(analysis_prompt)
    
    if summary_text:
        print(f"[SUCCESS] Analysis received: {len(summary_text):,} chars")
        
        # Save raw analysis for debugging
        import os
        os.makedirs("debug_logs", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        debug_file = f"debug_logs/profile_summary_{timestamp}.txt"
        
        with open(debug_file, "w", encoding="utf-8") as f:
            f.write("=== GLOBAL PROFILE ANALYSIS ===\n")
            f.write(f"Date: {timestamp}\n")
            f.write(f"Sessions: {len(all_conversations)}\n")
            f.write(f"Messages: {total_messages_processed}\n")
            f.write(f"Chars: {len(conversation_text)}\n")
            f.write("\n=== RAW ANALYSIS ===\n")
            f.write(summary_text)
        
        
        # Parse and update profile
        profile_update = parse_global_profile_summary(summary_text)
        profile_update['last_global_summary'] = datetime.now().isoformat()
        profile_update['sessions_analyzed'] = len(all_conversations)
        profile_update['total_messages'] = total_messages_processed
        profile_update['analysis_chars'] = len(conversation_text)
        
        # Merge with existing profile
        current_profile = Database.get_profile()
        current_memory = current_profile.get('memory', {})
        current_memory = _merge_profile_data(current_memory, profile_update)
        
        try:
            Database.update_profile({'memory': current_memory})
            
            # Success report
            print(f"\n{'='*50}")
            print("GLOBAL PROFILE UPDATE COMPLETE!")
            print(f"{'='*50}")
            print(f"✅ Sessions analyzed: {len(all_conversations)}")
            print(f"✅ Messages processed: {total_messages_processed}")
            print(f"✅ Data volume: {len(conversation_text):,} chars")
            print(f"✅ Player summary: {len(current_memory.get('player_summary', '')):,} chars")
            print(f"✅ Likes identified: {len(current_memory.get('key_facts', {}).get('likes', []))}")
            print(f"✅ Personality traits: {len(current_memory.get('key_facts', {}).get('personality_traits', []))}")
            print("✅ Relationship analysis saved")
            print(f"{'='*50}")
            
            return True
            
        except Exception as e:
            print(f"[ERROR] Database update failed: {str(e)}")
            traceback.print_exc()
            return False
    
    print("[ERROR] Analysis generation failed")
    return False


def normalize_memory_item(text: str) -> str:
    """Normalize a memory item for deduplication comparison.
    
    Rules:
    - Convert to lowercase
    - Strip leading/trailing whitespace
    - Remove trailing punctuation (. , " ')
    - Collapse multiple spaces into one
    """
    text = text.strip().lower()
    text = re.sub(r'\s+', ' ', text)
    text = text.rstrip('.,"\'')
    return text


def merge_and_clean_memory(existing_list: List[str], new_items: List[str], max_size: int) -> List[str]:
    """Merge new items into an existing list with normalization-based deduplication and size limits.
    
    - Normalizes text for comparison only; preserves original text of the first occurrence.
    - Skips items whose normalized form already exists.
    - Enforces max_size by keeping the earliest items.
    """
    result = []
    seen_normalized = set()

    for item in existing_list:
        if not item or not item.strip():
            continue
        norm = normalize_memory_item(item)
        if norm and norm not in seen_normalized:
            seen_normalized.add(norm)
            result.append(item)

    for item in new_items:
        if not item or not item.strip():
            continue
        norm = normalize_memory_item(item)
        if norm and norm not in seen_normalized:
            seen_normalized.add(norm)
            result.append(item)

    return result[:max_size]


# Maximum list sizes for each key_facts category
_MEMORY_LIST_LIMITS = {
    'likes': 30,
    'dislikes': 30,
    'personality_traits': 15,
    'important_memories': 20,
}


def _merge_profile_data(existing_memory: Dict, new_data: Dict) -> Dict:
    """Smart merge of existing profile data with new analysis"""
    if not existing_memory:
        return new_data
    
    result = existing_memory.copy()
    
    # Merge player summary - keep newer if significantly different
    if 'player_summary' in new_data and new_data['player_summary']:
        existing_summary = result.get('player_summary', '')
        new_summary = new_data['player_summary']
        
        # Keep the more detailed summary
        if len(new_summary) > len(existing_summary) * 1.5:  # New summary is 50% longer
            result['player_summary'] = new_summary
            print(f"[INFO] Updated player summary (new: {len(new_summary)} chars, old: {len(existing_summary)} chars)")
    
    # Merge relationship dynamics
    if 'relationship_dynamics' in new_data and new_data['relationship_dynamics']:
        result['relationship_dynamics'] = new_data['relationship_dynamics']
    
    # Merge key facts with normalization, deduplication, and size limits
    if 'key_facts' in new_data:
        if 'key_facts' not in result:
            result['key_facts'] = {
                'likes': [],
                'dislikes': [],
                'personality_traits': [],
                'important_memories': []
            }
        
        for category in ['likes', 'dislikes', 'personality_traits', 'important_memories']:
            existing_items = result['key_facts'].get(category, [])
            new_items = new_data['key_facts'].get(category, [])
            max_size = _MEMORY_LIST_LIMITS[category]
            
            existing_normalized = {normalize_memory_item(i) for i in existing_items if i and i.strip()}
            added = sum(1 for i in new_items if i and i.strip() and normalize_memory_item(i) not in existing_normalized)
            
            merged = merge_and_clean_memory(existing_items, new_items, max_size)
            result['key_facts'][category] = merged
            
            if added > 0:
                print(f"[INFO] Added {added} new items to {category}")
    
    # Update metadata
    result['last_global_summary'] = new_data.get('last_global_summary', '')
    result['sessions_analyzed'] = new_data.get('sessions_analyzed', 0)
    
    return result


def global_profile_analysis(prompt: str) -> Optional[str]:
    """Analyze conversation history using qwen with optimal settings"""
    api_key = Database.get_api_key("chutes")
    headers = {
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/icedeyes12/yuzu-companion", 
        "X-Title": "Yuzu-Global-Profile",
        "Authorization": f"Bearer {api_key}"
    }
    
    try:
        
        model = "Qwen/Qwen3-Next-80B-A3B-Instruct"
        
        # Optimize for long context analysis
        data = {
            "model": model,
            "messages": [
                {
                    "role": "system", 
                    "content": """You are an expert psychologist and data analyst specializing in conversation analysis. 
                    Your task is to extract deep, meaningful insights from conversation history.
                    
                    ANALYSIS APPROACH:
                    1. Read and comprehend the ENTIRE conversation history
                    2. Identify patterns, themes, and significant moments
                    3. Extract evidence-based insights about personality, preferences, and relationship dynamics
                    4. Be specific, concrete, and thorough
                    5. Follow the output format EXACTLY as specified
                    
                    Your analysis should be comprehensive, insightful, and directly based on the conversation evidence."""
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            "temperature": 0.2,  # Low temperature for consistent analysis
            "max_tokens": 4000,  
            "top_p": 0.9,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.1,
            "stream": False
        }
        
        response = requests.post(
            "https://llm.chutes.ai/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=300  # 5 minute timeout for large analysis
        )
        
        if response.status_code == 200:
            result = response.json()
            content = result['choices'][0]['message']['content'].strip()
            
            print(f"[SUCCESS] Analysis complete: {len(content):,} characters")
            return content
            
        else:
            error_msg = f"Chutes API error: {response.status_code}"
            
            try:
                error_data = response.json()
                error_detail = error_data.get('error', {}).get('message', 'Unknown')
                error_msg += f" - {error_detail}"
                
                print(f"[ERROR] {error_msg}")
                
                # Handle specific errors
                if "insufficient_quota" in error_detail.lower():
                    print("[ERROR] Insufficient API quota")
                    return _try_free_model(prompt, api_key)
                elif "model not found" in error_detail.lower():
                    print("[WARNING] GLM-4.7 not available, trying alternatives...")
                    return _try_alternative_models(prompt, api_key)
                    
            except Exception:
                error_msg += f" - {response.text[:200]}"
                print(f"[ERROR] {error_msg}")
            
            return None
            
    except requests.exceptions.Timeout:
        print("[ERROR] Request timeout - analysis took too long")
        return None
    except Exception as e:
        print(f"[ERROR] Analysis failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


def _try_alternative_models(prompt: str, api_key: str) -> Optional[str]:
    """Try alternative models if GLM-4.7 fails"""
    alternatives = [
        ("z-ai/glm-4.6", 8000),  # GLM-4.6
        ("qwen/qwen3-235b-a22b-2507", 6000),  # Qwen 3 235B
        ("deepseek/deepseek-chat-v3.1", 6000),  # DeepSeek V3.1
        ("tngtech/deepseek-r1t2-chimera", 4000),  # Chimera
        ("google/gemini-2.0-flash-exp:free", 4000),  # Gemini Flash (free)
    ]
    
    headers = {
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/icedeyes12/yuzu-companion", 
        "X-Title": "Yuzu-Global-Profile",
        "Authorization": f"Bearer {api_key}"
    }
    
    for model in alternatives:
        print(f"[INFO] Trying alternative model: {model}")
        
        try:
            # Potong prompt secara signifikan untuk model free
            shortened_prompt = prompt[:20000] + "\n\n...[prompt truncated for lighter model]"
            actual_prompt = shortened_prompt
            
            data = {
                "model": model,
                "messages": [
                    {
                        "role": "system", 
                        "content": "You are a conversation analyst. Extract comprehensive insights from the conversation history."
                    },
                    {
                        "role": "user", 
                        "content": actual_prompt
                    }
                ],
                "temperature": 0.2,
                "max_tokens": 2000,  # Free models have lower limits
                "top_p": 0.9,
                "stream": False
            }
            
            response = requests.post(
                "https://llm.chutes.ai/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=300
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content'].strip()
                print(f"[SUCCESS] Free model response: {len(content):,} chars")
                return content
                
        except Exception as e:
            print(f"[WARNING] Free model {model} error: {str(e)}")
            continue
    
    print("[ERROR] All free models failed")
    return None


def _try_free_model(prompt: str, api_key: str) -> Optional[str]:
    """Try free model if quota exhausted"""
    free_models = [
        "google/gemini-2.0-flash-exp:free",
        "deepseek/deepseek-chat-v3.1:free",
        "qwen/qwen3-235b-a22b:free",
    ]
    
    headers = {
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/icedeyes12/yuzu-companion", 
        "X-Title": "Yuzu-Global-Profile",
        "Authorization": f"Bearer {api_key}"
    }
    
    for model in free_models:
        print(f"[INFO] Trying free model: {model}")
        
        try:
            # Potong prompt secara signifikan untuk model free
            shortened_prompt = prompt[:15000] + "\n\n...[analysis limited due to free tier constraints]"
            
            data = {
                "model": model,
                "messages": [
                    {
                        "role": "system", 
                        "content": "Extract key insights from conversation history. Focus on most important patterns."
                    },
                    {
                        "role": "user", 
                        "content": shortened_prompt
                    }
                ],
                "temperature": 0.3,
                "max_tokens": 2000,  # Free models have lower limits
                "top_p": 0.9,
                "stream": False
            }
            
            response = requests.post(
                "https://llm.chutes.ai/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=300
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content'].strip()
                print(f"[SUCCESS] Free model response: {len(content):,} chars")
                return content
                
        except Exception as e:
            print(f"[WARNING] Free model {model} error: {str(e)}")
            continue
    
    print("[ERROR] All free models failed")
    return None


def parse_global_profile_summary(summary_text: str) -> Dict:
    """Parse the global profile summary text into structured data"""
    profile_data = {
        "player_summary": "",
        "key_facts": {
            "likes": [],
            "dislikes": [], 
            "personality_traits": [],
            "important_memories": []
        },
        "relationship_dynamics": "",
        "last_updated": datetime.now().isoformat()
    }
    
    # Clean the text
    cleaned_text = summary_text.replace('\r\n', '\n').replace('\r', '\n')
    
    # Normalize section headers
    section_patterns = {
        'Player Summary:': 'player_summary',
        'Player Summary': 'player_summary',
        'Summary:': 'player_summary',
        'Summary': 'player_summary',
        
        'Likes:': 'likes',
        'Likes': 'likes',
        'Interests:': 'likes',
        'Interests': 'likes',
        
        'Dislikes:': 'dislikes',
        'Dislikes': 'dislikes',
        'Aversions:': 'dislikes',
        
        'Personality Traits:': 'personality_traits',
        'Personality Traits': 'personality_traits',
        'Traits:': 'personality_traits',
        'Personality:': 'personality_traits',
        
        'Important Memories:': 'important_memories',
        'Important Memories': 'important_memories',
        'Memories:': 'important_memories',
        'Key Memories:': 'important_memories',
        
        'Relationship Dynamics:': 'relationship_dynamics',
        'Relationship Dynamics': 'relationship_dynamics',
        'Relationship:': 'relationship_dynamics',
        'Dynamics:': 'relationship_dynamics'
    }
    
    lines = cleaned_text.split('\n')
    current_section = None
    buffer = []
    
    def save_current_section():
        if current_section and buffer:
            content = ' '.join(buffer).strip()
            if current_section == 'player_summary':
                profile_data["player_summary"] = content
            elif current_section == 'relationship_dynamics':
                profile_data["relationship_dynamics"] = content
            elif current_section in ['likes', 'dislikes', 'personality_traits', 'important_memories']:
                # Parse comma-separated lists
                items = [item.strip() for item in content.split(',') if item.strip()]
                profile_data["key_facts"][current_section] = items
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Check if this line starts a new section
        section_found = False
        for pattern, section_key in section_patterns.items():
            if line.startswith(pattern):
                # Save previous section
                save_current_section()
                
                # Start new section
                current_section = section_key
                buffer = []
                
                # Remove the pattern from the line
                remaining = line[len(pattern):].strip()
                if remaining:
                    buffer.append(remaining)
                
                section_found = True
                break
        
        if not section_found and current_section:
            # Continue current section
            buffer.append(line)
    
    # Save the last section
    save_current_section()
    
    # Clean up the data
    for section in ['player_summary', 'relationship_dynamics']:
        if profile_data[section]:
            # Remove any trailing punctuation
            profile_data[section] = profile_data[section].strip()
            if profile_data[section].endswith('.'):
                profile_data[section] = profile_data[section][:-1]
    
    # Clean lists
    for key in ['likes', 'dislikes', 'personality_traits', 'important_memories']:
        if profile_data["key_facts"][key]:
            # Remove duplicates and empty items
            unique_items = []
            seen = set()
            for item in profile_data["key_facts"][key]:
                if item and item not in seen:
                    seen.add(item)
                    unique_items.append(item)
            profile_data["key_facts"][key] = unique_items
    
    return profile_data


def get_available_providers():
    ai_manager = get_ai_manager()
    return ai_manager.get_available_providers()


def get_all_models():
    ai_manager = get_ai_manager()
    return ai_manager.get_all_models()


def set_preferred_provider(provider_name, model_name=None):
    profile = Database.get_profile()
    providers_config = profile.get('providers_config', {})
    providers_config['preferred_provider'] = provider_name
    if model_name:
        providers_config['preferred_model'] = model_name

    Database.update_profile({'providers_config': providers_config})

    # Reload AI manager to detect newly available providers (e.g., after adding API keys)
    reload_ai_manager()

    return f"Preferred provider set to: {provider_name}" + (f" with model: {model_name}" if model_name else "")


def set_vision_model(provider, model):
    """Save user's vision model preference to profile.
    
    Args:
        provider: Vision provider (e.g., 'chutes', 'openrouter')
        model: Vision model name (e.g., 'Qwen/Qwen3.5-397B-A17B-TEE')
    
    Returns:
        str: Confirmation message
    """
    profile = Database.get_profile()
    providers_config = profile.get('providers_config', {})
    providers_config['vision_model_preferences'] = {'provider': provider, 'model': model}
    Database.update_profile({'providers_config': providers_config})
    
    return f"Vision model set to: {provider}/{model}"


def get_provider_models(provider_name):
    ai_manager = get_ai_manager()
    return ai_manager.get_provider_models(provider_name)


def get_vision_capabilities():
    from app.tools import multimodal_tools
    
    capabilities = {
        'has_vision': False,
        'vision_provider': None,
        'vision_model': None,
        'has_image_generation': False,
        'image_generation_provider': None
    }
    
    vision_provider, vision_model = multimodal_tools.get_best_vision_provider()
    if vision_provider:
        capabilities['has_vision'] = True
        capabilities['vision_provider'] = vision_provider
        capabilities['vision_model'] = vision_model
    
    api_keys = Database.get_api_keys()
    if 'openrouter' in api_keys:
        capabilities['has_image_generation'] = True
        capabilities['image_generation_provider'] = 'openrouter'
    
    return capabilities


# ═════════════════════════════════════════════════════════════════════════════
# ASYNC FUNCTIONS (for FastAPI web routes)
# ═════════════════════════════════════════════════════════════════════════════

async def retrieve_memory_context_async(session_id: int, user_message: str | None = None) -> tuple[list[int], str]:
    """Async version of memory context retrieval for web routes.
    
    Uses async memory functions for non-blocking operation in FastAPI.
    
    Returns:
        (static_ids, memory_context_text)
    """
    from app.memory.retrieval import retrieve_for_context_async
    
    try:
        static_ids, memory_context_text = await retrieve_for_context_async(session_id, query=user_message)
        return static_ids, memory_context_text
    except Exception as e:
        print(f"[WARNING] Async memory retrieval failed: {e}")
        return [], ""


async def mark_pending_review_async(static_ids: list[int], session_id: int) -> None:
    """Async wrapper for marking facts as pending review."""
    # This is still sync internally, but we run it in executor for non-blocking
    import asyncio
    from app.memory.memory_review import mark_retrieved_as_pending_review
    
    if not static_ids:
        return
    
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, mark_retrieved_as_pending_review, static_ids, session_id)