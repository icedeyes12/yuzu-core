# Test Modernization Plan — Yuzu Companion

> **Created:** 2026-06-30
> **Source:** Implementation review of snake-feet refactor (F1-F13)
> **Scope:** 19 failing tests across 2 files
> **Status:** Planned (not started)

---

## Root Cause Summary

All 19 failures share a single root cause: **the test suite was written against the pre-refactor `Database` facade API, which exposed `*_async`-suffixed methods and sync wrappers. F1 intentionally removed the sync mirror and consolidated the facade to async-only with clean names (no `_async` suffix).**

The tests were never updated to match. This is not a regression — the production code is correct. The tests are stale.

Additionally, `pytest-asyncio` was missing from the environment, masking async test failures. Installing it resolved 19 of the original 38 failures, leaving these 19 as the true modernization backlog.

---

## Scope

| File | Failings | Failures |
|------|----------|----------|
| `tests/test_fs_operations.py` | 1 | T-01 |
| `tests/test_tenant_isolation.py` | 18 | T-02 through T-19 |

---

## Summary Table

| ID | Test | Classification | Action | Priority |
|----|------|---------------|--------|----------|
| T-01 | `test_ls_tmp_dir` | Environment-specific | Update | Low |
| T-02 | `test_sync_add_message_rejects_empty_user_id` | Obsolete (sync removed) | Rewrite | High |
| T-03 | `test_sync_add_message_rejects_none_user_id` | Obsolete (sync removed) | Rewrite | High |
| T-04 | `test_get_messages_rejects_whitespace_user_id` | Obsolete (sync removed) | Rewrite | High |
| T-05 | `test_clear_session_rejects_empty_user_id` | Obsolete (sync removed) | Rewrite | High |
| T-06 | `test_async_add_message_rejects_empty_user_id` | Valid, needs update | Update | High |
| T-07 | `test_add_system_note_rejects_falsy_default` | Obsolete (sync removed) | Rewrite | High |
| T-08 | `test_tenant_a_reads_own_profile` | Valid, needs update | Update | Medium |
| T-09 | `test_tenant_b_reads_own_profile` | Valid, needs update | Update | Medium |
| T-10 | `test_profiles_are_distinct` | Valid, needs update | Update | Medium |
| T-11 | `test_tenant_a_update_does_not_affect_tenant_b` | Valid, needs update | Update | Medium |
| T-12 | `test_tenant_a_sees_only_own_sessions` | Valid, needs update | Update | Medium |
| T-13 | `test_tenant_b_sees_only_own_sessions` | Valid, needs update | Update | Medium |
| T-14 | `test_tenant_a_active_session_is_own` | Valid, needs update | Update | Medium |
| T-15 | `test_tenant_b_active_session_is_own` | Valid, needs update | Update | Medium |
| T-16 | `test_tenant_a_cannot_delete_tenant_b_session` | Valid, needs update | Update | Medium |
| T-17 | `test_tenant_a_can_delete_own_session` | Valid, needs update | Update | Medium |
| T-18 | `test_tenant_a_history_excludes_tenant_b` | Valid, needs update | Update | Medium |
| T-19 | `test_tenant_b_history_excludes_tenant_a` | Valid, needs update | Update | Medium |

---

## Recommended Execution Order

1. **T-01** (Low) — trivial path fix
2. **T-02 through T-07** (High) — security boundary tests. These verify `TenantScopeError` guards. Convert sync calls to async, rename `_async` methods to facade names.
3. **T-08 through T-19** (Medium) — tenant isolation integration tests. Mechanical rename from `Database.<method>_async(...)` to `Database.<method>(...)` with keyword arg adjustments.

**Additional:** Add `pytest-asyncio` to `pyproject.toml` dev dependencies and configure `asyncio_mode = "auto"`.

---

## Detailed Entries

### T-01: `test_ls_tmp_dir`

| Field | Value |
|-------|-------|
| File | `tests/test_fs_operations.py:19` |
| Classification | Environment-specific |
| Current code | `result = execute_ls({"path": "/tmp"})` |
| Issue | `/tmp` does not exist on Termux (Android). Test was written for standard Linux. |
| Intent | Verify the `ls` tool can list a directory and returns `{"ok": True, "data": {"listing": ...}}` |
| Intent still valid? | Yes — the tool works, the path is wrong |
| Action | Update |
| Priority | Low |
| Status | Planned |

---

### T-02: `test_sync_add_message_rejects_empty_user_id`

| Field | Value |
|-------|-------|
| File | `tests/test_tenant_isolation.py:725` |
| Classification | Obsolete (sync API removed by F1) |
| Current code | `Database.add_message("user", "hi", user_id="")` called synchronously |
| Issue | `add_message` is now `async def`. Calling without `await` returns a coroutine; the `_require_user_id` guard never fires. Sync facade surface was intentionally removed. |
| Intent | Verify that falsy `user_id` raises `TenantScopeError` at the facade boundary |
| Intent still valid? | Yes — the guard behavior is critical |
| Action | Rewrite — convert to `async def` test, use `await Database.add_message("user", "hi", user_id="")` |
| Priority | High |
| Status | Planned |

---

### T-03: `test_sync_add_message_rejects_none_user_id`

| Field | Value |
|-------|-------|
| File | `tests/test_tenant_isolation.py:729` |
| Classification | Obsolete (sync API removed by F1) |
| Current code | `Database.add_message("user", "hi", user_id=None)` called synchronously |
| Issue | Same as T-02 |
| Intent | Same as T-02 but with `None` |
| Intent still valid? | Yes |
| Action | Rewrite — convert to async, `await Database.add_message("user", "hi", user_id=None)` |
| Priority | High |
| Status | Planned |

---

### T-04: `test_get_messages_rejects_whitespace_user_id`

| Field | Value |
|-------|-------|
| File | `tests/test_tenant_isolation.py:733` |
| Classification | Obsolete (sync API removed by F1) |
| Current code | `Database.get_messages(user_id="   ")` called synchronously |
| Issue | `get_messages` is now `async def` |
| Intent | Verify whitespace-only `user_id` raises `TenantScopeError` |
| Intent still valid? | Yes |
| Action | Rewrite — convert to async, `await Database.get_messages(user_id="   ")` |
| Priority | High |
| Status | Planned |

---

### T-05: `test_clear_session_rejects_empty_user_id`

| Field | Value |
|-------|-------|
| File | `tests/test_tenant_isolation.py:737` |
| Classification | Obsolete (sync API removed by F1) |
| Current code | `Database.clear_session(user_id="")` called synchronously |
| Issue | `clear_session` is now `async def` |
| Intent | Verify empty `user_id` raises `TenantScopeError` |
| Intent still valid? | Yes |
| Action | Rewrite — convert to async, `await Database.clear_session(user_id="")` |
| Priority | High |
| Status | Planned |

---

### T-06: `test_async_add_message_rejects_empty_user_id`

| Field | Value |
|-------|-------|
| File | `tests/test_tenant_isolation.py:742` |
| Classification | Still valid, needs updating |
| Current code | `await Database.add_message_async("user", "hi", user_id="")` |
| Issue | Facade exposes this as `Database.add_message(...)` (no `_async` suffix) |
| Intent | Verify `TenantScopeError` on empty `user_id` via the async path |
| Intent still valid? | Yes |
| Action | Update — change `Database.add_message_async(...)` to `Database.add_message(...)` |
| Priority | High |
| Status | Planned |

---

### T-07: `test_add_system_note_rejects_falsy_default`

| Field | Value |
|-------|-------|
| File | `tests/test_tenant_isolation.py:746` |
| Classification | Obsolete (sync API removed by F1) |
| Current code | `Database.add_system_note("note", user_id="")` called synchronously |
| Issue | `add_system_note` is now `async def`. Test also references a historical regression about `user_id: str = ""` default — that default was removed. |
| Intent | Verify falsy `user_id` raises `TenantScopeError` |
| Intent still valid? | Yes |
| Action | Rewrite — convert to async, `await Database.add_system_note("note", user_id="")` |
| Priority | High |
| Status | Planned |

---

### T-08: `test_tenant_a_reads_own_profile`

| Field | Value |
|-------|-------|
| File | `tests/test_tenant_isolation.py:759` |
| Classification | Still valid, needs updating |
| Current code | `await Database.get_profile_async(TENANT_A)` |
| Issue | Facade exposes this as `Database.get_profile(user_id=TENANT_A)` |
| Intent | Verify tenant A can read their own profile |
| Intent still valid? | Yes |
| Action | Update — rename to `Database.get_profile(user_id=TENANT_A)` |
| Priority | Medium |
| Status | Planned |

---

### T-09: `test_tenant_b_reads_own_profile`

| Field | Value |
|-------|-------|
| File | `tests/test_tenant_isolation.py:765` |
| Classification | Still valid, needs updating |
| Current code | `await Database.get_profile_async(TENANT_B)` |
| Issue | Same as T-08 |
| Intent | Verify tenant B can read their own profile |
| Intent still valid? | Yes |
| Action | Update — rename to `Database.get_profile(user_id=TENANT_B)` |
| Priority | Medium |
| Status | Planned |

---

### T-10: `test_profiles_are_distinct`

| Field | Value |
|-------|-------|
| File | `tests/test_tenant_isolation.py:770` |
| Classification | Still valid, needs updating |
| Current code | `await Database.get_profile_async(TENANT_A)` and `..._async(TENANT_B)` |
| Issue | Same — `get_profile_async` → `get_profile` |
| Intent | Verify tenant A and B have distinct profiles |
| Intent still valid? | Yes |
| Action | Update — rename both calls |
| Priority | Medium |
| Status | Planned |

---

### T-11: `test_tenant_a_update_does_not_affect_tenant_b`

| Field | Value |
|-------|-------|
| File | `tests/test_tenant_isolation.py:778` |
| Classification | Still valid, needs updating |
| Current code | `await Database.update_profile_async({"display_name": "Modified A"}, TENANT_A)` |
| Issue | Facade exposes `Database.update_profile(data, user_id)` |
| Intent | Verify cross-tenant update isolation |
| Intent still valid? | Yes |
| Action | Update — rename to `Database.update_profile({"display_name": "Modified A"}, user_id=TENANT_A)` |
| Priority | Medium |
| Status | Planned |

---

### T-12: `test_tenant_a_sees_only_own_sessions`

| Field | Value |
|-------|-------|
| File | `tests/test_tenant_isolation.py:791` |
| Classification | Still valid, needs updating |
| Current code | `await Database.get_all_sessions_async(TENANT_A)` |
| Issue | Facade exposes `Database.get_all_sessions(user_id=TENANT_A)` |
| Intent | Verify tenant A sees only their own sessions |
| Intent still valid? | Yes |
| Action | Update — rename to `Database.get_all_sessions(user_id=TENANT_A)` |
| Priority | Medium |
| Status | Planned |

---

### T-13: `test_tenant_b_sees_only_own_sessions`

| Field | Value |
|-------|-------|
| File | `tests/test_tenant_isolation.py:797` |
| Classification | Still valid, needs updating |
| Current code | `await Database.get_all_sessions_async(TENANT_B)` |
| Issue | Same as T-12 |
| Intent | Same for tenant B |
| Intent still valid? | Yes |
| Action | Update — rename to `Database.get_all_sessions(user_id=TENANT_B)` |
| Priority | Medium |
| Status | Planned |

---

### T-14: `test_tenant_a_active_session_is_own`

| Field | Value |
|-------|-------|
| File | `tests/test_tenant_isolation.py:803` |
| Classification | Still valid, needs updating |
| Current code | `await Database.get_active_session_async(TENANT_A)` |
| Issue | Facade exposes `Database.get_active_session(user_id=TENANT_A)` |
| Intent | Verify tenant A's active session is their own |
| Intent still valid? | Yes |
| Action | Update — rename to `Database.get_active_session(user_id=TENANT_A)` |
| Priority | Medium |
| Status | Planned |

---

### T-15: `test_tenant_b_active_session_is_own`

| Field | Value |
|-------|-------|
| File | `tests/test_tenant_isolation.py:808` |
| Classification | Still valid, needs updating |
| Current code | `await Database.get_active_session_async(TENANT_B)` |
| Issue | Same as T-14 |
| Intent | Same for tenant B |
| Intent still valid? | Yes |
| Action | Update — rename to `Database.get_active_session(user_id=TENANT_B)` |
| Priority | Medium |
| Status | Planned |

---

### T-16: `test_tenant_a_cannot_delete_tenant_b_session`

| Field | Value |
|-------|-------|
| File | `tests/test_tenant_isolation.py:813` |
| Classification | Still valid, needs updating |
| Current code | `await Database.delete_session_async(SESSION_B, TENANT_A)` |
| Issue | Facade exposes `Database.delete_session(session_id, user_id=...)`. Positional arg order changed. |
| Intent | Verify cross-tenant delete is blocked |
| Intent still valid? | Yes |
| Action | Update — rename to `Database.delete_session(SESSION_B, user_id=TENANT_A)` |
| Priority | Medium |
| Status | Planned |

---

### T-17: `test_tenant_a_can_delete_own_session`

| Field | Value |
|-------|-------|
| File | `tests/test_tenant_isolation.py:819` |
| Classification | Still valid, needs updating |
| Current code | `await Database.delete_session_async(SESSION_A, TENANT_A)` |
| Issue | Same as T-16 |
| Intent | Verify tenant can delete their own session |
| Intent still valid? | Yes |
| Action | Update — rename to `Database.delete_session(SESSION_A, user_id=TENANT_A)` |
| Priority | Medium |
| Status | Planned |

---

### T-18: `test_tenant_a_history_excludes_tenant_b`

| Field | Value |
|-------|-------|
| File | `tests/test_tenant_isolation.py:829` |
| Classification | Still valid, needs updating |
| Current code | `await Database.get_chat_history_async(session_id=SESSION_A, user_id=TENANT_A)` |
| Issue | Facade exposes `Database.get_chat_history(session_id=..., user_id=...)` |
| Intent | Verify tenant A's chat history excludes tenant B's messages |
| Intent still valid? | Yes |
| Action | Update — drop `_async` suffix |
| Priority | Medium |
| Status | Planned |

---

### T-19: `test_tenant_b_history_excludes_tenant_a`

| Field | Value |
|-------|-------|
| File | `tests/test_tenant_isolation.py:839` |
| Classification | Still valid, needs updating |
| Current code | `await Database.get_chat_history_async(session_id=SESSION_B, user_id=TENANT_B)` |
| Issue | Same as T-18 |
| Intent | Same for tenant B |
| Intent still valid? | Yes |
| Action | Update — drop `_async` suffix |
| Priority | Medium |
| Status | Planned |

---

## Additional Recommendation

Add `pytest-asyncio` to `pyproject.toml` dev dependencies and configure `asyncio_mode = "auto"`. This would have surfaced the async test failures clearly from the start and prevented the masking issue.

---

*This document is the canonical implementation plan for test modernization. All items are Planned. Do not mark any as completed until implementation is verified.*
