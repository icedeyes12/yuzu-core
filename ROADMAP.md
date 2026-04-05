# YUZU-COMPANION — REFACTORING ROADMAP
> Status: DRAFT — April 2026
> Prioritas: Pecah monolith -> Polish infrastructure -> Testing -> Dokumentasi

---

## PREREQUISITE CHECKLIST

Jalankan ini dulu sebelum mulai refactor APAPUN:

bash
cd /home/workspace/yuzu-companion

# 1. Verify imports still work
python3 -c "from app.app import handle_user_message; print('OK')"
python3 -c "from web import app; print('OK')"

# 2. Backup point
git rev-parse HEAD

> Kalau ada import error, SELESAIKAN DULU sebelum lanjut.

---

## ADVISED BRANCHING STRATEGY

bash
# 1 branch per phase
git checkout -b phase0-cleanup-sprint
git checkout -b phase1-split-app-monolith
git checkout -b phase2-split-providers
git checkout -b phase3-infra-layer
git checkout -b phase4-memory-polish
git checkout -b phase5-testing-infra
git checkout -b phase6-docs

Rules:
- Setiap branch: refactor -> verify -> commit -> push -> merge
- Jangan pernah merge kode yang belum verified bisa jalan

## PROJECT STATUS

| Metric | Value |
|--------|-------|
| app/app.py | 2761 lines -- GOD MODULE |
| app/providers.py | 1072 lines -- provider + manager 1 file |
| app/database.py | 347 lines -- proxy ke db_pg_models |
| app/a.py, app/b.py | MIGRATION SCRIPTS -- to archive |
| Test suite | TIDAK ADA |
| src/ directory | TIDAK ADA |
| PostgreSQL migration | DONE |
| pgvector memory | DONE |

---

## PHASE 0 -- CLEANUP SPRINT
Estimated: 2-3 hours | Priority: HIGH

### TASK 0.1 -- Archive Migration Scripts

NOTE: app/yuzu_core.db already backed up in main environment -- SKIP deletion.

MICRO TASKS:
  - Buat archive/migrations/ directory
  - mv app/a.py archive/migrations/
  - mv app/b.py archive/migrations/
  - mv rebuild_semantic_facts.py archive/migrations/
  - mv reembed_semantic_facts.py archive/migrations/
  - mv app/memory/migrate_history.py archive/migrations/
  - Verifikasi: python3 -c "import app.a; import app.b" harus error
  - Commit: git co-author "chore: archive obsolete migration scripts"

### TASK 0.2 -- Cek & Resolve Circular Imports

MICRO TASKS:
  - Buat verify_imports.py yang import semua module berurutan
  - Test: python3 verify_imports.py
  - Kalau ada circular import:
    - Identifikasi siapa import siapa
    - Pindahkan import ke dalam function (lazy import)
    - Atau buat app/__init__.py sebagai facade
  - Commit per fix

### TASK 0.3 -- Uniformkan Error Handling Pattern

MICRO TASKS:
  - Cek semua file di app/ -- catch exception pattern sama?
  - Standard: module-level import errors -> print + raise
  - Commit: chore: uniform error handling pattern

---

## PHASE 1 -- BREAK THE MONOLITH (app/app.py 2761 lines)
Estimated: 6-8 hours | Priority: HIGH

### TASK 1.1 -- Identifikasi Concern Boundaries

MICRO TASKS:
  Baca app.py dari awal, catat setiap grup fungsi:

  CONCERN A: Visual Context Buffer (_visual_context_*)
    -> extract ke: app/context/visual_buffer.py

  CONCERN B: Command Detection (_detect_command, _is_tool_markdown, dll)
    -> extract ke: app/context/command_detector.py

  CONCERN C: Image Cache (_cache_images_from_message, dll)
    -> extract ke: app/context/image_cache.py

  CONCERN D: UserContext class
    -> extract ke: app/context/user_context.py

  CONCERN E: Session Lifecycle (start_session, end_session_cleanup, rename)
    -> extract ke: app/session/lifecycle.py

  CONCERN F: Memory Pipeline (FSRS, segmentation, extraction triggers)
    -> extract ke: app/memory/pipeline.py

  CONCERN G: Summarization (summarize_memory, session_context_analysis)
    -> extract ke: app/memory/summarizer.py

  CONCERN H: Core Orchestration (handle_user_message, streaming)
    -> stay di: app/app.py (tapi lebih kecil)

  Buat app/context/__init__.py
  Buat app/session/__init__.py

### TASK 1.2 -- Extract Session Lifecycle

MICRO TASKS:
  - Buat app/session/ directory
  - Buat app/session/lifecycle.py -- copy:
      start_session()
      end_session_cleanup()
      generate_session_name_ai()
  - Buat app/session/__init__.py
  - DI app/app.py -- REPLACE dengan import dari session.lifecycle
  - Hapus fungsi dari app/app.py
  - Verifikasi: python3 -c "from app.app import handle_user_message; print('OK')"
  - Commit: refactor: extract session lifecycle to app/session/

### TASK 1.3 -- Extract Visual Context Buffer

MICRO TASKS:
  - Buat app/context/visual_buffer.py
  - Copy: _visual_context_buffer, _visual_context_lock, _VISUAL_CONTEXT_TURNS,
          _store_visual_context(), _consume_visual_context()
  - Buat app/context/__init__.py
  - DI app/app.py -- import dari visual_buffer
  - Hapus dari app/app.py
  - Verify: python3 -c "from app.app import handle_user_message; print('OK')"
  - Commit

### TASK 1.4 -- Extract Command Detection

MICRO TASKS:
  - Buat app/context/command_detector.py
  - Copy: _VISUAL_REF_PATTERNS, _has_visual_reference(),
          _generate_tool_call_id(), _is_image_generation_tool(),
          _parse_image_result_from_formatted(), _detect_command(),
          _is_tool_markdown(), _is_model_using_markdown_image_shortcut(),
          _extract_prompt_from_markdown_image(), _extract_tool_role(),
          _extract_command_from_markdown(), _execute_command_tool()
  - _execute_command_tool perlu Database + registry -- lazy import di function
  - DI app/app.py -- GANTI _execute_command_tool dengan import
  - Hapus semua fungsi dari app/app.py
  - Verify
  - Commit

### TASK 1.5 -- Extract Image Cache & Generation Helpers

MICRO TASKS:
  - Buat app/context/image_cache.py
  - Copy: _cache_images_from_message(), _load_generated_image_base64(),
          _load_and_attach_generated_image()
  - DI app/app.py -- from app.context.image_cache import ...
  - Hapus dari app/app.py
  - Verify + Commit

### TASK 1.6 -- Extract Memory Pipeline

MICRO TASKS:
  - Buat app/memory/pipeline.py
  - Copy: detect_important_content(), should_summarize_memory()
  - _init_memory_system() -- extract dari start_session()
  - Buat app/memory/__init__.py
  - DI app/app.py -- from app.memory.pipeline import ...
  - Hapus dari app/app.py
  - COMMIT SETIAP EXTRACT -- jangan nunggu selesai semua

### TASK 1.7 -- Extract Summarizer

MICRO TASKS:
  - Buat app/memory/summarizer.py
  - Copy: summarize_memory(), session_context_analysis()
  - DI app/app.py -- from app.memory.summarizer import summarize_memory
  - Hapus dari app/app.py
  - Commit

### TASK 1.8 -- Flush & Verify app/app.py

MICRO TASKS:
  - Hitung ulang line count app/app.py -- harus < 500 lines
  - Kalau masih > 500, check apa yang belum di-extract
  - Pastikan tidak ada import yang dangling
  - python3 -m py_compile app/app.py
  - python3 -c "from app.app import handle_user_message, handle_user_message_streaming, start_session; print('ALL OK')"
  - Commit final phase 1

---

## PHASE 2 -- SPLIT PROVIDERS MODULE (app/providers.py 1072 lines)
Estimated: 4-5 hours | Priority: HIGH

### TASK 2.1 -- Identifikasi Concern Boundaries

MICRO TASKS:
  - AIProvider (base class) -> app/providers/base.py
  - OllamaProvider -> app/providers/ollama.py
  - CerebrasProvider -> app/providers/cerebras.py
  - OpenRouterProvider -> app/providers/openrouter.py
  - ChutesProvider -> app/providers/chutes.py
  - AIProviderManager -> app/providers/manager.py
  - Buat app/providers/__init__.py

### TASK 2.2 -- Extract Base Class

MICRO TASKS:
  - Buat app/providers/base.py -- copy AIProvider class
  - Buat app/providers/__init__.py
  - DI app/providers.py -- REPLACE dengan from app.providers.base import AIProvider
  - Verify: python3 -c "from app.providers import AIProvider; print('OK')"
  - Commit

### TASK 2.3 -- Extract OllamaProvider

MICRO TASKS:
  - Buat app/providers/ollama.py
  - Copy OllamaProvider class
  - DI app/providers.py -- HAPUS class, ganti import
  - Verify + Commit

### TASK 2.4 -- Extract Cerebras, OpenRouter, Chutes

MICRO TASKS:
  - Extract CerebrasProvider -> app/providers/cerebras.py
  - Extract OpenRouterProvider -> app/providers/openrouter.py
  - Extract ChutesProvider -> app/providers/chutes.py
  - COMMIT SETIAP SATU

### TASK 2.5 -- Extract AIProviderManager

MICRO TASKS:
  - Buat app/providers/manager.py
  - Copy AIProviderManager + _ai_manager_instance singleton
  - Copy get_ai_manager() + reload_ai_manager()
  - DI app/providers/__init__.py -- expose manager functions
  - Hapus dari app/providers.py
  - Verify + Commit

### TASK 2.6 -- Flush & Verify providers.py

MICRO TASKS:
  - app/providers.py harus < 100 lines (hanya import + __init__ + aliases)
  - python3 -m py_compile app/providers.py
  - Verify all providers still load
  - Commit final phase 2

---

## PHASE 3 -- INFRASTRUCTURE LAYER
Estimated: 3-4 hours | Priority: MEDIUM

### TASK 3.1 -- Buat app/config/ untuk env/configuration

MICRO TASKS:
  - Buat app/config/__init__.py
  - Buat app/config/settings.py -- centralized env defaults dari:
      app/db_pg.py (_PG_HOST, _PG_PORT, etc)
      app/providers.py (model lists, base URLs)
      app/encryption.py (key path)
  - app/db_pg.py -- from app.config.settings import PG_HOST, PG_PORT, etc
  - Commit

### TASK 3.2 -- Buat app/constants.py

MICRO TASKS:
  - Buat app/constants.py
  - Tarik: _VISUAL_CONTEXT_TURNS, _VISUAL_REF_PATTERNS (raw string)
  - Commit

### TASK 3.3 -- Buat app/exceptions.py

MICRO TASKS:
  - Buat app/exceptions.py:
      class YuzuError(Exception): pass
      class MemoryError(YuzuError): pass
      class ProviderError(YuzuError): pass
      class SessionError(YuzuError): pass
  - Replace print-based error handling dengan raise
  - Commit

### TASK 3.4 -- app/__init__.py sebagai Facade

MICRO TASKS:
  - Buat app/__init__.py yang expose public API:
      from app.app import handle_user_message, handle_user_message_streaming
      from app.providers import get_ai_manager, reload_ai_manager
      from app.database import Database
      from app.session.lifecycle import start_session, end_session_cleanup
  - Verify: python3 -c "import app; print(dir(app))"
  - Commit

---

## PHASE 4 -- MEMORY LAYER POLISH
Estimated: 2-3 hours | Priority: MEDIUM

### TASK 4.1 -- Fix search_similar Vector Construction

MICRO TASKS:
  - Buka app/memory/db_memory.py -- search_similar()
  - vec_str, vec_str2, vec_str3 identical -- use single vec_str
  - Commit: fix: dedupe vector string construction in search_similar

### TASK 4.2 -- Consolidate embedder imports

MICRO TASKS:
  - Cek app/memory/extractor.py -- import embed_text dari embedder.py?
  - Pastikan tidak ada duplicate embedding logic
  - Commit

### TASK 4.3 -- Verify retrieval.py retry logic

MICRO TASKS:
  - Buka app/memory/retrieval.py
  - Pastikan search_similar crash -> fallback graceful
  - Pastikan _trigger_memory_pipeline tidak block main flow
  - Commit per fix

---

## PHASE 5 -- TESTING INFRASTRUCTURE
Estimated: 4-6 hours | Priority: MEDIUM

### TASK 5.1 -- Setup pytest

MICRO TASKS:
  - pip install pytest pytest-asyncio
  - Buat tests/ directory + tests/__init__.py
  - Buat tests/conftest.py -- fixture untuk Database, AIProviderManager
  - Buat .gitignore: tests/__pycache__/, .pytest_cache/
  - Commit

### TASK 5.2 -- Write Import/Load Tests

MICRO TASKS:
  - Buat tests/test_imports.py
    - Test: semua module bisa di-import tanpa error
    - Test: app/app.py exports yang diharapkan
    - Test: web.py bisa di-import
  - Commit

### TASK 5.3 -- Write Unit Tests untuk Key Modules

MICRO TASKS:
  - tests/test_encryption.py -- encrypt/decrypt roundtrip
  - tests/test_visual_buffer.py -- store/consume logic
  - tests/test_command_detector.py -- detection logic
  - tests/test_schemas.py -- tool definition + contract building
  - Commit per file

### TASK 5.4 -- Write Integration Smoke Tests

MICRO TASKS:
  - tests/test_memory_pipeline.py -- process_messages_for_memory idempotent
  - tests/test_session_lifecycle.py -- start/end session
  - tests/test_tool_dispatch.py -- execute_tool roundtrip
  - Commit

---

## PHASE 6 -- DOCUMENTATION
Estimated: 2-3 hours | Priority: LOW

### TASK 6.1 -- Update README.md

MICRO TASKS:
  - Baca README.md -- apa still accurate?
  - Update installation instructions kalau perlu
  - Update feature list
  - Commit

### TASK 6.2 -- Buat docs/ARCHITECTURE.md

MICRO TASKS:
  - Buat docs/ARCHITECTURE.md
  - Document:
      - Folder structure (post-refactor)
      - Data flow (user message -> AI response)
      - Memory pipeline
      - Tool dispatch mechanism
      - Provider selection
  - Commit

### TASK 6.3 -- Buat CONTRIBUTING.md yang proper

MICRO TASKS:
  - Buat CONTRIBUTING.md dengan:
      - How to run tests
      - Branch naming convention
      - Commit message format
      - How to add a new tool
      - How to add a new provider
  - Commit

---

## PRIORITY SUMMARY

| Phase | Priority | Estimated | Key Deliverable |
|-------|----------|-----------|----------------|
| Phase 0 | HIGH | 2-3h | Clean slate, no junk |
| Phase 1 | HIGH | 6-8h | app/app.py < 500 lines |
| Phase 2 | HIGH | 4-5h | app/providers.py < 100 lines |
| Phase 3 | MEDIUM | 3-4h | Centralized config + exceptions |
| Phase 4 | MEDIUM | 2-3h | Memory layer robust |
| Phase 5 | MEDIUM | 4-6h | Test suite exists |
| Phase 6 | LOW | 2-3h | docs/ARCHITECTURE.md + updated README |

Total estimated: 23-32 hours

---

## KNOWN RISKS & MITIGATIONS

| Risk | Mitigation |
|------|------------|
| Circular imports muncul pas split | Test import setiap extract, lazy import di dalam function |
| Regression di tool dispatch | Buat smoke test sebelum split, verify dopo cada extract |
| app.py references private functions yang dipindah | python3 -m py_compile dopo cada extract |
| Session state bocor across modules | Verify session lifecycle test pass |

---

## DONT DO

- Jangan refactor dan add feature bareng -- pisah
- Jangan skip phase 0 -- migration scripts di a.py/b.py bisa confuse future refactoring
- Jangan ubah public API (handle_user_message signature) tanpa alasan
- Jangan merge phase kalau verification gagal
