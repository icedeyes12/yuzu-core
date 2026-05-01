from __future__ import annotations
# FILE: web.py
# DESCRIPTION: FastAPI web interface for yuzu-companion


from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Dict
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, ".env"))

from app.app import start_session  # noqa: E402
from app.database import Database  # noqa: E402
from app.api import api_router  # noqa: E402
from app.api.routes import set_session_tracker  # noqa: E402

# ---------------------------------------------------------------------------
# FastAPI Application Setup
# ---------------------------------------------------------------------------


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


# In-memory session tracking
_web_session_tracker: Dict[str, bool] = {}


# Share session tracker with API routes
set_session_tracker(_web_session_tracker)



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
# Register API Router
# ---------------------------------------------------------------------------


app.include_router(api_router, prefix="/api")

# ---------------------------------------------------------------------------
# Favicon
# ---------------------------------------------------------------------------


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(os.path.join(BASE_DIR, "static", "favicon.ico"))

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
# Main Entry Point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000, log_level="info")
