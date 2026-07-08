# Configuration Architecture Refactor

## 1. Executive Summary
This document outlines the architecture and execution plan for the configuration of Yuzu Companion. The goal is to establish a strict separation of concerns across 4 domains: Application Configuration, User Preferences, User Credentials, and Runtime Context. The refactoring is executed across 5 Phases, with Phases 1-3 focused on the backend and Phases 4-5 focusing on the frontend and prompt modularization.

## 2. Core Architecture & Domain Boundaries
We strictly adhere to these 4 distinct configuration domains:

### 2.1 Application Configuration
* **Ownership:** Server
* **Storage:** `.env` file only.
* **Examples:** `DATABASE_URL`, `SESSION_SECRET`, `OAUTH`, `APP_URL`, `REDIS_URL`, `LOG_LEVEL`, `ENABLE_SIGNUP`.
* **Constraint:** These must NEVER be exposed to the user UI.

### 2.2 User Preferences
* **Ownership:** User
* **Storage:** Database (`profiles` table, e.g., `preferences` or `providers_config`).
* **Examples:** `assistant_name`, `user_name`, `persona`, `provider_order`, `selected_model`, `temperature`, `top_p`, `history_instruction`, `vision_preference`.
* **Constraint:** Safe to persist in the database as these are non-secret configurations.

### 2.3 User Credentials (Strict Security Implementation)
* **Ownership:** User (Client-side)
* **Target Flow:** Browser Keyring -> Request Header (`X-Provider-Key`) -> Backend Context (`RequestKeyring`) -> Provider.
* **Anti-Pattern (ELIMINATED):** Browser -> Database -> `decrypt()` -> Provider, OR Browser -> `.env` -> Provider.
* **Constraint:** The server must NOT act as a password manager. Credentials only live in memory during the request lifecycle.

### 2.4 Runtime Context (`LLMContext`)
* **Ownership:** Backend Application State
* **Target Flow:** Request -> Resolve Context -> Provider -> LLM.
* **Data Structure:** `LLMContext` contains `provider`, `model`, `vision`, `api_key`, `base_url`, `parameters`.
* **Constraint:** `LLMContext` must be the Single Source of Truth (SSOT). The entire backend only accepts `LLMContext`. Scattered resolutions deep in provider logic are eliminated.

---

## 3. Execution Plan Status

### Phase 1: Audit and Analysis (COMPLETED)
- Mapped all environment variables, UI fields, and database columns.
- Identified legacy credentials stored in `api_keys` and anti-patterns.
- Defined the target 4-domain architecture.

### Phase 2: Runtime Context (`LLMContext`) SSOT Refactor (COMPLETED)
- Created `app/core/llm_context.py` with an `LLMContext` dataclass.
- Implemented `LLMContext.from_profile()` to merge DB preferences with `RequestKeyring` headers.
- Refactored all providers (`openrouter`, `chutes`, `ollama`, `cerebras`) to consume `LLMContext` directly.
- Removed scattered `resolve_api_key`, `resolve_base_url`, and `resolve_model` functions.
- Updated services (`session_service`, `config_service`) and tools to pass `LLMContext`.

### Phase 3: Cleanup (COMPLETED)
- **Destructive Action:** Completely deleted the `api_keys` table creation DDL from `app/db/queries.py`.
- Removed all DB credential persistence logic and CRUD helpers (`add_api_key_async`, etc.) from `app/db/models_async.py` and `app/db/facade.py`.
- Updated encryption status tracking to ignore the now-deleted API keys table.
- Verified system integrity with 100% test pass rate.

### Phase 4: Configuration UI v2 (Frontend Redesign) (IN PROGRESS)
Implement a modular configuration interface with the following structure:
* **Identity:** `Assistant Name`, `User Name`, `Persona` (Dropdown/Radio: Warm, Professional, Smug, Pirate, Neko, Custom), `Persona Prompt` (textarea).
* **Providers (Card-based layout):**
    * *OpenRouter / OpenAI / Anthropic:* `API Key` input, `Model` dropdown, `Refresh Models` button.
    * *Custom OpenAI / Custom Anthropic:* `Base URL`, `API Key`, `Fetch Models` button, `Model` dropdown, `Vision` toggle.
* **Constraint:** Fetch models via `GET /v1/models` from the provider (proxied through backend if necessary due to CORS), but ensure the API key is only used for the request and NEVER persisted.

### Phase 5: Advanced Settings & Persona Modularization (PENDING)
* **Advanced Config UI:** Implement sections for `Generation` (Temperature, Top P, Max Tokens, Reasoning, Vision, History Limit), `Prompt` (Persona, Post History Instructions, Developer Prompt), and `Debug`.
* **System Prompt Modularization:** Refactor the monolithic system prompt into a modular template.
    * *Base Template:* `You are {{assistant_name}}, a helpful AI companion. Your personality is defined by: {{persona}}. You are speaking with {{user_name}}.`
    * *Logic:* Inject the `{{persona}}` from a preset (e.g., Warm, Professional, Smug, etc.) or a Custom input.
    * *Goal:* Keep the core prompt short and stable, treating personality as a swappable component injected into the system instruction, similar to modern character card architectures.
