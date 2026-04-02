# FILE: web.py
# DESCRIPTION: FastAPI web interface for AI companion system

from fastapi import FastAPI, Request, HTTPException, Form, File, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from datetime import datetime
import json
import os

from app.app import (
    handle_user_message, handle_user_message_streaming, start_session,
    end_session_cleanup, summarize_memory, summarize_global_player_profile,
    set_preferred_provider, get_vision_capabilities
)
from app.database import Database
from app.providers import get_ai_manager

# ---------------------------------------------------------------------------
# FastAPI Application Setup
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(
    title="Yuzu Companion",
    description="AI companion system with memory, multimodal, and multi-provider support",
    version="1.0.0"
)

# Mount static directories
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
app.mount("/uploads", StaticFiles(directory=os.path.join(BASE_DIR, "static/uploads")), name="uploads")
app.mount("/generated_images", StaticFiles(directory=os.path.join(BASE_DIR, "static/generated_images")), name="generated_images")

# Jinja2 templates
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Simple in-memory session tracking (replaces Flask signed cookies)
_web_session_tracker: Dict[str, bool] = {}


def ensure_static_dirs():
    static_dirs = [
        os.path.join(BASE_DIR, 'static/uploads'),
        os.path.join(BASE_DIR, 'static/generated_images'),
        os.path.join(BASE_DIR, 'static/image_cache')
    ]
    for dir_path in static_dirs:
        os.makedirs(dir_path, exist_ok=True)


def _get_session_id(request: Request) -> str:
    client_host = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    return f"{client_host}_{hash(user_agent) % 10000}"


ensure_static_dirs()

# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class MessageRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User message text")


class StreamMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User message text")
    provider: Optional[str] = Field(None, description="AI provider to use")
    model: Optional[str] = Field(None, description="AI model to use")


class ApiKeyRequest(BaseModel):
    key_name: str = Field(..., min_length=1, description="Name for the API key")
    api_key: str = Field(..., min_length=1, description="The API key value")


class ChutesKeyRequest(BaseModel):
    api_key: str = Field(..., min_length=1, description="Chutes API key value")


class SessionCreateRequest(BaseModel):
    name: str = Field(default="New Chat", min_length=1, description="Session name")


class SessionSwitchRequest(BaseModel):
    session_id: int = Field(..., gt=0, description="Session ID to switch to")


class SessionRenameRequest(BaseModel):
    session_id: int = Field(..., gt=0, description="Session ID to rename")
    name: str = Field(..., min_length=1, description="New session name")


class SessionDeleteRequest(BaseModel):
    session_id: int = Field(..., gt=0, description="Session ID to delete")


class ProviderSetRequest(BaseModel):
    provider_name: str = Field(..., min_length=1, description="AI provider name")
    model_name: Optional[str] = Field(None, description="Optional model name")


class ProviderTestRequest(BaseModel):
    provider_name: str = Field(..., min_length=1, description="Provider name to test")


class LocationUpdateRequest(BaseModel):
    lat: float = Field(..., description="Latitude")
    lon: float = Field(..., description="Longitude")


class GlobalKnowledgeUpdateRequest(BaseModel):
    facts: str = Field(..., description="Global knowledge facts")


# ---------------------------------------------------------------------------
# HTML Page Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    profile = Database.get_profile()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"profile": profile}
    )


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    session_id = _get_session_id(request)
    
    if not _web_session_tracker.get(session_id):
        print(f"Web session not found for {session_id}, starting new web session...")
        start_session(interface="web")
        _web_session_tracker[session_id] = True
        print("Web session started and flagged.")
    
    profile = Database.get_profile()
    return templates.TemplateResponse(
        request=request,
        name="chat.html",
        context={"profile": profile}
    )


@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    profile = Database.get_profile()
    return templates.TemplateResponse(
        request=request,
        name="config.html",
        context={"profile": profile}
    )


@app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    profile = Database.get_profile()
    return templates.TemplateResponse(
        request=request,
        name="about.html",
        context={"profile": profile}
    )


@app.get("/static/html/sidebar.html", response_class=HTMLResponse)
async def serve_sidebar():
    sidebar_path = os.path.join(BASE_DIR, "templates", "sidebar.html")
    if os.path.exists(sidebar_path):
        with open(sidebar_path, "r") as f:
            return HTMLResponse(f.read())
    
    fallback = """<div class="sidebar" id="mainSidebar">
        <div class="sidebar-header"><h2>Yuzu Companion</h2></div>
        <div class="sidebar-content">
            <a href="/">Home</a>
            <a href="/chat">Chat</a>
            <a href="/config">Config</a>
            <a href="/about">About</a>
        </div>
    </div>"""
    return HTMLResponse(fallback)


# ---------------------------------------------------------------------------
# API Routes - Profile & Chat
# ---------------------------------------------------------------------------

@app.get("/api/get_profile")
async def api_get_profile():
    try:
        profile = Database.get_profile()
        active_session = Database.get_active_session()
        chat_history = Database.get_chat_history(session_id=active_session["id"], limit=None)
        session_memory = Database.get_session_memory(active_session["id"])
        
        ai_manager = get_ai_manager()
        available_providers = ai_manager.get_available_providers()
        all_models = ai_manager.get_all_models()
        
        providers_config = profile.get("providers_config", {})
        current_provider = providers_config.get("preferred_provider", "ollama")
        current_model = providers_config.get("preferred_model", "glm-4.6:cloud")
        
        api_keys = Database.get_api_keys()
        vision_capabilities = get_vision_capabilities()
        
        # Convert datetime objects to strings for JSON serialization
        profile_dict = {
            "id": profile["id"],
            "display_name": profile["display_name"],
            "partner_name": profile["partner_name"],
            "affection": profile["affection"],
            "theme": profile["theme"],
            "memory": profile["memory"],
            "session_history": profile["session_history"],
            "global_knowledge": profile["global_knowledge"],
            "providers_config": profile["providers_config"],
            "context": profile["context"],
            "image_model": profile["image_model"],
            "vision_model": profile["vision_model"],
            "created_at": profile["created_at"].isoformat() if profile["created_at"] else None,
            "updated_at": profile["updated_at"].isoformat() if profile["updated_at"] else None,
        }
        
        return {
            **profile_dict,
            "chat_history": chat_history,
            "api_keys": api_keys,
            "active_session": active_session,
            "session_memory": session_memory,
            "ai_providers": {
                "available_providers": available_providers,
                "all_models": all_models,
                "current_provider": current_provider,
                "current_model": current_model
            },
            "multimodal_capabilities": vision_capabilities
        }
    except Exception as e:
        print(f"Error in api_get_profile: {e}")
        raise HTTPException(status_code=500, detail="Failed to load profile")


@app.post("/api/send_message")
async def api_send_message(request: MessageRequest):
    try:
        user_message = request.message.strip()
        
        if not user_message:
            return {"reply": "Please type a message!"}
        
        print(f"Web message: {user_message[:200]}...")
        
        active_session = Database.get_active_session()
        _ = active_session["id"]
        
        ai_reply = handle_user_message(user_message, interface="web")
        
        print(f"AI reply: {ai_reply}")
        
        return {"reply": ai_reply}
        
    except Exception as e:
        print(f"Error in api_send_message: {e}")
        import traceback
        traceback.print_exc()
        return {"reply": "Sorry, I encountered an error processing your message."}


@app.post("/api/send_message_stream")
async def api_send_message_stream(request: StreamMessageRequest):
    try:
        user_message = request.message.strip()
        
        if not user_message:
            async def empty_generator():
                yield 'data: {"chunk": "Please type a message!"}\n\n'
            return StreamingResponse(empty_generator(), media_type="text/event-stream")
        
        print(f"Streaming message: {user_message[:200]}...")
        
        # Get streaming response generator from app.py
        response_generator = handle_user_message_streaming(
            user_message,
            interface="web",
            provider=request.provider,
            model=request.model
        )
        
        def generate():
            for chunk in response_generator:
                if chunk:
                    escaped_chunk = json.dumps(chunk)
                    yield f'data: {{"chunk": {escaped_chunk}}}\n\n'
        
        return StreamingResponse(generate(), media_type="text/event-stream")
        
    except Exception as e:
        print(f"Error in streaming: {e}")
        import traceback
        traceback.print_exc()
        
        def generate_error():
            yield 'data: {"chunk": "Sorry, I encountered an error processing your message."}\n\n'
        
        return StreamingResponse(generate_error(), media_type="text/event-stream")


@app.post("/api/send_message_with_images")
async def api_send_message_with_images(
    request: Request,
    message: str = Form(""),
    images: List[UploadFile] = File(default=[])
):
    try:
        message_text = message.strip()
        
        if not message_text and not images:
            return {"reply": "Please provide a message or images!"}
        
        print(f"Processing message with {len(images)} images")
        
        active_session = Database.get_active_session()
        _ = active_session["id"]
        
        saved_images = []
        image_markdowns = []
        
        for i, image_file in enumerate(images):
            if image_file and image_file.filename:
                uploads_dir = "static/uploads"
                os.makedirs(uploads_dir, exist_ok=True)
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_filename = "".join(c for c in image_file.filename if c.isalnum() or c in ('.', '-', '_')).rstrip()
                filename = f"{timestamp}_{i}_{safe_filename}"
                filepath = os.path.join(uploads_dir, filename)
                
                # Save uploaded file
                content = await image_file.read()
                with open(filepath, "wb") as f:
                    f.write(content)
                
                web_url = f"/uploads/{filename}"
                image_markdown = f"![Uploaded Image](uploads/{filename})"
                image_markdowns.append(image_markdown)
                
                saved_images.append({
                    "web_url": web_url,
                    "filepath": filepath,
                    "markdown": image_markdown
                })
                print(f"Saved image to static: {filepath}")
        
        if image_markdowns:
            final_user_message = f"{message_text}\n\n" + "\n".join(image_markdowns) if message_text else "\n".join(image_markdowns)
        else:
            final_user_message = message_text
        
        print(f"Final user message: {final_user_message[:200]}...")
        
        ai_reply = handle_user_message(final_user_message, interface="web")
        
        return {
            "reply": ai_reply,
            "uploaded_images": saved_images
        }
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return {"reply": "Error processing message."}


@app.post("/api/generate_image")
async def api_generate_image(request: MessageRequest):
    """Image generation now uses /api/send_message. Redirect for backwards compat."""
    try:
        prompt = request.message.strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="Prompt required")
        
        # Route through the unified send_message pipeline
        ai_reply = handle_user_message(f"/imagine {prompt}", interface="web")
        return {"reply": ai_reply, "status": "success"}
    except Exception as e:
        print(f"Error generating image: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/static/uploads/{filename}")
async def serve_uploaded_image(filename: str):
    try:
        uploads_dir = os.path.abspath(os.path.join(BASE_DIR, "static", "uploads"))
        file_path = os.path.abspath(os.path.normpath(os.path.join(uploads_dir, filename)))
        if not file_path.startswith(uploads_dir + os.sep):
            raise HTTPException(status_code=404, detail="Image not found")
        if os.path.exists(file_path):
            return FileResponse(file_path)
        raise HTTPException(status_code=404, detail="Image not found")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")


@app.get("/static/generated_images/{filename}")
async def serve_generated_image(filename: str):
    try:
        generated_dir = os.path.abspath(os.path.join(BASE_DIR, "static", "generated_images"))
        file_path = os.path.abspath(os.path.normpath(os.path.join(generated_dir, filename)))
        if not file_path.startswith(generated_dir + os.sep):
            raise HTTPException(status_code=404, detail="Image not found")
        if os.path.exists(file_path):
            return FileResponse(file_path)
        raise HTTPException(status_code=404, detail="Image not found")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")


@app.get("/api/get_vision_capabilities")
async def api_get_vision_capabilities():
    try:
        capabilities = get_vision_capabilities()
        return {
            "status": "success",
            "capabilities": capabilities
        }
    except Exception as e:
        print(f"Error getting vision capabilities: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/update_profile")
async def api_update_profile(request: Request):
    try:
        updates = await request.json()
        Database.update_profile(updates)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/clear_chat")
async def api_clear_chat(request: Request):
    try:
        active_session = Database.get_active_session()
        session_id = active_session["id"]
        
        Database.clear_chat_history(session_id)
        
        # Reset session flag
        client_id = _get_session_id(request)
        _web_session_tracker.pop(client_id, None)
        
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/end_session")
async def api_end_session(request: Request):
    try:
        # Reset session flag
        client_id = _get_session_id(request)
        _web_session_tracker.pop(client_id, None)
        
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        profile = Database.get_profile()
        
        session_history = profile.get("session_history", {})
        current_session = session_history.get("current_session", {})
        start_time = current_session.get("start_time")
        duration = 0
        
        if start_time:
            try:
                start = datetime.fromisoformat(start_time)
                duration = (datetime.now() - start).total_seconds() / 60
            except Exception:
                pass
        
        disconnect_msg = (
            f"*{profile['display_name']} disconnected from web interface at {current_time}. "
            f"Session duration: {duration:.1f} minutes*"
        )
        
        Database.add_message("system", disconnect_msg)
        end_session_cleanup(profile, interface="web", unexpected_exit=False)
        return {"status": "session ended"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# API Routes - API Keys
# ---------------------------------------------------------------------------

@app.post("/api/add_api_key")
async def api_add_api_key(request: ApiKeyRequest):
    if not request.api_key or not request.key_name:
        return {"status": "error", "message": "Key name and API key required"}
    
    if Database.add_api_key(request.key_name, request.api_key):
        return {"status": "success", "message": f"{request.key_name} API key added"}
    else:
        return {"status": "error", "message": "API key already exists or failed to save"}


@app.post("/api/add_chutes_key")
async def api_add_chutes_key(request: ChutesKeyRequest):
    try:
        api_key = request.api_key.strip()
        
        if not api_key:
            return {"status": "error", "message": "Chutes API key required"}
        
        if Database.add_api_key("chutes", api_key):
            return {"status": "success", "message": "Chutes API key added successfully!"}
        else:
            return {"status": "error", "message": "Failed to save Chutes API key"}
    except Exception as e:
        print(f"Error adding Chutes API key: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/remove_api_key")
async def api_remove_api_key(request: Request):
    try:
        data = await request.json()
        key_name = data.get("key_name", "").strip()
        
        if not key_name:
            return {"status": "error", "message": "Key name required"}
        
        if Database.remove_api_key(key_name):
            return {"status": "success", "message": f"{key_name} API key removed"}
        else:
            return {"status": "error", "message": "API key not found"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# API Routes - Memory & Context
# ---------------------------------------------------------------------------

@app.post("/api/update_session_context")
async def api_update_session_context():
    try:
        active_session = Database.get_active_session()
        session_id = active_session["id"]
        profile = Database.get_profile()
        
        chat_history = Database.get_chat_history(session_id=session_id)
        
        if len(chat_history) < 5:
            return {"status": "error", "message": "Need at least 5 conversation messages"}
        
        last_user_msg = next((msg for msg in reversed(chat_history) if msg["role"] == "user"), None)
        last_ai_reply = next((msg for msg in reversed(chat_history) if msg["role"] == "assistant"), None)
        
        if last_user_msg and last_ai_reply:
            success = summarize_memory(profile, last_user_msg["content"], last_ai_reply["content"], session_id)
            
            if success:
                session_memory = Database.get_session_memory(session_id)
                return {
                    "status": "success",
                    "message": "Session context updated!",
                    "session_memory": session_memory
                }
            else:
                return {"status": "error", "message": "Session context update failed"}
        else:
            return {"status": "error", "message": "Need conversation history"}
            
    except Exception as e:
        print(f"Error updating session context: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/update_global_profile")
async def api_update_global_profile():
    try:
        success = summarize_global_player_profile()
        
        if success:
            profile = Database.get_profile()
            print(f"Returning updated profile with memory: {profile.get('memory', {})}")
            
            return {
                "status": "success",
                "message": "Global player profile updated from ALL sessions!",
                "profile": profile
            }
        else:
            return {"status": "error", "message": "Global profile analysis failed"}
    except Exception as e:
        print(f"Error updating global profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/rebuild_structured_memory")
async def api_rebuild_structured_memory():
    """Rebuild structured memory from current session messages."""
    try:
        active_session = Database.get_active_session()
        session_id = active_session["id"]

        from app.memory.extractor import process_messages_for_memory
        from app.memory.segmenter import segment_session

        # Extract semantic + episodic memories from recent messages
        recent = Database.get_chat_history(session_id=session_id, limit=50, recent=True)
        if len(recent) < 3:
            return {
                "status": "error",
                "message": "Need at least 3 conversation messages to extract memory. Continue chatting and try again."
            }

        process_messages_for_memory(session_id, recent)

        # Create conversation segments
        segment_session(session_id)

        # Get current memory stats
        from app.database import get_db_session, SemanticMemory, EpisodicMemory, ConversationSegment
        with get_db_session() as db_session:
            semantic_count = db_session.query(SemanticMemory).filter_by(session_id=session_id).count()
            episodic_count = db_session.query(EpisodicMemory).filter_by(session_id=session_id).count()
            segment_total = db_session.query(ConversationSegment).filter_by(session_id=session_id).count()

        return {
            "status": "success",
            "message": f"Structured memory rebuilt: {semantic_count} facts, {episodic_count} episodes, {segment_total} segments",
            "stats": {
                "semantic": semantic_count,
                "episodic": episodic_count,
                "segments": segment_total,
            }
        }
    except Exception as e:
        print(f"Error rebuilding structured memory: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/run_memory_decay")
async def api_run_memory_decay():
    """Run FSRS memory decay on current session."""
    try:
        active_session = Database.get_active_session()
        session_id = active_session["id"]

        from app.memory.review import run_decay
        run_decay(session_id)

        return {
            "status": "success",
            "message": "Memory decay applied. Old memories faded, recent ones preserved."
        }
    except Exception as e:
        print(f"Error running memory decay: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/memory_stats")
async def api_memory_stats():
    """Get structured memory statistics for the current session."""
    try:
        active_session = Database.get_active_session()
        session_id = active_session["id"]

        from app.database import get_db_session, SemanticMemory, EpisodicMemory, ConversationSegment
        with get_db_session() as db_session:
            semantic_count = db_session.query(SemanticMemory).filter_by(session_id=session_id).count()
            episodic_count = db_session.query(EpisodicMemory).filter_by(session_id=session_id).count()
            segment_count = db_session.query(ConversationSegment).filter_by(session_id=session_id).count()

            # Get top semantic facts for display
            top_facts = db_session.query(SemanticMemory).filter_by(
                session_id=session_id
            ).order_by(SemanticMemory.confidence.desc()).limit(10).all()

            facts_list = [
                f"{f.entity} {f.relation} {f.target}"
                for f in top_facts
            ]

        return {
            "status": "success",
            "stats": {
                "semantic": semantic_count,
                "episodic": episodic_count,
                "segments": segment_count,
                "top_facts": facts_list,
            }
        }
    except Exception as e:
        print(f"Error getting memory stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# API Routes - Provider Management
# ---------------------------------------------------------------------------

@app.get("/api/providers/list")
async def api_list_providers():
    try:
        ai_manager = get_ai_manager()
        available_providers = ai_manager.get_available_providers()
        all_models = ai_manager.get_all_models()
        
        profile = Database.get_profile()
        providers_config = profile.get("providers_config", {})
        current_provider = providers_config.get("preferred_provider", "ollama")
        current_model = providers_config.get("preferred_model", "glm-4.6:cloud")
        
        return {
            "status": "success",
            "available_providers": available_providers,
            "all_models": all_models,
            "current_provider": current_provider,
            "current_model": current_model
        }
    except Exception as e:
        print(f"Error listing providers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/providers/set_preferred")
async def api_set_preferred_provider(request: ProviderSetRequest):
    try:
        if not request.provider_name:
            return {"status": "error", "message": "Provider name required"}
        
        result = set_preferred_provider(request.provider_name, request.model_name)
        
        return {
            "status": "success",
            "message": result
        }
    except Exception as e:
        print(f"Error setting preferred provider: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/providers/test_connection")
async def api_test_provider_connection(request: ProviderTestRequest):
    try:
        if not request.provider_name:
            return {"status": "error", "message": "Provider name required"}
        
        ai_manager = get_ai_manager()
        provider = ai_manager.providers.get(request.provider_name)
        
        if not provider:
            return {
                "status": "error",
                "message": f"Provider {request.provider_name} not found"
            }
        
        is_connected = provider.test_connection()
        
        return {
            "status": "success",
            "provider": request.provider_name,
            "connected": is_connected,
            "message": f'{request.provider_name}: {"Connected" if is_connected else "Connection failed"}'
        }
    except Exception as e:
        print(f"Error testing provider connection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/browser_unload")
async def api_browser_unload(request: Request):
    """Handle browser page unload/reload events."""
    try:
        # Reset session flag
        client_id = _get_session_id(request)
        _web_session_tracker.pop(client_id, None)
        print("Web page closed or refreshed - session cleared")
        
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        profile = Database.get_profile()
        
        session_history = profile.get("session_history", {})
        current_session = session_history.get("current_session", {})
        start_time = current_session.get("start_time")
        duration = 0
        
        if start_time:
            try:
                start = datetime.fromisoformat(start_time)
                duration = (datetime.now() - start).total_seconds() / 60
            except Exception:
                pass
        
        disconnect_msg = (
            f"*{profile['display_name']} disconnected unexpectedly from web interface at {current_time}. "
            f"Session duration: {duration:.1f} minutes*"
        )
        
        Database.add_message("system", disconnect_msg)
        end_session_cleanup(profile, interface="web", unexpected_exit=True)
        
        return {"status": "page closed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# API Routes - Session Management
# ---------------------------------------------------------------------------

@app.get("/api/sessions/list")
async def api_list_sessions():
    try:
        sessions = Database.get_all_sessions()
        return {"sessions": sessions}
    except Exception as e:
        print(f"Error listing sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sessions/create")
async def api_create_session(http_request: Request, request: SessionCreateRequest):
    try:
        session_id = Database.create_session(request.name)
        Database.switch_session(session_id)
        
        # Reset session flag
        client_id = _get_session_id(http_request)
        _web_session_tracker.pop(client_id, None)
        
        return {"status": "success", "session_id": session_id}
    except Exception as e:
        print(f"Error creating session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sessions/switch")
async def api_switch_session(request: SessionSwitchRequest, http_request: Request):
    try:
        if not request.session_id:
            raise HTTPException(status_code=400, detail="session_id required")
        
        Database.switch_session(request.session_id)
        
        # Reset session flag
        client_id = _get_session_id(http_request)
        _web_session_tracker.pop(client_id, None)
        
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        profile = Database.get_profile()
        
        all_sessions = Database.get_all_sessions()
        session_count = len(all_sessions)
        
        connection_msg = (
            f"*{profile['display_name']} connected to web interface at {current_time}. "
            f"Switched to session #{[s['id'] for s in all_sessions].index(request.session_id) + 1} of {session_count}*"
        )
        
        Database.add_message("system", connection_msg, session_id=request.session_id)
        
        # Set session flag for the new session
        _web_session_tracker[client_id] = True
        
        chat_history = Database.get_chat_history(session_id=request.session_id)
        session_memory = Database.get_session_memory(session_id=request.session_id)
        
        return {
            "status": "success",
            "session_id": request.session_id,
            "chat_history": chat_history,
            "session_memory": session_memory
        }
    except Exception as e:
        print(f"Error switching session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sessions/rename")
async def api_rename_session(request: SessionRenameRequest):
    try:
        if not request.session_id or not request.name:
            raise HTTPException(status_code=400, detail="session_id and name required")
        
        success = Database.rename_session(request.session_id, request.name)
        
        if success:
            return {"status": "success"}
        else:
            raise HTTPException(status_code=404, detail="Session not found")
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error renaming session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sessions/delete")
async def api_delete_session(request: SessionDeleteRequest):
    try:
        if not request.session_id:
            raise HTTPException(status_code=400, detail="session_id required")
        
        success = Database.delete_session(request.session_id)
        
        if success:
            active_session = Database.get_active_session()
            chat_history = Database.get_chat_history()
            session_memory = Database.get_session_memory(active_session["id"])
            
            return {
                "status": "success",
                "active_session": active_session,
                "chat_history": chat_history,
                "session_memory": session_memory
            }
        else:
            raise HTTPException(status_code=404, detail="Session not found")
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sessions/{session_id}/memory")
async def api_get_session_memory(session_id: int):
    try:
        session_memory = Database.get_session_memory(session_id)
        return {
            "status": "success",
            "session_id": session_id,
            "session_context": session_memory.get("session_context", ""),
            "last_summarized": session_memory.get("last_summarized", "Never")
        }
    except Exception as e:
        print(f"Error getting session memory: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# API Routes - Location & Global Knowledge
# ---------------------------------------------------------------------------

@app.post("/api/update_location")
async def api_update_location(request: LocationUpdateRequest):
    try:
        context = Database.get_context()
        context["location"] = {"lat": request.lat, "lon": request.lon}
        Database.update_context(context)
        return {"status": "ok"}
    except Exception as e:
        print(f"Error updating location: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/update_weather_location")
async def api_update_weather_location(request: LocationUpdateRequest):
    try:
        context = Database.get_context()
        context["location"] = {"lat": request.lat, "lon": request.lon}
        Database.update_context(context)
        return {"status": "success", "message": "Weather location updated"}
    except Exception as e:
        print(f"Error updating weather location: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/global_knowledge/update")
async def api_update_global_knowledge(request: GlobalKnowledgeUpdateRequest):
    try:
        global_knowledge = {"facts": request.facts}
        Database.update_profile({"global_knowledge": global_knowledge})
        return {"status": "success", "message": "Global knowledge updated"}
    except Exception as e:
        print(f"Error updating global knowledge: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000, log_level="info")
