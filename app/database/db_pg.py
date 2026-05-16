# FILE: app/database/db_pg.py
# DESCRIPTION: PostgreSQL connection pool and query helpers (psycopg v3).
#              Provides both sync (PgSession) and async (AsyncPgSession)
#              context managers backed by lazy-initialized pools.

from __future__ import annotations

import atexit
import os
from typing import Any
from pathlib import Path

from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, ConnectionPool

from app.logging_config import get_logger

# Load .env from project root (relative to this module)
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

# PostgreSQL connection parameters
DB_HOST = os.getenv("DB_HOST", os.getenv("PGHOST", "localhost"))
DB_PORT = int(os.getenv("DB_PORT", os.getenv("PGPORT", "5432")))
DB_NAME = os.getenv("DB_NAME", os.getenv("PGDATABASE", "yuzu"))
DB_USER = os.getenv("DB_USER", os.getenv("PGUSER", "postgres"))
DB_PASSWORD = os.getenv("DB_PASSWORD", os.getenv("PGPASSWORD", ""))

log = get_logger(__name__)

# ── Connection settings (env-driven) ──────────────────────────────────────────
_PG_HOST = os.getenv("PGHOST", os.getenv("PG_HOST", ""))
_PG_PORT = os.getenv("PGPORT", os.getenv("PG_PORT", ""))
_PG_DBNAME = os.getenv("PGDATABASE", os.getenv("PG_DBNAME", ""))
_PG_USER = os.getenv("PGUSER", os.getenv("PG_USER", ""))
_PG_PASSWORD = os.getenv("PGPASSWORD", os.getenv("PG_PASSWORD", ""))
_MIN_CONN = 1
_MAX_CONN = 10


# ── Vector literal formatting (pgvector uses square brackets) ───────────────
def vector_sql(val: list[float] | None) -> str | None:
    """Convert a list[float] to a pgvector literal string."""
    if val is None:
        return None
    return "[" + ",".join(str(x) for x in val) + "]"


# ── DSN builder ──────────────────────────────────────────────────────────────
def _build_dsn() -> str:
    if not all([_PG_HOST, _PG_PORT, _PG_DBNAME, _PG_USER]):
        raise RuntimeError(
            "PostgreSQL connection requires PGHOST, PGPORT, PGDATABASE, PGUSER "
            "env vars. Set them before starting the application."
        )
    return (
        f"host={_PG_HOST} port={_PG_PORT} dbname={_PG_DBNAME} "
        f"user={_PG_USER} password={_PG_PASSWORD}"
    )


# ── Global pools (lazy singletons) ───────────────────────────────────────────
_sync_pool: ConnectionPool | None = None
_async_pool: AsyncConnectionPool | None = None


def get_sync_pool() -> ConnectionPool:
    """Return the lazily-created sync connection pool."""
    global _sync_pool
    if _sync_pool is None:
        _sync_pool = ConnectionPool(
            conninfo=_build_dsn(),
            min_size=_MIN_CONN,
            max_size=_MAX_CONN,
            kwargs={"row_factory": dict_row},
        )
        log.info("sync pool created: %s:%s/%s", _PG_HOST, _PG_PORT, _PG_DBNAME)
    return _sync_pool


async def get_async_pool() -> AsyncConnectionPool:
    """Return the lazily-created async connection pool."""
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
        log.info("async pool created: %s:%s/%s", _PG_HOST, _PG_PORT, _PG_DBNAME)
    return _async_pool


def close_sync_pool() -> None:
    """Close the sync connection pool, if open."""
    global _sync_pool
    if _sync_pool is not None:
        _sync_pool.close()
        _sync_pool = None
        log.info("sync pool closed")


async def close_async_pool() -> None:
    """Close the async connection pool, if open."""
    global _async_pool
    if _async_pool is not None:
        await _async_pool.close()
        _async_pool = None
        log.info("async pool closed")


atexit.register(close_sync_pool)


# ── SYNC session context manager ──────────────────────────────────────────────
class PgSession:
    """Sync DB session. Commits on success, rolls back on exception.

    Example:
        with PgSession() as s:
            row = s.fetchone("SELECT * FROM profiles LIMIT 1")
            s.execute("INSERT INTO ...")
    """

    __slots__ = ("conn", "autocommit", "_pool")

    def __init__(self, autocommit: bool = False) -> None:
        self.autocommit = autocommit
        self.conn = None
        self._pool: ConnectionPool | None = None

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

    def fetchone(self, query: str, params: tuple | dict | None = None) -> dict | None:
        """Return the first row as a dict, or None."""
        with self.conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            return dict(row) if row else None

    def fetchall(self, query: str, params: tuple | dict | None = None) -> list[dict]:
        """Return all rows as a list of dicts."""
        with self.conn.cursor() as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def execute(self, query: str, params: tuple | dict | None = None) -> None:
        """Execute a non-returning query (INSERT/UPDATE/DELETE/DDL)."""
        with self.conn.cursor() as cur:
            cur.execute(query, params)

    def execute_scalar(self, query: str, params: tuple | dict | None = None) -> Any:
        """Return the first column of the first row (e.g. COUNT, SUM)."""
        with self.conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            return list(row.values())[0] if row else None

    def execute_returning(self, query: str, params: tuple | dict | None = None) -> dict | None:
        """Execute INSERT/UPDATE ... RETURNING * and return the row dict."""
        with self.conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            return dict(row) if row else None

    def execute_batch(self, query: str, params_list: list[tuple]) -> int:
        """Execute many parameter sets. Returns rowcount."""
        with self.conn.cursor() as cur:
            cur.executemany(query, params_list)
            return cur.rowcount or 0


# ── ASYNC session context manager ─────────────────────────────────────────────
class AsyncPgSession:
    """Async DB session. Commits on success, rolls back on exception.

    Example:
        async with AsyncPgSession() as s:
            row = await s.fetchone("SELECT * FROM profiles LIMIT 1")
            await s.execute("INSERT INTO ...")
    """

    __slots__ = ("conn", "autocommit", "_pool")

    def __init__(self, autocommit: bool = False) -> None:
        self.autocommit = autocommit
        self.conn = None
        self._pool: AsyncConnectionPool | None = None

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

    async def fetchone(self, query: str, params: tuple | dict | None = None) -> dict | None:
        """Return the first row as a dict, or None."""
        async with self.conn.cursor() as cur:
            await cur.execute(query, params)
            row = await cur.fetchone()
            return dict(row) if row else None

    async def fetchall(self, query: str, params: tuple | dict | None = None) -> list[dict]:
        """Return all rows as a list of dicts."""
        async with self.conn.cursor() as cur:
            await cur.execute(query, params)
            return [dict(row) for row in await cur.fetchall()]

    async def execute(self, query: str, params: tuple | dict | None = None) -> None:
        """Execute a non-returning query (INSERT/UPDATE/DELETE/DDL)."""
        async with self.conn.cursor() as cur:
            await cur.execute(query, params)

    async def execute_scalar(self, query: str, params: tuple | dict | None = None) -> Any:
        """Return the first column of the first row (e.g. COUNT, SUM)."""
        async with self.conn.cursor() as cur:
            await cur.execute(query, params)
            row = await cur.fetchone()
            return list(row.values())[0] if row else None

    async def execute_returning(self, query: str, params: tuple | dict | None = None) -> dict | None:
        """Execute INSERT/UPDATE ... RETURNING * and return the row dict."""
        async with self.conn.cursor() as cur:
            await cur.execute(query, params)
            row = await cur.fetchone()
            return dict(row) if row else None

    async def execute_batch(self, query: str, params_list: list[tuple]) -> int:
        """Execute many parameter sets. Returns rowcount."""
        async with self.conn.cursor() as cur:
            await cur.executemany(query, params_list)
            return cur.rowcount or 0


# ── Module-level convenience helpers ──────────────────────────────────────────
# Each helper opens a fresh PgSession / AsyncPgSession, runs the query,
# and returns. Useful for one-off queries that don't need a transaction.


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
    """True when *query* returns at least one row."""
    return pg_fetchone(query, params) is not None


def pg_scalar(query: str, params: tuple | dict | None = None) -> Any:
    """Return the first column of the first row (e.g. COUNT, SUM)."""
    with PgSession() as s:
        return s.execute_scalar(query, params)


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
    """True when *query* returns at least one row."""
    return await pg_fetchone_async(query, params) is not None


async def pg_scalar_async(query: str, params: tuple | dict | None = None) -> Any:
    """Return the first column of the first row (e.g. COUNT, SUM)."""
    async with AsyncPgSession() as s:
        return await s.execute_scalar(query, params)


__all__ = [
    # Pools
    "get_sync_pool",
    "get_async_pool",
    "close_sync_pool",
    "close_async_pool",
    # Session context managers
    "PgSession",
    "AsyncPgSession",
    # Sync helpers
    "pg_fetchone",
    "pg_fetchall",
    "pg_execute",
    "pg_exists",
    "pg_scalar",
    # Async helpers
    "pg_fetchone_async",
    "pg_fetchall_async",
    "pg_execute_async",
    "pg_exists_async",
    "pg_scalar_async",
    # pgvector helper
    "vector_sql",
]
