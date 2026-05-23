# Backend Overhaul Roadmap: yuzu-companion

This roadmap outlines the systematic restructuring of the `yuzu-companion` backend from legacy-inflected patterns to a clean, modular FastAPI + PostgreSQL architecture.

## Phase 1: Foundation & Safe Isolation
*Establish the target structure and ensure a safe environment for destructive cleanup.*

- [x] **Infrastructure Setup**
    - [x] Create a new refactor branch: `git checkout -b refactor/backend-overhaul`.
    - [x] Initialize the new directory structure (empty `__init__.py` files):
        - [x] Create `app/api/endpoints/` and `app/api/endpoints/__init__.py`.
        - [x] Create `app/db/` and `app/db/__init__.py`.
        - [x] Create `app/services/` and `app/services/__init__.py`.
    - [x] Verify existing test suite passes: `python3 -m pytest tests/`. (Note: tests had some pre-existing failures/errors, but were verified).

- [x] **Database Layer Consolidation**
    - [x] Migration of `app/database/` content to `app/db/`.
        - [x] Move `app/database/db_queries.py` to `app/db/queries.py`.
        - [x] Move `app/database/db_pg.py` to `app/db/connection.py`.
        - [x] Move `app/database/db_pg_models.py` to `app/db/models.py`.
        - [x] Move `app/database/db_pg_models_async.py` to `app/db/models_async.py`.
        - [x] Extract `Database` class from `app/database/facade.py` into `app/db/facade.py`.
    - [x] Update all internal imports:
        - [x] `grep -r "app.database" app/` and replace with `app.db`.
        - [x] `grep -r "from app.database import" app/` and replace with `from app.db import`.
    - [x] Clean up redundant passthroughs in `app/db/facade.py`. (Simplified `_proxy` logic).

- [x] **API Registry Refactor**
    - [x] Initialize `app/api/main.py` as the new central router registry.
    - [x] Configure `APIRouter` with prefix and tags for each module.
    - [x] Move static file serving (`/static/uploads`, etc.) to a dedicated `app/api/static.py`.
        - [x] Migrate `serve_uploaded_image` from `routes.py`.
        - [x] Migrate `serve_generated_image` from `routes.py`.

## Phase 2: Provider & Config Canonization
*Unify how the system handles external AI services and configuration state.*

- [x] **One Provider Manager**
    - [x] Convert `app/providers.py` into a package `app/providers/`.
        - [x] Create `app/providers/base.py` and extract `AIProvider` and `AIProviderManager`.
        - [x] Create `app/providers/ollama.py` and extract `OllamaProvider`.
        - [x] Create `app/providers/cerebras.py` and extract `CerebrasProvider`.
        - [x] Create `app/providers/openrouter.py` and extract `OpenRouterProvider`.
        - [x] Create `app/providers/chutes.py` and extract `ChutesProvider`.
    - [x] Centralize API key lookup:
        - [x] Update `app/providers/base.py` to handle common `api_key` retrieval from DB.
        - [x] Remove manual lookup logic from `app/memory/embedder.py`.
        - [x] Remove manual lookup logic from `app/profile_analysis.py`.

- [x] **Single Config Payload (SSOT)**
    - [x] Create `app/services/config_service.py`.
    - [x] Move logic for building `ai_providers` and `vision` JSON from `api_get_config`.
    - [x] Move logic for building `profile_dict` from `api_get_profile`.
    - [x] Implement a unified `get_frontend_config()` that satisfies both web and CLI needs.
    - [x] Ensure `main.py` uses this service for its "status" display.

## Phase 3: Service Layer Extraction
*Strip business logic out of the API routes and orchestrator.*

- [x] **Session Lifecycle Service**
    - [x] Create `app/services/session_service.py`.
    - [x] Migrate `start_session`, `end_session_cleanup`, and `auto_name_session_if_needed`.
    - [x] Consolidate `_web_session_tracker` into a service-level state if still needed, or replace with DB session status.
    - [x] Standardize `connection_msg` and `disconnect_msg` generation.

- [x] **Chat & Messaging Service**
    - [x] Create `app/services/chat_service.py`.
    - [x] Extract `api_send_message` logic.
    - [x] Extract `api_send_message_stream` initiation logic.
    - [x] Move `image_markdowns` construction from the API layer to this service.
    - [x] Delete `api_send_message_with_images` (DEPRECATED).

- [x] **Memory Pipeline Isolation**
    - [x] Move `detect_important_content`, `summarize_memory`, etc., from `app/profile_analysis.py` to `app/memory/`.
    - [x] Move `run_memory_pipeline` trigger logic to `app/services/memory_service.py`.
    - [x] Clean up `app/memory/__init__.py` to export the public API.

## Phase 4: API Route Decomposition
*Break down the monolithic routes.py into focused, maintainable modules.*

- [x] **Module Split**
    - [x] Implement `app/api/endpoints/chat.py` (message sending, streaming).
    - [x] Implement `app/api/endpoints/sessions.py` (CRUD, switching, renaming).
    - [x] Implement `app/api/endpoints/profile.py` (config, settings, keys).
    - [x] Implement `app/api/endpoints/memory.py` (stats, rebuild, decay).

- [x] **Cleanup & Deletion**
    - [x] Delete `app/api/routes.py` after full migration.
    - [x] Remove `app/api/routes/` empty directory.
    - [x] Consolidate `api_update_location` and `api_update_weather_location`.
    - [x] Ensure all routes use Pydantic models for validation (remove `request.json()` usage).

## Phase 5: Final Cleanup & Shim Removal
*Final technical debt clearance and architecture finalization.*

- [x] **Shim Elimination**
    - [x] Update `main.py`: Replace `from app.app import ...` with specific imports.
    - [x] Update `web.py`: Replace `from app.app import ...` with specific imports.
    - [x] Update `scripts/yuzu_cli.py`: Verified no `app.app` imports needed.
    - [x] Delete `app/app.py`.

- [x] **Flask-era Baggage Hunt**
    - [x] Replace `print()` with `log.info()`, `log.error()`, etc.
    - [x] Standardize error responses: Use `HTTPException` with clear, non-leaking detail strings.
    - [x] Clean up manual path manipulations: Replace `os.path.join` with `/` operator from `pathlib.Path`.
    - [x] Remove unused `_NoopContext` in `app/session_lifecycle.py` (file deleted).

- [x] **Final Verification**
    - [x] Run `py_compile` across the whole project to ensure import integrity.
    - [x] Verify roadmap completion.

## Phase 6: Verification & Documentation
*Ensure the new architecture is solid and well-explained.*

- [x] **Validation Pass**
    - [x] Run tests: 136 passed (5 pre-existing shell_exec env failures).
    - [x] Verify CLI: `main.py` starts, connects to DB, initializes properly.
    - [x] Memory pipeline: No core logic changes, throttling unchanged.

- [x] **Documentation Update**
    - [x] Update `README.md` and `AGENTS.md` to reflect the new module structure.
    - [x] Create `docs/BACKEND.md` with Request → Router → Service → DB flow.
    - [x] Document removal of `app.py` shim and `routes.py` monolith.
