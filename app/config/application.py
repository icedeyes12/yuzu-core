from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str


@dataclass(frozen=True)
class OAuthProviderConfig:
    name: str
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    issuer: str = ""
    jwks_url: str = ""


@dataclass(frozen=True)
class ApplicationConfig:
    database: DatabaseConfig
    app_base_url: str
    session_secret: str
    cookie_secure: bool
    oauth_providers: dict[str, OAuthProviderConfig] = field(default_factory=dict)
    log_level: str = "INFO"
    termux_bash: str | None = None
    default_cwd: str | None = None

    @classmethod
    def from_env(cls) -> ApplicationConfig:
        import os
        from app.db.connection import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

        db = DatabaseConfig(
            host=DB_HOST,
            port=int(DB_PORT),
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
        )
        return cls(
            database=db,
            app_base_url=os.environ.get("APP_BASE_URL", ""),
            session_secret=os.environ.get("SESSION_SECRET", ""),
            cookie_secure=os.environ.get("COOKIE_SECURE", "true").lower() == "true",
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            termux_bash=os.environ.get("TERMUX_BASH"),
            default_cwd=os.environ.get("HOME") or None,
        )
