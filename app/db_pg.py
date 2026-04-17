# FILE: app/db_pg.py
# DESCRIPTION: PostgreSQL connection pool and raw SQL helpers.
#             psycopg v3 with both sync (ConnectionPool) and async (AsyncConnectionPool).
#             Use async versions in FastAPI routes, sync for legacy code.

from __future__ import annotations

import atexit
import os
from typing import Any

from psycopg_pool import AsyncConnectionPool, ConnectionPool
from psycopg.rows import dict_row

# ── Env defaults ────────────────────────────────────────────────────────────
_PG_HOST = os.getenv("PGHOST", os.getenv("PG_HOST", ""))
_PG_PORT = os.getenv("PGPORT", os.getenv("PG_PORT", ""))
_PG_DBNAME = os.getenv("PGDATABASE", os.getenv("PG_DBNAME", ""))
_PG_USER = os.getenv("PGUSER", os.getenv("PG_USER", ""))
_PG_PASSWORD = os.getenv("PGPASSWORD", os.getenv("PG_PASSWORD", ""))
_MIN_CONN = 1
_MAX_CONN = 10


# ── Vector literal formatting (pgvector uses square brackets) ───────────────
def vector_sql(val: list[float] | None) -> str | None:
    """Convert list[float] to pgvector literal string."""
    if val is None:
        return None
    return "[" + ",".join(str(x) for x in val) + "]"


# ── DSN builder ──────────────────────────────────────────────────────────────
def _build_dsn() -> str:
    if not all([_PG_HOST, _PG_PORT, _PG_DBNAME, _PG_USER]):
        raise RuntimeError(
            "PostgreSQL connection requires PGHOST, PGPORT, PGDATABASE, PGUSER env vars. "
            "Set them before starting the application."
        )
    return (
        f"host={_PG_HOST} port={_PG_PORT} dbname={_PG_DBNAME} "
        f"user={_PG_USER} password={_PG_PASSWORD}"
    )


# ── Global pools (lazy singletons) ───────────────────────────────────────────
_sync_pool: ConnectionPool | None = None
_async_pool: AsyncConnectionPool | None = None


def get_sync_pool() -> ConnectionPool:
    """Get or create the sync connection pool."""
    global _sync_pool
    if _sync_pool is None:
        _sync_pool = ConnectionPool(
            conninfo=_build_dsn(),
            min_size=_MIN_CONN,
            max_size=_MAX_CONN,
            kwargs={"row_factory": dict_row},
        )
        print(f"[db_pg] Sync pool created: {_PG_HOST}:{_PG_PORT}/{_PG_DBNAME}")
    return _sync_pool


async def get_async_pool() -> AsyncConnectionPool:
    """Get or create the async connection pool."""
    global _async_pool
    if _async_pool is None:
        _async_pool = AsyncConnectionPool(
            conninfo=_build_dsn(),
            min_size=_MIN_CONN,
            max_size=_MAX_CONN,
            kwargs={"row_factory": dict_row},
            open=False,
        )
        await _async_pool.open()
        print(f"[db_pg] Async pool created: {_PG_HOST}:{_PG_PORT}/{_PG_DBNAME}")
    return _async_pool


def close_sync_pool() -> None:
    """Close the sync connection pool."""
    global _sync_pool
    if _sync_pool is not None:
        _sync_pool.close()
        _sync_pool = None
        print("[db_pg] Sync pool closed")


async def close_async_pool() -> None:
    """Close the async connection pool."""
    global _async_pool
    if _async_pool is not None:
        await _async_pool.close()
        _async_pool = None
        print("[db_pg] Async pool closed")


# Register cleanup on exit
atexit.register(close_sync_pool)


# ── SYNC Session Context Manager ─────────────────────────────────────────────
class PgSession:
    """
    Sync context manager for database sessions.
    Commits on success, rolls back on exception.

    Usage:
        with PgSession() as s:
            row = s.fetchone("SELECT * FROM profiles LIMIT 1")
            s.execute("INSERT INTO ...")
    """

    __slots__ = ("conn", "autocommit", "_pool")

    def __init__(self, autocommit: bool = False):
        self.autocommit = autocommit
        self.conn = None
        self._pool = None

    def __enter__(self) -> PgSession:
        self._pool = get_sync_pool()
        self.conn = self._pool.getconn()
        if self.autocommit:
            self.conn.autocommit = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn is None:
            return
        try:
            if exc_type is not None:
                self.conn.rollback()
            elif not self.autocommit:
                self.conn.commit()
        except Exception:
            self.conn.rollback()
        finally:
            self._pool.putconn(self.conn)
            self.conn = None

    # ── Core query methods ─────────────────────────────────────────────────
    def fetchone(self, query: str, params: tuple | dict | None = None) -> dict | None:
        """Return first row or None."""
        with self.conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            return dict(row) if row else None

    def fetchall(self, query: str, params: tuple | dict | None = None) -> list[dict]:
        """Return all rows as list of dicts."""
        with self.conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            return [dict(row) for row in rows]

    def execute(self, query: str, params: tuple | dict | None = None) -> None:
        """Execute a query (INSERT/UPDATE/DELETE)."""
        with self.conn.cursor() as cur:
            cur.execute(query, params)

    def execute_scalar(self, query: str, params: tuple | dict | None = None) -> Any:
        """Return first column of first row (e.g. COUNT, SUM)."""
        with self.conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            return row[0] if row else None

    def execute_returning(self, query: str, params: tuple | dict | None = None) -> dict | None:
        """Execute INSERT ... RETURNING * and return the row dict."""
        with self.conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            return dict(row) if row else None

    def execute_batch(self, query: str, params_list: list[tuple]) -> int:
        """Execute many rows. Returns rowcount."""
        with self.conn.cursor() as cur:
            cur.executemany(query, params_list)
            return cur.rowcount or 0


# ── ASYNC Session Context Manager ────────────────────────────────────────────
class AsyncPgSession:
    """
    Async context manager for database sessions.
    Commits on success, rolls back on exception.

    Usage:
        async with AsyncPgSession() as s:
            row = await s.fetchone("SELECT * FROM profiles LIMIT 1")
            await s.execute("INSERT INTO ...")
    """

    __slots__ = ("conn", "autocommit", "_pool")

    def __init__(self, autocommit: bool = False):
        self.autocommit = autocommit
        self.conn = None
        self._pool = None

    async def __aenter__(self) -> AsyncPgSession:
        self._pool = await get_async_pool()
        self.conn = await self._pool.getconn()
        if self.autocommit:
            await self.conn.set_autocommit(True)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.conn is None:
            return
        try:
            if exc_type is not None:
                await self.conn.rollback()
            elif not self.autocommit:
                await self.conn.commit()
        except Exception:
            await self.conn.rollback()
        finally:
            await self._pool.putconn(self.conn)
            self.conn = None

    # ── Core query methods ─────────────────────────────────────────────────
    async def fetchone(self, query: str, params: tuple | dict | None = None) -> dict | None:
        """Return first row or None."""
        async with self.conn.cursor() as cur:
            await cur.execute(query, params)
            row = await cur.fetchone()
            return dict(row) if row else None

    async def fetchall(self, query: str, params: tuple | dict | None = None) -> list[dict]:
        """Return all rows as list of dicts."""
        async with self.conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()
            return [dict(row) for row in rows]

    async def execute(self, query: str, params: tuple | dict | None = None) -> None:
        """Execute a query (INSERT/UPDATE/DELETE)."""
        async with self.conn.cursor() as cur:
            await cur.execute(query, params)

    async def execute_scalar(self, query: str, params: tuple | dict | None = None) -> Any:
        """Return first column of first row (e.g. COUNT, SUM)."""
        async with self.conn.cursor() as cur:
            await cur.execute(query, params)
            row = await cur.fetchone()
            return row[0] if row else None

    async def execute_returning(self, query: str, params: tuple | dict | None = None) -> dict | None:
        """Execute INSERT ... RETURNING * and return the row dict."""
        async with self.conn.cursor() as cur:
            await cur.execute(query, params)
            row = await cur.fetchone()
            return dict(row) if row else None

    async def execute_batch(self, query: str, params_list: list[tuple]) -> int:
        """Execute many rows. Returns rowcount."""
        async with self.conn.cursor() as cur:
            await cur.executemany(query, params_list)
            return cur.rowcount or 0


# ── Module-level SYNC convenience functions ───────────────────────────────────
def pg_fetchone(query: str, params: tuple | dict | None = None) -> dict | None:
    with PgSession() as s:
        return s.fetchone(query, params)


def pg_fetchall(query: str, params: tuple | dict | None = None) -> list[dict]:
    with PgSession() as s:
        return s.fetchall(query, params)


def pg_execute(query: str, params: tuple | dict | None = None) -> None:
    with PgSession() as s:
        s.execute(query, params)


def pg_exists(query: str, params: tuple | dict | None = None) -> bool:
    return pg_fetchone(query, params) is not None


def pg_scalar(query: str, params: tuple | dict | None = None) -> Any:
    return pg_fetchone(query, params)


# ── Module-level ASYNC convenience functions ──────────────────────────────────
async def pg_fetchone_async(query: str, params: tuple | dict | None = None) -> dict | None:
    async with AsyncPgSession() as s:
        return await s.fetchone(query, params)


async def pg_fetchall_async(query: str, params: tuple | dict | None = None) -> list[dict]:
    async with AsyncPgSession() as s:
        return await s.fetchall(query, params)


async def pg_execute_async(query: str, params: tuple | dict | None = None) -> None:
    async with AsyncPgSession() as s:
        await s.execute(query, params)


async def pg_exists_async(query: str, params: tuple | dict | None = None) -> bool:
    return await pg_fetchone_async(query, params) is not None


async def pg_scalar_async(query: str, params: tuple | dict | None = None) -> Any:
    return await pg_fetchone_async(query, params)


# ── Legacy aliases (for backward compat) ─────────────────────────────────────
get_pool = get_sync_pool
close_pool = close_sync_pool
