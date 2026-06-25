# FILE: tests/test_tenant_isolation.py
# DESCRIPTION: Phase 4.4 — Anti-Regression Guardrails for multi-tenant isolation.
#
# Two test categories:
#   1. Static SQL inspection — every tenant-scoped query must bind user_id
#   2. Multi-tenant integration — two mock tenants cannot cross-access data
#
# No live database required. All DB access is mocked at the connection layer.

from __future__ import annotations

import re
from datetime import datetime

import pytest

# ── Static test targets ──────────────────────────────────────────────────────
from app.db import queries as queries_mod
from app.memory import db_memory_queries as mem_queries_mod
from app.memory.db_memory_queries import (
    build_metadata_conditions,
    build_update_last_accessed_query,
)

# ── Integration test targets ─────────────────────────────────────────────────
from app.db import Database
from app.db.facade import TenantScopeError
from app.memory.db_memory import (
    get_fact_by_id_async,
    get_facts_by_session_async,
    invalidate_fact_async,
    save_fact_async,
    search_similar_async,
)

# ============================================================================
# Constants
# ============================================================================

TENANT_A = "00000000-0000-7000-8000-00000000000a"
TENANT_B = "00000000-0000-7000-8000-00000000000b"
SESSION_A = "00000000-0000-7000-8000-0000000000a1"
SESSION_B = "00000000-0000-7000-8000-0000000000b1"

TENANT_TABLES = {"profiles", "chat_sessions", "messages", "semantic_facts"}


# ============================================================================
# Category 1: Static SQL Inspection Tests
# ============================================================================
#
# Every SQL constant that touches a tenant-scoped table (profiles,
# chat_sessions, messages, semantic_facts) must either:
#   - Contain "user_id" in its text, OR
#   - Appear in a documented exemption set below with a clear reason.
#
# Any FUTURE SQL constant that touches a tenant table without user_id and
# is NOT in an exemption set will cause a test failure. This is the
# anti-regression guardrail: it prevents new unscoped queries from
# silently entering the codebase.

INSERT_EXEMPTIONS = {
    # INSERT statements — user_id is a column VALUE, not a WHERE filter.
    "SQL_PROFILE_INSERT_DEFAULT",
    "SQL_PROFILE_INSERT_DEFAULT_RETURNING",
    "SQL_SESSION_INSERT",
    "SQL_MESSAGE_INSERT",
    "SQL_IDENTITY_INSERT",
    "SQL_SESSION_TOKEN_CREATE",
    "SQL_FACT_INSERT",
}

AUTH_INFRA_EXEMPTIONS = {
    # Auth / session-token infrastructure — system-level, not tenant-scoped.
    "SQL_PROFILE_UNCLAIMED_LOOKUP",
    "SQL_AUTH_ME_LOOKUP",
    "SQL_IDENTITY_LOOKUP",
    "SQL_SESSION_TOKEN_VALIDATE",
    "SQL_SESSION_TOKEN_REVOKE",
}

PROFILE_PK_EXEMPTIONS = {
    # Profile by primary key — the id column IS the user_id (inherent scoping).
    "SQL_PROFILE_SELECT_BY_ID",
    "SQL_PROFILE_UPDATE_AVATAR",
}

SYSTEM_AGGREGATE_EXEMPTIONS = {
    # System-wide aggregate / migration queries — not tenant-scoped.
    "SQL_ENC_TOTAL_MESSAGES",
    "SQL_ENC_ENCRYPTED_MESSAGES",
    "SQL_ENC_TOTAL_KEYS",
    "SQL_ENC_ENCRYPTED_KEYS",
    "SQL_MESSAGE_SELECT_ENCRYPTED",
    "SQL_MESSAGE_SELECT_CONTENT_BY_ID",
    "SQL_MESSAGE_UPDATE_DECRYPTED",
    "SQL_MESSAGE_UPDATE",
    "SQL_MESSAGE_RECENT_SYSTEM_GLOBAL",
}

SESSION_PK_EXEMPTIONS = {
    # Session PK operations — ownership verified upstream via
    # SQL_SESSION_OWNERSHIP_CHECK or the session_id was obtained from a
    # user-scoped query.
    # TODO (Phase 4.2 hardening): add AND user_id = %s for defense-in-depth.
    "SQL_SESSION_UPDATE_MEMORY",
    "SQL_SESSION_INCREMENT_COUNT",
    "SQL_SESSION_RESET_COUNT_AND_MEMORY",
    "SQL_SESSION_OWNERSHIP_CHECK",
    "SQL_SESSIONS_RECENT_ACTIVE",
}

MESSAGE_SESSION_EXEMPTIONS = {
    # Message queries scoped by session_id (UUID, hard to guess).
    # Defense-in-depth gap: should also filter by user_id.
    # TODO (Phase 4.2 hardening): add AND user_id = %s.
    "SQL_MESSAGE_SELECT_ASC_LIMIT",
    "SQL_MESSAGE_SELECT_DESC_LIMIT",
    "SQL_MESSAGE_SELECT_ASC_ALL",
    "SQL_MESSAGE_SELECT_AFTER_ID",
    "SQL_MESSAGE_DELETE_FOR_SESSION",
    "SQL_MESSAGE_COUNT_CONVERSATIONAL",
    "SQL_MESSAGE_CONVERSATION_SUMMARY",
    "SQL_MESSAGE_RECENT_SYSTEM_FOR_SESSION",
    "SQL_MESSAGE_HISTORY_FOR_AI_ASC_LIMIT",
    "SQL_MESSAGE_HISTORY_FOR_AI_DESC_LIMIT",
    "SQL_MESSAGE_HISTORY_FOR_AI_ASC_ALL",
}

ALL_EXEMPTIONS = (
    INSERT_EXEMPTIONS
    | AUTH_INFRA_EXEMPTIONS
    | PROFILE_PK_EXEMPTIONS
    | SYSTEM_AGGREGATE_EXEMPTIONS
    | SESSION_PK_EXEMPTIONS
    | MESSAGE_SESSION_EXEMPTIONS
)


def _get_sql_constants(module):
    """Extract all SQL_* string constants from a module's namespace."""
    return {
        name: getattr(module, name)
        for name in dir(module)
        if name.startswith("SQL_") and isinstance(getattr(module, name), str)
    }


def _references_tenant_table(sql: str) -> bool:
    sql_lower = sql.lower()
    return any(table in sql_lower for table in TENANT_TABLES)


class TestStaticSQLScoping:
    """Every tenant-scoped SQL constant must bind user_id or be exempted."""

    def test_queries_py_tenant_queries_have_user_id(self):
        """All non-exempt SQL constants in queries.py touching tenant tables
        must contain 'user_id' in their text."""
        constants = _get_sql_constants(queries_mod)
        violations = []
        for name, sql in sorted(constants.items()):
            if not _references_tenant_table(sql):
                continue
            if name in ALL_EXEMPTIONS:
                continue
            if "user_id" not in sql.lower():
                violations.append(name)
        assert not violations, (
            f"queries.py constants touching tenant tables without user_id "
            f"and not exempted: {violations}"
        )

    def test_db_memory_queries_have_user_id(self):
        """All SQL constants in db_memory_queries.py touching semantic_facts
        must contain 'user_id'."""
        constants = _get_sql_constants(mem_queries_mod)
        violations = []
        for name, sql in sorted(constants.items()):
            if not _references_tenant_table(sql):
                continue
            if name in ALL_EXEMPTIONS:
                continue
            if "user_id" not in sql.lower():
                violations.append(name)
        assert not violations, (
            f"db_memory_queries.py constants without user_id: {violations}"
        )

    def test_deleted_unscoped_constants_absent(self):
        """The 7 unscoped constants deleted in Phase 4.1 must not exist."""
        deleted = [
            "SQL_PROFILE_SELECT_FIRST",
            "SQL_SESSION_SELECT_ACTIVE",
            "SQL_SESSION_SELECT_ALL",
            "SQL_SESSION_DEACTIVATE_ALL",
            "SQL_SESSION_ACTIVATE_ONE",
            "SQL_SESSION_RENAME",
            "SQL_SESSION_DELETE",
        ]
        for name in deleted:
            assert not hasattr(queries_mod, name), (
                f"{name} was deleted in Phase 4.1 but still exists"
            )

    def test_build_metadata_conditions_requires_user_id(self):
        """build_metadata_conditions must raise ValueError on missing user_id."""
        with pytest.raises(ValueError, match="user_id is required"):
            build_metadata_conditions()
        with pytest.raises(ValueError, match="user_id is required"):
            build_metadata_conditions(user_id="")
        with pytest.raises(ValueError, match="user_id is required"):
            build_metadata_conditions(user_id=None)

    def test_build_metadata_conditions_includes_user_id(self):
        """build_metadata_conditions must include user_id in conditions."""
        conditions, params = build_metadata_conditions(user_id=TENANT_A)
        assert "user_id = %s" in conditions
        assert TENANT_A in params

    def test_build_update_last_accessed_includes_user_id(self):
        """The multi-id UPDATE builder must include user_id scope."""
        sql = build_update_last_accessed_query(3)
        assert "user_id" in sql.lower()

    def test_guardrail_new_constants_need_user_id_or_exemption(self):
        """Any SQL constant (from either file) touching a tenant table must
        contain user_id or be in the exemption list. This is the CI gate
        that prevents new unscoped queries from entering the codebase."""
        constants = {
            **_get_sql_constants(queries_mod),
            **_get_sql_constants(mem_queries_mod),
        }
        for name, sql in sorted(constants.items()):
            if not _references_tenant_table(sql):
                continue
            if name in ALL_EXEMPTIONS:
                continue
            assert "user_id" in sql.lower(), (
                f"{name} touches a tenant table but has no user_id. "
                f"Add user_id scoping or add to exemption list with a reason."
            )


# ============================================================================
# Category 2: Multi-Tenant Integration Tests
# ============================================================================
#
# A MockTenantDB simulates user_id-scoped query filtering without a real
# PostgreSQL. Two tenants (A and B) are pre-seeded with distinct profiles,
# sessions, messages, and semantic facts. Every test verifies that one
# tenant cannot read, update, or append to the other's data.


class MockTenantDB:
    """In-memory multi-tenant database for isolation testing.

    Simulates user_id-scoped query filtering. All data is stored in plain
    dicts/lists and filtered by user_id extracted from the SQL parameters.
    """

    def __init__(self):
        self.profiles: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}
        self.messages: list[dict] = []
        self.facts: list[dict] = []
        self.queries: list[tuple] = []
        self._next_id = 1000

    def seed(self):
        """Pre-populate with two tenants' data."""
        now = datetime.now()
        self.profiles = {
            TENANT_A: {
                "id": TENANT_A,
                "display_name": "Tenant A",
                "partner_name": "Partner A",
                "affection": 50,
                "theme": "dark",
                "memory_state": {},
                "session_history": {},
                "global_knowledge": {},
                "providers_config": {},
                "context": {},
                "image_model": "default",
                "vision_model": "default",
                "avatar_url": None,
                "created_at": now,
                "updated_at": now,
            },
            TENANT_B: {
                "id": TENANT_B,
                "display_name": "Tenant B",
                "partner_name": "Partner B",
                "affection": 75,
                "theme": "light",
                "memory_state": {},
                "session_history": {},
                "global_knowledge": {},
                "providers_config": {},
                "context": {},
                "image_model": "default",
                "vision_model": "default",
                "avatar_url": None,
                "created_at": now,
                "updated_at": now,
            },
        }
        self.sessions = {
            SESSION_A: {
                "id": SESSION_A,
                "user_id": TENANT_A,
                "name": "A's Chat",
                "is_active": True,
                "message_count": 2,
                "memory_state": {},
                "deleted_at": None,
                "created_at": now,
                "updated_at": now,
            },
            SESSION_B: {
                "id": SESSION_B,
                "user_id": TENANT_B,
                "name": "B's Chat",
                "is_active": True,
                "message_count": 2,
                "memory_state": {},
                "deleted_at": None,
                "created_at": now,
                "updated_at": now,
            },
        }
        self.messages = [
            {
                "id": 1,
                "session_id": SESSION_A,
                "user_id": TENANT_A,
                "role": "user",
                "content": "Hello from A",
                "image_paths": "[]",
                "timestamp": now,
            },
            {
                "id": 2,
                "session_id": SESSION_A,
                "user_id": TENANT_A,
                "role": "assistant",
                "content": "Hi A!",
                "image_paths": "[]",
                "timestamp": now,
            },
            {
                "id": 3,
                "session_id": SESSION_B,
                "user_id": TENANT_B,
                "role": "user",
                "content": "Hello from B",
                "image_paths": "[]",
                "timestamp": now,
            },
            {
                "id": 4,
                "session_id": SESSION_B,
                "user_id": TENANT_B,
                "role": "assistant",
                "content": "Hi B!",
                "image_paths": "[]",
                "timestamp": now,
            },
        ]
        self.facts = [
            {
                "id": 1,
                "user_id": TENANT_A,
                "fact_type": "static",
                "content": "Tenant A likes coffee",
                "embedding": None,
                "metadata": {"category": "Preference"},
                "invalid_at": None,
                "created_at": now,
                "last_accessed": now,
            },
            {
                "id": 2,
                "user_id": TENANT_A,
                "fact_type": "dynamic",
                "content": "Tenant A visited Paris",
                "embedding": None,
                "metadata": {"category": "Experience", "session_id": SESSION_A},
                "invalid_at": None,
                "created_at": now,
                "last_accessed": now,
            },
            {
                "id": 3,
                "user_id": TENANT_B,
                "fact_type": "static",
                "content": "Tenant B likes tea",
                "embedding": None,
                "metadata": {"category": "Preference"},
                "invalid_at": None,
                "created_at": now,
                "last_accessed": now,
            },
            {
                "id": 4,
                "user_id": TENANT_B,
                "fact_type": "dynamic",
                "content": "Tenant B visited Tokyo",
                "embedding": None,
                "metadata": {"category": "Experience", "session_id": SESSION_B},
                "invalid_at": None,
                "created_at": now,
                "last_accessed": now,
            },
        ]

    # ── user_id extraction ────────────────────────────────────────────────

    def _extract_user_id(self, sql: str, params) -> str | None:
        """Extract the user_id parameter value from a SQL query + params."""
        if not params:
            return None
        params = list(params)
        # Pattern 1: 'user_id = %s' or 'user_id=%s' in a WHERE clause
        m = re.search(r"user_id\s*=\s*(%s)", sql, re.IGNORECASE)
        if m:
            uid_pos = m.start(1)
            idx = sum(1 for p in re.finditer(r"%s", sql) if p.start() < uid_pos)
            return params[idx] if idx < len(params) else None
        # Pattern 2: 'FROM profiles WHERE id = %s' (id IS the user_id)
        if re.search(r"from\s+profiles\s+where\s+id\s*=\s*%s", sql, re.IGNORECASE):
            return params[0] if params else None
        return None

    # ── fetchone ──────────────────────────────────────────────────────────

    async def fetchone(self, sql, params=None):
        self.queries.append((sql, params))
        sl = sql.lower()

        # Profile by ID
        if "from profiles" in sl and "where id" in sl:
            uid = params[0] if params else None
            row = self.profiles.get(uid)
            return dict(row) if row else None

        # Active session for user
        if "from chat_sessions" in sl and "is_active" in sl:
            uid = params[0] if params else None
            for s in self.sessions.values():
                if s["user_id"] == uid and s["is_active"] and not s.get("deleted_at"):
                    return dict(s)
            return None

        # Session ownership check (returns user_id)
        if "from chat_sessions" in sl and "where id" in sl:
            sid = params[0] if params else None
            s = self.sessions.get(sid)
            return {"user_id": s["user_id"]} if s else None

        # Fact by ID + user_id
        if "from semantic_facts" in sl and "where id" in sl:
            uid = self._extract_user_id(sql, params)
            fact_id = params[0] if params else None
            for f in self.facts:
                if f["id"] == fact_id and f["user_id"] == uid:
                    return dict(f)
            return None

        # Fact dup check (by content + user_id)
        if "from semantic_facts" in sl and "content" in sl:
            uid = self._extract_user_id(sql, params)
            content = params[1] if params and len(params) > 1 else None
            for f in self.facts:
                if f["user_id"] == uid and f["content"] == content:
                    return dict(f)
            return None

        return None

    # ── fetchall ──────────────────────────────────────────────────────────

    async def fetchall(self, sql, params=None):
        self.queries.append((sql, params))
        sl = sql.lower()

        # All sessions for user (has ORDER BY)
        if "from chat_sessions" in sl and "order by" in sl:
            uid = params[0] if params else None
            return [
                dict(s)
                for s in self.sessions.values()
                if s["user_id"] == uid and not s.get("deleted_at")
            ]

        # Messages by session_id
        if "from messages" in sl and "session_id" in sl:
            sid = params[0] if params else None
            return [dict(m) for m in self.messages if m["session_id"] == sid]

        # Semantic facts with user_id filter
        if "semantic_facts" in sl:
            uid = self._extract_user_id(sql, params)
            if not uid:
                return []
            results = [
                dict(f)
                for f in self.facts
                if f["user_id"] == uid and not f.get("invalid_at")
            ]
            # Apply fact_type filter if present in SQL
            ft_match = re.search(r"fact_type\s*=\s*%s", sql, re.IGNORECASE)
            if ft_match:
                ft_idx = sum(
                    1 for p in re.finditer(r"%s", sql) if p.start() < ft_match.start()
                )
                if ft_idx < len(params):
                    ft = params[ft_idx]
                    results = [f for f in results if f["fact_type"] == ft]
            return results

        return []

    # ── execute ───────────────────────────────────────────────────────────

    async def execute(self, sql, params=None):
        self.queries.append((sql, params))
        sl = sql.lower()

        # Profile update — parse SET clause and apply column values
        if "update profiles" in sl:
            set_match = re.search(r"set\s+(.+?)\s+where", sl)
            if set_match:
                col_names = re.findall(r"(\w+)\s*=\s*%s", set_match.group(1))
                uid = params[-1] if params else None
                if uid in self.profiles:
                    for i, col in enumerate(col_names):
                        if i < len(params) - 1:
                            self.profiles[uid][col] = params[i]
                    self.profiles[uid]["updated_at"] = datetime.now()

        # Session deactivate for user
        elif "update chat_sessions" in sl and "is_active = false" in sl:
            uid = self._extract_user_id(sql, params)
            if uid:
                for s in self.sessions.values():
                    if s["user_id"] == uid:
                        s["is_active"] = False

        # Session activate (scoped)
        elif "update chat_sessions" in sl and "is_active = true" in sl:
            sid = params[1] if params and len(params) > 1 else None
            uid = self._extract_user_id(sql, params)
            if sid in self.sessions and uid:
                if self.sessions[sid]["user_id"] == uid:
                    self.sessions[sid]["is_active"] = True

        # Session soft delete (scoped)
        elif "update chat_sessions" in sl and "deleted_at" in sl:
            sid = params[0] if params else None
            uid = self._extract_user_id(sql, params)
            if sid in self.sessions and uid:
                if self.sessions[sid]["user_id"] == uid:
                    self.sessions[sid]["deleted_at"] = datetime.now()

        # Fact invalidate (scoped by user_id)
        elif "update semantic_facts" in sl and "invalid_at" in sl:
            uid = self._extract_user_id(sql, params)
            fact_id = params[2] if params and len(params) > 2 else None
            for f in self.facts:
                if f["id"] == fact_id and f["user_id"] == uid:
                    f["invalid_at"] = datetime.now()

        # Fact decay / metadata update (scoped by user_id)
        elif "update semantic_facts" in sl:
            uid = self._extract_user_id(sql, params)
            fact_id = params[2] if params and len(params) > 2 else None
            for f in self.facts:
                if f["id"] == fact_id and f["user_id"] == uid:
                    f["last_accessed"] = datetime.now()

    # ── execute_returning ─────────────────────────────────────────────────

    async def execute_returning(self, sql, params=None):
        self.queries.append((sql, params))
        sl = sql.lower()
        self._next_id += 1
        now = datetime.now()

        # Session insert
        if "insert into chat_sessions" in sl:
            uid = params[0] if params else None
            row = {
                "id": f"new-session-{self._next_id}",
                "user_id": uid,
                "name": params[1] if len(params) > 1 else "New Chat",
                "is_active": params[2] if len(params) > 2 else False,
                "message_count": 0,
                "memory_state": {},
                "deleted_at": None,
                "created_at": now,
                "updated_at": now,
            }
            self.sessions[row["id"]] = row
            return dict(row)

        # Message insert
        if "insert into messages" in sl:
            row = {
                "id": self._next_id,
                "session_id": params[0] if params else None,
                "user_id": params[1] if len(params) > 1 else None,
                "role": params[2] if len(params) > 2 else "user",
                "content": params[3] if len(params) > 3 else "",
                "image_paths": "[]",
                "timestamp": now,
            }
            self.messages.append(row)
            return dict(row)

        # Fact insert
        if "insert into semantic_facts" in sl:
            row = {
                "id": self._next_id,
                "user_id": params[0] if params else None,
                "fact_type": params[1] if len(params) > 1 else "static",
                "content": params[2] if len(params) > 2 else "",
                "embedding": None,
                "metadata": {},
                "invalid_at": None,
                "created_at": now,
                "last_accessed": now,
            }
            self.facts.append(row)
            return dict(row)

        # Profile insert
        if "insert into profiles" in sl:
            uid = f"new-profile-{self._next_id}"
            row = {
                "id": uid,
                "display_name": "New User",
                "partner_name": "Yuzu",
                "affection": 0,
                "theme": "dark",
                "memory_state": {},
                "session_history": {},
                "global_knowledge": {},
                "providers_config": {},
                "context": {},
                "image_model": "default",
                "vision_model": "default",
                "avatar_url": None,
                "created_at": now,
                "updated_at": now,
            }
            self.profiles[uid] = row
            return dict(row)

        return None


class MockAsyncPgSession:
    """Mock AsyncPgSession that delegates to a MockTenantDB instance."""

    def __init__(self, db: MockTenantDB):
        self._db = db

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def fetchone(self, query, params=None):
        return await self._db.fetchone(query, params)

    async def fetchall(self, query, params=None):
        return await self._db.fetchall(query, params)

    async def execute(self, query, params=None):
        await self._db.execute(query, params)

    async def execute_returning(self, query, params=None):
        return await self._db.execute_returning(query, params)

    async def execute_scalar(self, query, params=None):
        row = await self._db.fetchone(query, params)
        if row:
            return list(row.values())[0]
        return None


@pytest.fixture
def tenant_db(monkeypatch):
    """Create a pre-seeded mock DB and patch all DB access points."""
    db = MockTenantDB()
    db.seed()

    # Patch module-level async helpers in models_async
    monkeypatch.setattr("app.db.models_async.pg_fetchone_async", db.fetchone)
    monkeypatch.setattr("app.db.models_async.pg_fetchall_async", db.fetchall)
    monkeypatch.setattr("app.db.models_async.pg_execute_async", db.execute)
    monkeypatch.setattr(
        "app.db.models_async.AsyncPgSession",
        lambda *a, **kw: MockAsyncPgSession(db),
    )

    # Patch module-level async helpers in db_memory
    monkeypatch.setattr("app.memory.db_memory.pg_fetchone_async", db.fetchone)
    monkeypatch.setattr("app.memory.db_memory.pg_fetchall_async", db.fetchall)
    monkeypatch.setattr("app.memory.db_memory.pg_execute_async", db.execute)
    monkeypatch.setattr(
        "app.memory.db_memory.AsyncPgSession",
        lambda *a, **kw: MockAsyncPgSession(db),
    )

    return db


# ── Tenant Scope Guard (Phase 4.4 boundary check) ──────────────────────────


class TestTenantScopeGuard:
    """Falsy user_id must fail loud at the facade boundary — never reach a
    tenant-scoped query. Pure unit tests: the guard fires before any DB
    access, so no tenant_db fixture is needed."""

    def test_sync_add_message_rejects_empty_user_id(self):
        with pytest.raises(TenantScopeError):
            Database.add_message("user", "hi", user_id="")

    def test_sync_add_message_rejects_none_user_id(self):
        with pytest.raises(TenantScopeError):
            Database.add_message("user", "hi", user_id=None)  # type: ignore[arg-type]

    def test_get_messages_rejects_whitespace_user_id(self):
        with pytest.raises(TenantScopeError):
            Database.get_messages(user_id="   ")

    def test_clear_session_rejects_empty_user_id(self):
        with pytest.raises(TenantScopeError):
            Database.clear_session(user_id="")

    @pytest.mark.asyncio
    async def test_async_add_message_rejects_empty_user_id(self):
        with pytest.raises(TenantScopeError):
            await Database.add_message_async("user", "hi", user_id="")

    def test_add_tool_result_now_requires_user_id(self):
        # Regression: add_tool_result previously called _resolve_session_id
        # with a single arg (TypeError at runtime). Now keyword-only user_id
        # + guard — falsy user_id raises TenantScopeError instead.
        with pytest.raises(TenantScopeError):
            Database.add_tool_result("bash", "out", user_id="")

    def test_add_system_note_rejects_falsy_default(self):
        # Regression: add_system_note had `user_id: str = ""` (a falsy default
        # that silently scoped queries to an empty tenant). The default is now
        # removed; falsy user_id raises TenantScopeError.
        with pytest.raises(TenantScopeError):
            Database.add_system_note("note", user_id="")


# ── Profile Isolation ────────────────────────────────────────────────────────


class TestProfileIsolation:
    @pytest.mark.asyncio
    async def test_tenant_a_reads_own_profile(self, tenant_db):
        profile = await Database.get_profile_async(TENANT_A)
        assert profile["id"] == TENANT_A
        assert profile["display_name"] == "Tenant A"

    @pytest.mark.asyncio
    async def test_tenant_b_reads_own_profile(self, tenant_db):
        profile = await Database.get_profile_async(TENANT_B)
        assert profile["id"] == TENANT_B
        assert profile["display_name"] == "Tenant B"

    @pytest.mark.asyncio
    async def test_profiles_are_distinct(self, tenant_db):
        a = await Database.get_profile_async(TENANT_A)
        b = await Database.get_profile_async(TENANT_B)
        assert a["id"] != b["id"]
        assert a["display_name"] != b["display_name"]

    @pytest.mark.asyncio
    async def test_tenant_a_update_does_not_affect_tenant_b(self, tenant_db):
        await Database.update_profile_async({"display_name": "Modified A"}, TENANT_A)
        b = await Database.get_profile_async(TENANT_B)
        assert b["display_name"] == "Tenant B"
        a = await Database.get_profile_async(TENANT_A)
        assert a["display_name"] == "Modified A"


# ── Session Isolation ─────────────────────────────────────────────────────────


class TestSessionIsolation:
    @pytest.mark.asyncio
    async def test_tenant_a_sees_only_own_sessions(self, tenant_db):
        sessions = await Database.get_all_sessions_async(TENANT_A)
        assert len(sessions) == 1
        assert sessions[0]["id"] == SESSION_A

    @pytest.mark.asyncio
    async def test_tenant_b_sees_only_own_sessions(self, tenant_db):
        sessions = await Database.get_all_sessions_async(TENANT_B)
        assert len(sessions) == 1
        assert sessions[0]["id"] == SESSION_B

    @pytest.mark.asyncio
    async def test_tenant_a_active_session_is_own(self, tenant_db):
        session = await Database.get_active_session_async(TENANT_A)
        assert session["id"] == SESSION_A

    @pytest.mark.asyncio
    async def test_tenant_b_active_session_is_own(self, tenant_db):
        session = await Database.get_active_session_async(TENANT_B)
        assert session["id"] == SESSION_B

    @pytest.mark.asyncio
    async def test_tenant_a_cannot_delete_tenant_b_session(self, tenant_db):
        await Database.delete_session_async(SESSION_B, TENANT_A)
        # Session_B must still exist and be undeleted
        assert tenant_db.sessions[SESSION_B]["deleted_at"] is None

    @pytest.mark.asyncio
    async def test_tenant_a_can_delete_own_session(self, tenant_db):
        await Database.delete_session_async(SESSION_A, TENANT_A)
        assert tenant_db.sessions[SESSION_A]["deleted_at"] is not None


# ── Message Isolation ─────────────────────────────────────────────────────────


class TestMessageIsolation:
    @pytest.mark.asyncio
    async def test_tenant_a_history_excludes_tenant_b(self, tenant_db):
        history = await Database.get_chat_history_async(
            session_id=SESSION_A, user_id=TENANT_A
        )
        assert len(history) == 2
        for msg in history:
            assert msg["session_id"] == SESSION_A
            assert "from A" in msg["content"] or "Hi A" in msg["content"]

    @pytest.mark.asyncio
    async def test_tenant_b_history_excludes_tenant_a(self, tenant_db):
        history = await Database.get_chat_history_async(
            session_id=SESSION_B, user_id=TENANT_B
        )
        assert len(history) == 2
        for msg in history:
            assert msg["session_id"] == SESSION_B
            assert "from B" in msg["content"] or "Hi B" in msg["content"]


# ── Memory (semantic_facts) Isolation ─────────────────────────────────────────


class TestMemoryIsolation:
    @pytest.mark.asyncio
    async def test_tenant_a_facts_exclude_tenant_b(self, tenant_db):
        facts = await get_facts_by_session_async(session_id=SESSION_A, user_id=TENANT_A)
        assert len(facts) > 0
        for f in facts:
            assert f["user_id"] == TENANT_A
            assert "Tenant A" in f["content"]

    @pytest.mark.asyncio
    async def test_tenant_b_facts_exclude_tenant_a(self, tenant_db):
        facts = await get_facts_by_session_async(session_id=SESSION_B, user_id=TENANT_B)
        assert len(facts) > 0
        for f in facts:
            assert f["user_id"] == TENANT_B
            assert "Tenant B" in f["content"]

    @pytest.mark.asyncio
    async def test_tenant_a_cannot_read_tenant_b_fact_by_id(self, tenant_db):
        """Fact ID 3 belongs to Tenant_B; Tenant_A must get None."""
        fact = await get_fact_by_id_async(3, TENANT_A)
        assert fact is None

    @pytest.mark.asyncio
    async def test_tenant_a_can_read_own_fact_by_id(self, tenant_db):
        fact = await get_fact_by_id_async(1, TENANT_A)
        assert fact is not None
        assert fact["user_id"] == TENANT_A

    @pytest.mark.asyncio
    async def test_tenant_a_cannot_invalidate_tenant_b_fact(self, tenant_db):
        await invalidate_fact_async(3, TENANT_A)
        fact_3 = next(f for f in tenant_db.facts if f["id"] == 3)
        assert fact_3["invalid_at"] is None

    @pytest.mark.asyncio
    async def test_tenant_a_can_invalidate_own_fact(self, tenant_db):
        await invalidate_fact_async(1, TENANT_A)
        fact_1 = next(f for f in tenant_db.facts if f["id"] == 1)
        assert fact_1["invalid_at"] is not None

    @pytest.mark.asyncio
    async def test_save_fact_associates_with_calling_tenant(self, tenant_db):
        fact_id = await save_fact_async(
            session_id=SESSION_A,
            content="Tenant A new fact",
            embedding=None,
            fact_type="static",
            user_id=TENANT_A,
        )
        assert fact_id is not None
        new_fact = next(f for f in tenant_db.facts if f["id"] == fact_id)
        assert new_fact["user_id"] == TENANT_A

    @pytest.mark.asyncio
    async def test_dup_check_is_tenant_scoped(self, tenant_db):
        """Tenant_A saving the same content as Tenant_B must not be rejected."""
        fact_id = await save_fact_async(
            session_id=SESSION_A,
            content="Tenant B likes tea",
            embedding=None,
            fact_type="static",
            user_id=TENANT_A,
        )
        assert fact_id is not None, (
            "Dup check must be per-user — Tenant_A should save same content "
            "as Tenant_B without rejection"
        )

    @pytest.mark.asyncio
    async def test_search_similar_is_tenant_scoped(self, tenant_db):
        dummy_vec = [0.1] * 4096
        results = await search_similar_async(
            embedding=dummy_vec,
            user_id=TENANT_A,
            limit=10,
        )
        for r in results:
            assert r["user_id"] == TENANT_A

    @pytest.mark.asyncio
    async def test_memory_functions_reject_missing_user_id(self, tenant_db):
        with pytest.raises(ValueError):
            await get_fact_by_id_async(1, None)
        with pytest.raises(ValueError):
            await get_facts_by_session_async(SESSION_A, user_id=None)
        with pytest.raises(ValueError):
            await invalidate_fact_async(1, None)
        with pytest.raises(ValueError):
            await search_similar_async([0.1] * 4096, user_id=None)


class TestSyncMemoryGuards:
    """Sync memory functions must also reject missing user_id —
    previously only async variants had guards."""

    def test_sync_invalidate_fact_requires_user_id(self):
        from app.memory.db_memory import invalidate_fact

        with pytest.raises(ValueError):
            invalidate_fact(1, user_id=None)

    def test_sync_search_similar_requires_user_id(self):
        from app.memory.db_memory import search_similar

        with pytest.raises(ValueError):
            search_similar([0.1] * 4096, user_id=None)

    def test_sync_search_trgm_requires_user_id(self):
        from app.memory.db_memory import search_trgm

        with pytest.raises(ValueError):
            search_trgm("test query", user_id=None)

    def test_sync_search_tsv_requires_user_id(self):
        from app.memory.db_memory import search_tsv

        with pytest.raises(ValueError):
            search_tsv("test query", user_id=None)

    def test_sync_save_fact_requires_user_id(self):
        from app.memory.db_memory import save_fact

        with pytest.raises(ValueError):
            save_fact(session_id=None, content="x", embedding=None, fact_type="static", user_id=None)


class TestRetrieveMemoryGuards:
    """retrieve_memory entry points must reject missing user_id
    instead of silently returning empty results."""

    def test_retrieve_memory_rejects_missing_user_id(self):
        from app.memory.retrieval import retrieve_memory

        with pytest.raises(ValueError):
            retrieve_memory(SESSION_A, user_id=None)

    @pytest.mark.asyncio
    async def test_retrieve_memory_async_rejects_missing_user_id(self):
        from app.memory.retrieval import retrieve_memory_async

        with pytest.raises(ValueError):
            await retrieve_memory_async(SESSION_A, user_id=None)
