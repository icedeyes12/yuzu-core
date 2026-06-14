# Yuzu Companion — Refactor Plan (Phase 1 Audit Report)

**Tanggal Audit:** 2026-06-14  
**Versi Codebase:** ~v3.2.0 (post-backend-overhaul)  
**Fokus:** Tech debt cleanup, duplicate sync functions, dead code, scattered logic

---

## Executive Summary

Audit ini mengidentifikasi **5 kategori utama tech debt** di codebase `app/`:

1. **Duplicate Sync Functions** — 75+ pasangan sync/async di `app/db/` dan `app/memory/` yang sudah diorkestrasi via facade/boundary layer
2. **Dead Code** — Stub endpoint, deprecated functions, unused imports
3. **Scattered Business Logic** — Inline logic di API endpoints yang seharusnya di service layer
4. **Circular Import Risk** — Lazy `from app.providers import get_ai_manager` pattern di 10+ file
5. **Structural Debt** — Redundant helper functions, duplicate patterns

---

## 🔴 CRITICAL: Business Logic di API Endpoints

### `app/api/endpoints/memory.py` (Lines 84-124)

**Masalah:** Endpoint `/rebuild_structured_memory` berisi inline logic untuk memory pipeline trigger.

```python
# Lines 84-124: Memory pipeline trigger logic
from app.memory.memory import run_memory_pipeline_async
from app.memory.db_memory import count_facts, FACT_TYPE_STATIC, FACT_TYPE_DYNAMIC

# INLINED BUSINESS LOGIC:
count = await Database.get_session_messages_count_async(session_id)
result = await run_memory_pipeline_async(session_id, count)
semantic_count = count_facts(fact_type=FACT_TYPE_STATIC, session_id=session_id)
episodic_count = count_facts(fact_type=FACT_TYPE_DYNAMIC, session_id=session_id)
```

**Aksi:** Pindahkan ke `MemoryService.rebuild_structured_memory_async()`

---

## 🟠 HIGH: Dead Code & Stub Endpoints

### 1. Stub Endpoints di `app/api/endpoints/memory.py`

```python
# Lines 140-143: DEAD ENDPOINT
@router.post("/memory/store")
async def api_store_memory(request: Request, session_id: int | None = None):
    pass  # ← No implementation


# Lines 146-149: DEAD ENDPOINT
@router.get("/memory/retrieve")
async def api_retrieve_memory(request: Request, session_id: int | None = None):
    pass  # ← No implementation
```

**Aksi:** Hapus atau implementasikan dengan proper service layer call.

---

## 🟡 MEDIUM: Sync/Async Function Duplication

### 1. Database Layer (`app/db/models.py` + `models_async.py`)

**Statistik:**
- `models.py`: 41 sync functions
- `models_async.py`: 43 async functions
- **Fungsi duplikat hampir 1:1**

**Contoh duplikasi:**

| Sync Function | Async Function | Status |
|---------------|----------------|--------|
| `get_profile()` | `get_profile_async()` | 🟢 Facade wraps both |
| `add_message()` | `add_message_async()` | 🟢 Facade wraps both |
| `update_message()` | `update_message_async()` | 🟢 Facade wraps both |
| `get_chat_history()` | `get_chat_history_async()` | 🟢 Facade wraps both |

**Analisis:** Facade pattern sudah correct. Sync versions masih diperlukan untuk:
- CLI runner (`app/cli.py`)
- Background thread workers yang tidak async
- Legacy script imports

**Aksi:** 
- ✅ KEEP: Sync functions sudah properly wrapped by `Database` facade
- ⚠️ AUDIT: Pastikan tidak ada direct import `from app.db.models import X` yang bypass facade

---

### 2. Memory Layer (`app/memory/db_memory.py`)

**Statistik:**
- Sync functions: 13
- Async functions: 9

**Duplikasi signifikan:**

| Sync Function | Async Function | Status |
|---------------|----------------|--------|
| `save_fact()` | `save_fact_async()` | ⚠️ Both active |
| `search_similar()` | `search_similar_async()` | ⚠️ Both active |
| `search_trgm()` | `search_trgm_async()` | ⚠️ Both active |
| `search_tsv()` | `search_tsv_async()` | ⚠️ Both active |
| `get_facts_by_session()` | `get_facts_by_session_async()` | ⚠️ Both active |
| `update_last_accessed()` | `update_last_accessed_async()` | ⚠️ Both active |
| `invalidate_fact()` | `invalidate_fact_async()` | ⚠️ Both active |
| `decay_facts()` | ❌ No async | 🔴 Needs async |
| `increment_importance()` | ❌ No async | 🔴 Needs async |

**Analisis:** Memory layer TIDAK memiliki facade. Callers harus memilih manual sync vs async.

**Aksi:**
- 🔨 CREATE: `app.memory.db_memory_facade` dengan class wrapper
- 📋 PATTERN: Mirror `app.db.facade.Database` pattern
- ⚠️ MIGRATE: Move sync callers in production routes to async

---

### 3. Retrieval Layer (`app/memory/retrieval.py`)

**Statistik:**
- Sync functions: 22
- Async functions: 7

**Duplikasi signifikan:**

| Sync Function | Async Function | Status |
|---------------|----------------|--------|
| `retrieve_static_memories()` | `retrieve_static_memories_async()` | ⚠️ Both active |
| `retrieve_dynamic_memories()` | `retrieve_dynamic_memories_async()` | ⚠️ Both active |
| `retrieve_memories_combined()` | `retrieve_memories_combined_async()` | ⚠️ Uses asyncio.to_thread |
| `retrieve_memory()` | `retrieve_memory_async()` | ⚠️ Both active |
| `retrieve_for_context()` | `retrieve_for_context_async()` | ⚠️ Both active |
| `_get_cached_embedding()` | `_get_cached_embedding_async()` | 🔴 Thread-local cache issue |
| `_embed_query()` | `_embed_query_async()` | ⚠️ Both active |

**Catatan khusus:**
- `retrieve_memories_combined_async()` uses `asyncio.to_thread()` untuk sync wrapper — potential blocking
- `_get_cached_embedding()` uses `threading.local()` — bisa problematic di async context

**Aksi:**
- 📋 AUDIT: Verify threading.local() cache safety in async context
- 🔨 CONSIDER: Context-aware cache using `contextvars`
- 📋 VERIFY: All callers of sync versions are legitimate non-async contexts

---

## 🟡 MEDIUM: Deprecated Functions

### 1. `add_image_tools_message()` — Already Marked DEPRECATED

**Lokasi:**
- `app/db/models.py:439`
- `app/db/facade.py:373`

```python
def add_image_tools_message(session_id: int, image_url: str) -> int | None:
    # DEPRECATED: image_tools messages are now unified into the standard 
    # message pipeline with image_paths
    return add_message(session_id, "image_tools", image_url)
```

**Aksi:** Hapus jika tidak ada caller. Jika ada, migrasikan ke `add_message(role, content, image_paths=[])`.

---

### 2. `SessionService.start_session()` — Already Marked DEPRECATED

**Lokasi:**
- `app/services/session_service.py:41`

```python
@staticmethod
def start_session(interface: str = "terminal") -> dict[str, Any]:
    """Mark the active session as started (sync).
    
    DEPRECATED: No longer creates connection log messages.
    """
    # Connection logging removed to prevent context pollution
```

**Aksi:** Audit usage dan hapus jika unused. Sama dengan `start_session_async()`.

---

### 3. `_rate_facts_batch()` — Sync Wrapper Marked DEPRECATED

**Lokasi:**
- `app/memory/memory_review.py:174`

```python
def _rate_facts_batch(facts: list[dict], conversation_context: str) -> dict[int, str]:
    """Rate multiple facts in a single LLM call (sync wrapper).
    
    DEPRECATED: Use async version _rate_facts_batch_async instead.
    This sync wrapper exists only for legacy compatibility.
    """
    import asyncio
    return asyncio.run(_rate_facts_batch_async(facts, conversation_context))
```

**Aksi:** Remove sync wrapper. Force all callers to use async version.

---

### 4. Automatic Vision Model Switching — Marked DEPRECATED

**Lokasi:**
- `app/llm_client.py:143`

```python
# DEPRECATED: Automatic vision model switching is removed in favor of 
# manual configuration and validation.
```

**Aksi:** Hapus code block deprecated jika masih ada.

---

## 🟡 MEDIUM: Circular Import Risk

### Lazy Import Pattern Overuse

**Pattern yang berulang di 10+ file:**

```python
# Inside function body instead of module top-level
async def some_function():
    from app.providers import get_ai_manager  # ← Lazy import
    ai_manager = await get_ai_manager()
```

**Lokasi:**
- `app/memory/memory.py:360`
- `app/memory/memory_review.py:82, 231`
- `app/memory/pcl.py:137, 241`
- `app/memory/embedder.py:9` (top-level import, OK)
- `app/memory/summarization.py:7` (top-level import, OK)
- `app/memory/profile.py:10` (top-level import, OK)
- `app/tools/memory_store.py:52`

**Analisis:** Lazy import digunakan untuk menghindari circular import karena:
- `app.providers` imports dari `app.providers.base`
- Multiple memory modules import dari providers
- Providers mungkin import dari memory untuk embedding

**Aksi:**
- 📋 AUDIT: Verify jika top-level import aman untuk semua module
- 🔨 CONSIDER: Refactor import structure jika circular dependency bisa dipecahkan
- 📋 DOCUMENT: Document which lazy imports are intentional vs workaround

---

## 🟡 MEDIUM: Duplicate Helper Functions

### 1. `_get_session_id(request: Request)` — Defined Twice

**Lokasi:**
- `app/api/endpoints/chat.py:21-24`
- `app/api/endpoints/sessions.py:26-29`

```python
# DUPLICATE - Same implementation
def _get_session_id(request: Request) -> str:
    client_host = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    return f"{client_host}_{hash(user_agent) % 10000}"
```

**Aksi:** Pindahkan ke `app.services.session_service` atau `app.api.utils`.

---

## 🟢 LOW: Code Quality Issues

### 1. Variable Shadowing di `sessions.py:140`

```python
async def api_clear_chat(request: Request, session_id: int | None = None):
    try:
        if session_id:
            session_id = session_id  # ← Useless reassignment
        else:
            active_session = await get_active_session_async()
            session_id = active_session["id"]
```

**Aksi:** Remove useless line 142.

---

### 2. Missing Async Versions for Decay Functions

**`app/memory/db_memory.py`:**
- `decay_facts()` — sync only, no async version
- `increment_importance()` — sync only, no async version

**Aksi:** Implement async versions jika dipanggil dari async context.

---

### 3. Incomplete Implementation

**`app/memory/review.py:run_decay_async()`:**
```python
# Lines 68-71
# I'll just use asyncio.to_thread for now because decay_facts logic
# is complex and it's already implemented.
# But wait, I'm supposed to make everything non-blocking.
# I'll use asyncio.to_thread for the sync decay_facts call.
count_episodic = await asyncio.to_thread(
    decay_facts, session_id=session_id, fact_type=FACT_TYPE_DYNAMIC
)
```

**Aksi:** Properly implement async version atau document as intentional blocking.

---

## 📋 Refactor Action Checklist

### Phase 2A: Dead Code Removal (Safe, Low Risk)

- [ ] Hapus stub endpoints `/memory/store` dan `/memory/retrieve` di `app/api/endpoints/memory.py`
- [ ] Hapus deprecated `add_image_tools_message()` jika tidak ada caller
- [ ] Hapus deprecated `SessionService.start_session()` jika tidak ada caller
- [ ] Hapus sync wrapper `_rate_facts_batch()` di `app/memory/memory_review.py`
- [ ] Fix useless reassignment di `app/api/endpoints/sessions.py:142`

---

### Phase 2B: Business Logic Extraction (Medium Risk)

- [ ] Buat `app.services.memory_service.MemoryService.rebuild_structured_memory_async()`
- [ ] Pindahkan inline pipeline logic dari `memory.py` endpoint ke service
- [ ] Buat `app.api.utils` atau pindahkan `_get_session_id()` ke `SessionService`
- [ ] Verify semua api endpoints hanya mengandung:
  - Request parsing
  - Service calls
  - Response formatting

---

### Phase 2C: Async Migration (High Risk, Requires Testing)

- [ ] Buat `app.memory.db_memory_facade` mirip `app.db.facade.Database`
- [ ] Audit dan migrasikan semua sync callers di FastAPI routes ke async
- [ ] Implement async versions untuk `decay_facts_async()` dan `increment_importance_async()`
- [ ] Verify `threading.local()` cache safety atau migrate ke `contextvars`
- [ ] Review `retrieve_memories_combined_async()` blocking `asyncio.to_thread()`

---

### Phase 2D: Import Structure Cleanup (Refactoring)

- [ ] Audit circular import dependency tree
- [ ] Document intentional lazy imports vs workaround lazy imports
- [ ] Consider refactor providers/memory import structure jika feasible
- [ ] Verify no direct `from app.db.models import X` bypass facade

---

## 📊 Statistics Summary

| Category | Count | Priority |
|----------|-------|----------|
| Dead endpoints (stub) | 2 | 🔴 HIGH |
| Deprecated functions | 5 | 🟡 MEDIUM |
| Duplicate sync/async in `app/db/` | 41 pairs | ✅ OK (facade wraps) |
| Duplicate sync/async in `app/memory/` | 13 pairs | 🟡 NEEDS FACADE |
| Duplicate helper functions | 1 | 🟡 MEDIUM |
| Circular import risk points | 10+ | 🟡 MEDIUM |
| Missing async implementations | 2 | 🟡 MEDIUM |
| Variable shadowing | 1 | 🟢 LOW |

---

## 🎯 Recommended Execution Order

1. **Phase 2A** (1-2 hours, safe)
2. **Phase 2B** (2-3 hours, moderate)
3. **Phase 2C** (4-6 hours, high risk, needs extensive testing)
4. **Phase 2D** (1-2 hours, refactoring)

**Total estimasi:** 8-13 hours untuk cleanup lengkap.

---

## ⚠️ Safety Constraints

1. **NEVER delete tables atau columns** — Only add
2. **NEVER drop sync functions** tanpa audit callers
3. **NEVER modify streaming pipeline** tanpa full testing
4. **Always run:**
   - `ruff check .`
   - `python3 -m py_compile` on changed files
   - Full test suite: `python3 -m pytest tests/ -v`
5. **Test manual via CLI dan web UI** setelah setiap phase

---

## 📁 Files Affected

### API Endpoints
- `app/api/endpoints/memory.py` — Stub removal, business logic extraction
- `app/api/endpoints/sessions.py` — Variable shadowing fix
- `app/api/endpoints/chat.py` — Helper deduplication

### Services
- `app/services/memory_service.py` — New method additions
- `app/services/session_service.py` — Helper function consolidation

### Database Layer
- `app/db/models.py` — Deprecated function removal (audit first)
- `app/db/facade.py` — Deprecated function removal (audit first)

### Memory Layer
- `app/memory/db_memory.py` — Add async versions, potential facade
- `app/memory/db_memory_facade.py` — NEW FILE (if created)
- `app/memory/memory_review.py` — Deprecated sync wrapper removal
- `app/memory/retrieval.py` — Cache safety audit
- `app/memory/review.py` — Better async implementation

### Utilities
- `app/api/utils.py` — NEW FILE (optional, for shared helpers)

---

**End of Phase 1 Audit Report**

**NEXT:** Tunggu ACC atau "Lanjut" dari user sebelum Phase 2 execution.