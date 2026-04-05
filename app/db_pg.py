# FILE: app/db_pg.py
# DESCRIPTION: PostgreSQL connection pool and raw SQL helpers.
#             Uses psycopg2 (NOT psycopg2-binary). ThreadedConnectionPool
#             for thread-safe reuse in CLI and web contexts.
#
# TERMUX NOTE: psycopg2 is installed as a regular package. No compilation needed.

from __future__ import annotations

import os
from typing import Any

from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from psycopg2.extensions import register_adapter, AsIs

# ── Env defaults (Termux/local dev) ──────────────────────────────────────────
_PG_HOST     = os.getenv("PGHOST", os.getenv("PG_HOST", "127.0.0.1"))
_PG_PORT     = os.getenv("PGPORT", os.getenv("PG_PORT", "5432"))
_PG_DBNAME   = os.getenv("PGDATABASE", os.getenv("PG_DBNAME", "yuzuki"))
_PG_USER     = os.getenv("PGUSER", os.getenv("PG_USER", "icedeyes12"))
_PG_PASSWORD = os.getenv("PGPASSWORD", os.getenv("PG_PASSWORD", ""))
_MIN_CONN    = 1
_MAX_CONN    = 10

# ── Global pool (lazy singleton) ──────────────────────────────────────────────
_pool: pool.ThreadedConnectionPool | None = None

class Vector:
    """Wrapper for pgvector list[float] that psycopg2 can serialize."""
    def __init__(self, data):
        self.data = data
    
    def __repr__(self):
        # pgvector uses square brackets, not curly braces
        return "[" + ",".join(str(x) for x in self.data) + "]"

def vector_sql(val):
    """Convert list[float] to Vector wrapper for psycopg2."""
    if val is None:
        return None
    return Vector(val)

# Register adapter for list type (when passing list to VECTOR column)
register_adapter(list, lambda v: AsIs(vector_sql(v)))

def _build_dsn() -> str:
    return (
        f"host={_PG_HOST} port={_PG_PORT} dbname={_PG_DBNAME} "
        f"user={_PG_USER} password={_PG_PASSWORD}"
    )


def get_pool() -> pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = pool.ThreadedConnectionPool(
            _MIN_CONN, _MAX_CONN,
            dsn=_build_dsn(),
            cursor_factory=RealDictCursor,
        )
        print(f"[db_pg] Pool created: {_PG_HOST}:{_PG_PORT}/{_PG_DBNAME}")
    return _pool


def close_pool():
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        print("[db_pg] Pool closed")


# ── Session context manager ──────────────────────────────────────────────────
class PgSession:
    """
    Context manager for one-off queries.
    Commits on success, rolls back on exception.

    Usage:
        with PgSession() as s:
            row = s.fetchone("SELECT * FROM profiles LIMIT 1")
            s.execute("INSERT INTO ...")
    """
    __slots__ = ('conn', 'autocommit')

    def __init__(self, autocommit: bool = False):
        self.autocommit = autocommit
        self.conn = None

    def __enter__(self) -> PgSession:
        p = get_pool()
        self.conn = p.getconn()
        self.conn.autocommit = self.autocommit
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
            get_pool().putconn(self.conn)
            self.conn = None

    # ── Core query methods ───────────────────────────────────────────────────
    def fetchone(self, query: str, params: tuple | dict | None = None) -> dict | None:
        """Return first row or None."""
        cur = self.conn.cursor()
        cur.execute(query, params)
        result = cur.fetchone()
        return dict(result) if result else None

    def fetchall(self, query: str, params: tuple | dict | None = None) -> list[dict]:
        """Return all rows as list of dicts."""
        cur = self.conn.cursor()
        cur.execute(query, params)
        return [dict(row) for row in cur.fetchall()]

    def execute(self, query: str, params: tuple | dict | None = None) -> None:
        """Execute a query (INSERT/UPDATE/DELETE)."""
        cur = self.conn.cursor()
        cur.execute(query, params)

    def execute_scalar(self, query: str, params: tuple | dict | None = None) -> Any:
        """Return first column of first row (e.g. COUNT, SUM)."""
        cur = self.conn.cursor()
        cur.execute(query, params)
        row = cur.fetchone()
        return row[0] if row else None

    def execute_returning(self, query: str, params: tuple | dict | None = None) -> dict | None:
        """Execute INSERT ... RETURNING * and return the row dict."""
        cur = self.conn.cursor()
        cur.execute(query, params)
        result = cur.fetchone()
        return dict(result) if result else None

    def execute_batch(self, query: str, params_list: list[tuple]) -> int:
        """Execute many rows (executemany). Returns rowcount."""
        cur = self.conn.cursor()
        cur.executemany(query, params_list)
        return cur.rowcount


# ── Module-level convenience functions ────────────────────────────────────────
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
    """Return True if query returns at least one row."""
    return pg_fetchone(query, params) is not None


def pg_scalar(query: str, params: tuple | dict | None = None) -> Any:
    return pg_fetchone(query, params)
