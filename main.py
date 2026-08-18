from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
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


def _cors_config() -> dict[str, object]:
    """
    Build the CORS configuration from the configured allowed origins.

    Returns:
        dict[str, object]: CORS settings derived from `CORS_ORIGINS`, or default cross-origin
                origins including chat.yuzuki.space when no origins are configured.
    """
    origins_env = os.environ.get("CORS_ORIGINS", "")
    origins = [o.strip() for o in origins_env.split(",") if o.strip()]
    default_origins = [
        "https://chat.yuzuki.space",
        "https://yuzuki.space",
        "https://api.yuzuki.space",
        "http://localhost:5000",
        "http://127.0.0.1:5000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    allow_origins = origins if origins else default_origins

    return {
        "allow_origins": allow_origins,
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }


# Trust proxy headers (e.g. X-Forwarded-Proto, X-Forwarded-For) from reverse proxies like Cloudflare
trusted_hosts_env = os.environ.get("TRUSTED_HOSTS", "*")
trusted_hosts = [h.strip() for h in trusted_hosts_env.split(",") if h.strip()]
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=trusted_hosts)


CORS_CONFIG = _cors_config()
app.add_middleware(CORSMiddleware, **CORS_CONFIG)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add standard security headers to every response when not already set.

    preview-shell.html is the one exception: the frontend embeds it in a
    sandboxed same-origin iframe (HTML-preview fences), so it must stay
    frameable by the app itself while everything else stays clickjacking-
    hardened. A meta-tag CSP cannot express frame-ancestors, so the backend
    enforces it via header on top of the pages' meta CSP (the two intersect).
    """

    _FRAMEABLE_PATH = "/preview-shell.html"

    async def dispatch(self, request: Request, call_next):
        """
        Add standard security headers to the response when they are not already set.

        Returns:
            Response: The response with security headers applied.
        """
        if request.method == "OPTIONS":
            return await call_next(request)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        if request.url.path == self._FRAMEABLE_PATH:
            response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
            response.headers.setdefault(
                "Content-Security-Policy", "frame-ancestors 'self'"
            )
        else:
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault(
                "Content-Security-Policy", "frame-ancestors 'none'"
            )
        return response


app.add_middleware(SecurityHeadersMiddleware)


def _env_flag(name: str, default: bool) -> bool:
    """ฅ^•ﻌ•^ฅ"""
    return os.environ.get(name, "true" if default else "false").lower() == "true"


SERVE_WEB_UI = _env_flag("SERVE_WEB_UI", True)

# Local single-origin SPA mode: when SERVE_WEB_UI is true and SERVE_SPA is set,
# the page routes serve the built SPA from web/dist instead of the Jinja
# templates. Default keeps the current Jinja UI; SERVE_SPA has no effect in
# API-only mode (SERVE_WEB_UI=false).
SERVE_SPA = _env_flag("SERVE_SPA", False)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    from uuid import uuid4

    request.state.request_id = request.headers.get("x-request-id") or str(uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.middleware("http")
async def metrics_http_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
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
    if not metrics.enabled:
        raise HTTPException(status_code=404, detail="Not found")
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
    """
    Create a service-unavailable response for a database operational error.

    Returns:
        Response: A 503 problem-detail response indicating that the database is temporarily unavailable.
    """
    return problem_detail(
        503, "Service unavailable", "The database is temporarily unavailable.", request
    )


@app.exception_handler(StarletteHTTPException)
async def custom_starlette_http_exception_handler(request: Request, exc: Exception):
    """
    Handle HTTP exceptions and apply CORS headers for allowed request origins.

    Parameters:
        request (Request): The incoming HTTP request.
        exc (Exception): The exception being handled. Non-Starlette exceptions are
            represented as internal server errors.

    Returns:
        Response: An HTTP error response with CORS headers when the request origin
        is allowed.
    """
    starlette_exc = (
        exc
        if isinstance(exc, StarletteHTTPException)
        else StarletteHTTPException(status_code=500, detail=str(exc))
    )
    response = await http_exception_handler(request, starlette_exc)
    origin = request.headers.get("origin")
    allowed_origins = CORS_CONFIG.get("allow_origins")
    if (
        isinstance(allowed_origins, list)
        and origin
        and (origin in allowed_origins or "*" in allowed_origins)
    ):
        response.headers["Access-Control-Allow-Origin"] = origin
        if CORS_CONFIG.get("allow_credentials"):
            response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(
    StarletteHTTPException, custom_starlette_http_exception_handler
)
app.add_exception_handler(Exception, unhandled_exception_handler)


class PublicStaticFiles(StaticFiles):
    """Serve public assets without exposing private image directories."""

    _PRIVATE_DIRECTORIES = {"uploads", "generated_images", "image_cache"}

    async def get_response(self, path, scope):
        if path.split("/", 1)[0] in self._PRIVATE_DIRECTORIES:
            raise StarletteHTTPException(status_code=404)
        return await super().get_response(path, scope)


if SERVE_WEB_UI and not SERVE_SPA:
    # Keep one canonical public mount: templates use url_for("static", path=...).
    app.mount(
        "/static",
        PublicStaticFiles(directory=os.path.join(BASE_DIR, "static")),
        name="static",
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


app.include_router(api_router, prefix="/v1")
app.include_router(api_router, prefix="/api/v1", include_in_schema=False)
app.include_router(health_router)

# ---------------------------------------------------------------------------
# Favicon
# ---------------------------------------------------------------------------


if SERVE_WEB_UI and not SERVE_SPA:

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return FileResponse(os.path.join(BASE_DIR, "static", "favicon.ico"))


# ---------------------------------------------------------------------------
# HTML Page Routes
# Jinja mode (SERVE_WEB_UI=true, SERVE_SPA=false) is the default and serves the
# server-rendered pages; SPA mode (SERVE_SPA=true) serves the built web/
# frontend instead. API-only mode (SERVE_WEB_UI=false) omits both.
# ---------------------------------------------------------------------------


if SERVE_WEB_UI and not SERVE_SPA:

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
    async def chat_redirect(
        request: Request, user_id: str = Depends(get_user_for_html)
    ):
        from fastapi.responses import RedirectResponse

        sessions = await Database.get_all_sessions(user_id=user_id)
        if not sessions:
            session_id = await Database.create_session(
                "New Conversation", user_id=user_id
            )
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
# SPA Page Routes (SERVE_WEB_UI=true + SERVE_SPA=true)
# ---------------------------------------------------------------------------


if SERVE_WEB_UI and SERVE_SPA:
    SPA_DIST_DIR = os.environ.get("SPA_DIST_DIR", os.path.join(BASE_DIR, "web", "dist"))
    if not os.path.isdir(os.path.join(SPA_DIST_DIR, "assets")):
        raise RuntimeError(
            "SERVE_SPA=true requires a built SPA: run `npm --prefix web run build` "
            "so web/dist exists before starting the server (or set SPA_DIST_DIR)."
        )

    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(SPA_DIST_DIR, "assets")),
        name="spa-assets",
    )

    def _spa_entry(html_name: str) -> FileResponse:
        """ฅ^•ﻌ•^ฅ"""
        return FileResponse(os.path.join(SPA_DIST_DIR, html_name))

    @app.get("/favicon.ico", include_in_schema=False)
    async def spa_favicon():
        return FileResponse(os.path.join(SPA_DIST_DIR, "favicon.ico"))

    @app.get("/", response_class=HTMLResponse)
    async def spa_home():
        return _spa_entry("index.html")

    @app.get("/login", response_class=HTMLResponse)
    async def spa_login():
        return _spa_entry("login.html")

    @app.get("/chat", response_class=HTMLResponse)
    async def spa_chat():
        return _spa_entry("chat.html")

    @app.get("/chat/{session_id}", response_class=HTMLResponse)
    async def spa_chat_session(session_id: str):
        return _spa_entry("chat.html")

    @app.get("/config", response_class=HTMLResponse)
    async def spa_config():
        return _spa_entry("config.html")

    @app.get("/about", response_class=HTMLResponse)
    async def spa_about():
        return _spa_entry("about.html")

    @app.get("/preview-shell.html", response_class=HTMLResponse)
    async def spa_preview_shell():
        # Frameable by the app itself (see SecurityHeadersMiddleware); the
        # frontend loads this in a sandboxed iframe for HTML-preview fences.
        return _spa_entry("preview-shell.html")


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5000, log_level="info")
