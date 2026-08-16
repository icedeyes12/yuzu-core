from __future__ import annotations

from app.db.connection import (
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
    db_settings,
)

DB_ENV_KEYS = [
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "PGHOST",
    "PGPORT",
    "PGDATABASE",
    "PGUSER",
    "PGPASSWORD",
    "PG_HOST",
    "PG_PORT",
    "PG_DBNAME",
    "PG_USER",
    "PG_PASSWORD",
]


def _clear_db_env(monkeypatch) -> None:
    """Remove every DB-related env var (incl. any loaded from .env)."""
    for key in DB_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults_when_nothing_set(monkeypatch):
    _clear_db_env(monkeypatch)
    assert db_settings() == {
        "host": "localhost",
        "port": "5432",
        "dbname": "yuzu",
        "user": "postgres",
        "password": "",
    }


def test_pg_underscore_aliases_used_when_other_tiers_unset(monkeypatch):
    _clear_db_env(monkeypatch)
    monkeypatch.setenv("PG_HOST", "alias-host")
    monkeypatch.setenv("PG_PORT", "6000")
    monkeypatch.setenv("PG_DBNAME", "alias-db")
    monkeypatch.setenv("PG_USER", "alias-user")
    monkeypatch.setenv("PG_PASSWORD", "alias-pw")
    assert db_settings() == {
        "host": "alias-host",
        "port": "6000",
        "dbname": "alias-db",
        "user": "alias-user",
        "password": "alias-pw",
    }


def test_pg_wins_over_pg_underscore(monkeypatch):
    _clear_db_env(monkeypatch)
    monkeypatch.setenv("PG_HOST", "alias-host")
    monkeypatch.setenv("PGHOST", "main-host")
    monkeypatch.setenv("PG_PORT", "6000")
    monkeypatch.setenv("PGPORT", "7000")
    assert db_settings()["host"] == "main-host"
    assert db_settings()["port"] == "7000"


def test_db_wins_over_pg_and_pg_underscore(monkeypatch):
    _clear_db_env(monkeypatch)
    monkeypatch.setenv("PG_HOST", "alias-host")
    monkeypatch.setenv("PGHOST", "main-host")
    monkeypatch.setenv("DB_HOST", "legacy-host")
    monkeypatch.setenv("PG_PORT", "6000")
    monkeypatch.setenv("PGPORT", "7000")
    monkeypatch.setenv("DB_PORT", "8000")
    assert db_settings()["host"] == "legacy-host"
    assert db_settings()["port"] == "8000"


def test_explicit_empty_value_is_not_default(monkeypatch):
    _clear_db_env(monkeypatch)
    monkeypatch.setenv("DB_HOST", "")
    monkeypatch.setenv("PGHOST", "main-host")
    # getenv returns "" because the var is set; it does not fall through
    assert db_settings()["host"] == ""


def test_legacy_constants_consistent_with_db_settings():
    settings = db_settings()
    assert DB_HOST == settings["host"]
    assert DB_PORT == int(settings["port"])
    assert DB_NAME == settings["dbname"]
    assert DB_USER == settings["user"]
    assert DB_PASSWORD == settings["password"]
