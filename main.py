from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from psycopg import OperationalError

# Import psycopg errors for exception handling
from psycopg_pool import PoolTimeout
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BASE_DIR, ".env"))

from fastapi import HTTPException  # noqa: E402

from app.api import api_router  # noqa: E402
from app.api.endpoints.health import router as health_router  # noqa: E402
from app.api.errors import (  # noqa: E402
    http_exception_handler,
    problem_detail,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.auth.session import SESSION_COOKIE_NAME, validate_session  # noqa: E402
from app.core.logging_config import get_logger  # noqa: E402
from app.db import Database, init_pg_tables_async  # noqa: E402
from app.db.connection import (  # noqa: E402
    close_async_pool,
    get_async_pool,
    get_sync_pool,
)
from app.metrics import metrics  # noqa: E402
from app.services.session_service import SessionService  # noqa: E402, F401

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

    # Run schema bootstrap before health check so missing columns are repaired
    # during startup instead of failing later on first query.
    # Schema verification is performed by init_pg_tables_async; deploy-time DDL
    # is intentionally not run under the application role.
    await init_pg_tables_async()

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
    docs_url=None,
    redoc_url=None,
    # Disable default exception handlers for DB errors
    exception_handlers={  # pyright: ignore[reportArgumentType]
        PoolTimeout: None,  # Will be added below
        OperationalError: None,
    },
)

# Trust proxy headers (e.g. X-Forwarded-Proto, X-Forwarded-For) from reverse proxies like Cloudflare
trusted_hosts_env = os.environ.get("TRUSTED_HOSTS", "127.0.0.1")
trusted_hosts = [h.strip() for h in trusted_hosts_env.split(",") if h.strip()]
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=trusted_hosts)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; connect-src 'self' https:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        return response


app.add_middleware(SecurityHeadersMiddleware)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    from uuid import uuid4

    request.state.request_id = request.headers.get("x-request-id") or str(uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.middleware("http")
async def metrics_http_middleware(request: Request, call_next):
    started = time.perf_counter()
    metrics.request_started()
    try:
        response = await call_next(request)
    except Exception:
        metrics.request_finished(
            request.method, request.url.path, 500, time.perf_counter() - started
        )
        raise
    metrics.request_finished(
        request.method,
        request.url.path,
        response.status_code,
        time.perf_counter() - started,
    )
    return response


@app.get("/metrics", include_in_schema=False)
async def metrics_endpoint() -> Response:
    body, content_type = metrics.render()
    return Response(content=body, headers={"Content-Type": content_type})


# ---------------------------------------------------------------------------
# Database Offline Handler
# ---------------------------------------------------------------------------


def _render_offline_page() -> str:
    """Read and return the offline.html template."""
    offline_path = os.path.join(BASE_DIR, "templates", "offline.html")
    if os.path.exists(offline_path):
        with open(offline_path) as f:
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
    return problem_detail(
        503, "Service unavailable", "The database is temporarily unavailable.", request
    )


@app.exception_handler(OperationalError)
async def operational_error_handler(request: Request, exc: OperationalError):
    return problem_detail(
        503, "Service unavailable", "The database is temporarily unavailable.", request
    )


app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# Mount static directories
app.mount(
    "/static/assets",
    StaticFiles(directory=os.path.join(BASE_DIR, "static/assets")),
    name="assets",
)
app.mount(
    "/static/css",
    StaticFiles(directory=os.path.join(BASE_DIR, "static/css")),
    name="css",
)
app.mount(
    "/static/js",
    StaticFiles(directory=os.path.join(BASE_DIR, "static/js")),
    name="js",
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


ensure_static_dirs()

# ---------------------------------------------------------------------------
# Register API Router
# ---------------------------------------------------------------------------


app.include_router(api_router, prefix="/api/v1")
app.include_router(health_router)

# ---------------------------------------------------------------------------
# Favicon
# ---------------------------------------------------------------------------


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(os.path.join(BASE_DIR, "static", "favicon.ico"))


# ---------------------------------------------------------------------------
# HTML Page Routes
# ---------------------------------------------------------------------------


async def get_user_for_html(request: Request):
    """Dependency for HTML routes that redirects to /login if unauthenticated."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    user_id = await validate_session(token)
    if not user_id:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    return user_id


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    from fastapi.responses import RedirectResponse

    from app.auth.session import SESSION_COOKIE_NAME, validate_session

    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        user_id = await validate_session(token)
        if user_id:
            return RedirectResponse(url="/chat", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={},
    )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, user_id: str = Depends(get_user_for_html)):
    profile = await Database.get_profile(user_id)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"profile": profile, "user_id": user_id, "current_page": "home"},
    )


@app.get("/chat", response_class=HTMLResponse)
async def chat_redirect(request: Request, user_id: str = Depends(get_user_for_html)):
    from fastapi.responses import RedirectResponse

    sessions = await Database.get_all_sessions(user_id=user_id)
    if not sessions:
        session_id = await Database.create_session("New Conversation", user_id=user_id)
    else:
        session_id = sessions[0]["id"]
    return RedirectResponse(url=f"/chat/{session_id}", status_code=302)


@app.get("/chat/{session_id}", response_class=HTMLResponse)
async def chat_page(
    session_id: str, request: Request, user_id: str = Depends(get_user_for_html)
):
    profile = await Database.get_profile(user_id)
    return templates.TemplateResponse(
        request=request,
        name="chat.html",
        context={"profile": profile, "user_id": user_id, "current_page": "chat"},
    )


@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request, user_id: str = Depends(get_user_for_html)):
    profile = await Database.get_profile(user_id)
    return templates.TemplateResponse(
        request=request,
        name="config.html",
        context={"profile": profile, "user_id": user_id, "current_page": "config"},
    )


@app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request, user_id: str = Depends(get_user_for_html)):
    profile = await Database.get_profile(user_id)
    return templates.TemplateResponse(
        request=request,
        name="about.html",
        context={"profile": profile, "user_id": user_id, "current_page": "about"},
    )


@app.get("/static/html/sidebar.html", response_class=HTMLResponse)
async def serve_sidebar():
    sidebar_path = os.path.join(BASE_DIR, "templates", "sidebar.html")
    if os.path.exists(sidebar_path):
        with open(sidebar_path) as f:
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
