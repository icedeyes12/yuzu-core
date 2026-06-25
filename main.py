from __future__ import annotations
# FILE: web.py
# DESCRIPTION: FastAPI web interface for yuzu-companion


from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os

# Import psycopg errors for exception handling
from psycopg_pool import PoolTimeout
from psycopg import OperationalError

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BASE_DIR, ".env"))

from app.db import Database  # noqa: E402
from app.db.connection import get_sync_pool, get_async_pool, close_async_pool  # noqa: E402
from app.api import api_router  # noqa: E402
from app.api.utils import get_current_user  # noqa: E402
from app.services.session_service import SessionService  # noqa: E402, F401
from app.logging_config import get_logger  # noqa: E402

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# FastAPI Lifespan — Database Pool Management
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage DB pool lifecycle explicitly (startup → shutdown)."""
    # ── STARTUP ─────────────────────────────────────────────────────
    log.info("Starting Yuzu Companion...")

    # Initialize pools explicitly (no lazy init)
    sync_pool = get_sync_pool()
    async_pool = await get_async_pool()

    # Health check
    try:
        async with async_pool.connection() as conn:
            await conn.execute("SELECT 1")
        log.info("Database health check passed")
    except Exception as e:
        log.critical("Database unavailable: %s", e)
        raise

    # Store pools in app state
    app.state.sync_pool = sync_pool
    app.state.async_pool = async_pool

    log.info("Startup complete")

    yield  # ── RUNTIME ──────────────────────────────────────────────

    # ── SHUTDOWN ───────────────────────────────────────────────────
    log.info("Shutting down...")

    try:
        await close_async_pool()
        log.info("Database pools closed")
    except Exception as e:
        log.error("Error closing pools: %s", e)

    log.info("Shutdown complete")


# ---------------------------------------------------------------------------
# FastAPI Application Setup
# ---------------------------------------------------------------------------


app = FastAPI(
    title="Yuzu Companion",
    description="AI companion system with memory, multimodal, and multi-provider support",
    version="1.0.0",
    lifespan=lifespan,
    # Disable default exception handlers for DB errors
    exception_handlers={
        PoolTimeout: None,  # Will be added below
        OperationalError: None,
    },
)


# ---------------------------------------------------------------------------
# Database Offline Handler
# ---------------------------------------------------------------------------


def _render_offline_page() -> str:
    """Read and return the offline.html template."""
    offline_path = os.path.join(BASE_DIR, "templates", "offline.html")
    if os.path.exists(offline_path):
        with open(offline_path, "r") as f:
            return f.read()
    # Fallback inline HTML
    return """
    <!DOCTYPE html>
    <html><head><title>Database Offline</title></head>
    <body style="background:#1a1a2e;color:#e0e0e0;display:flex;align-items:center;justify-content:center;min-height:100vh;font-family:sans-serif;">
    <div style="text-align:center;">
    <h1 style="color:#ff69b4;">⚡ Database Offline</h1>
    <p>PostgreSQL is not reachable. Start the database and try again.</p>
    <a href="/" style="background:#ff69b4;color:white;padding:0.8rem 2rem;border-radius:25px;text-decoration:none;">Retry</a>
    </div></body></html>
    """


@app.exception_handler(PoolTimeout)
async def pool_timeout_handler(request: Request, exc: PoolTimeout):
    """Handle database pool timeout - show offline page."""
    return HTMLResponse(content=_render_offline_page(), status_code=503)


@app.exception_handler(OperationalError)
async def operational_error_handler(request: Request, exc: OperationalError):
    """Handle database connection errors - show offline page."""
    return HTMLResponse(content=_render_offline_page(), status_code=503)


# Mount static directories
app.mount(
    "/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static"
)
app.mount(
    "/uploads",
    StaticFiles(directory=os.path.join(BASE_DIR, "static/uploads")),
    name="uploads",
)
app.mount(
    "/generated_images",
    StaticFiles(directory=os.path.join(BASE_DIR, "static/generated_images")),
    name="generated_images",
)


# Jinja2 templates
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


def ensure_static_dirs():
    static_dirs = [
        os.path.join(BASE_DIR, "static/uploads"),
        os.path.join(BASE_DIR, "static/generated_images"),
        os.path.join(BASE_DIR, "static/image_cache"),
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
async def home(request: Request, user_id: str = Depends(get_current_user)):
    profile = await Database.get_profile_async(user_id)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"profile": profile, "current_page": "home"},
    )


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request, user_id: str = Depends(get_current_user)):
    profile = await Database.get_profile_async(user_id)
    return templates.TemplateResponse(
        request=request,
        name="chat.html",
        context={"profile": profile, "current_page": "chat"},
    )


@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request, user_id: str = Depends(get_current_user)):
    profile = await Database.get_profile_async(user_id)
    return templates.TemplateResponse(
        request=request,
        name="config.html",
        context={"profile": profile, "current_page": "config"},
    )


@app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request, user_id: str = Depends(get_current_user)):
    profile = await Database.get_profile_async(user_id)
    return templates.TemplateResponse(
        request=request,
        name="about.html",
        context={"profile": profile, "current_page": "about"},
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
