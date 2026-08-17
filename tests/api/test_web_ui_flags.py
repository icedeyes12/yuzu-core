from __future__ import annotations

import importlib

import pytest
from fastapi import Response

import main as main_module


def test_env_flag_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SERVE_WEB_UI", raising=False)
    assert main_module._env_flag("SERVE_WEB_UI", True) is True
    assert main_module._env_flag("SERVE_WEB_UI", False) is False
    monkeypatch.setenv("SERVE_WEB_UI", "false")
    assert main_module._env_flag("SERVE_WEB_UI", True) is False
    monkeypatch.setenv("SERVE_WEB_UI", "TRUE")
    assert main_module._env_flag("SERVE_WEB_UI", True) is True


def test_cors_config_default_preserves_legacy_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    cfg = main_module._cors_config()
    assert "https://chat.yuzuki.space" in cfg["allow_origins"]
    assert "https://yuzuki.space" in cfg["allow_origins"]
    assert cfg["allow_credentials"] is True
    assert cfg["allow_headers"] == ["*"]


def test_cors_config_origins_enable_credentials_and_byok_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CORS_ORIGINS", "https://app.example.com, https://dev.example.com"
    )
    cfg = main_module._cors_config()
    assert cfg["allow_origins"] == [
        "https://app.example.com",
        "https://dev.example.com",
    ]
    assert cfg["allow_credentials"] is True
    assert cfg["allow_methods"] == ["*"]
    assert cfg["allow_headers"] == ["*"]


def test_serve_web_ui_false_hides_html_routes_and_public_static(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SERVE_WEB_UI", "false")
    reloaded = importlib.reload(main_module)
    try:
        paths = set(reloaded.app.openapi()["paths"])
        for hidden in (
            "/",
            "/login",
            "/chat",
            "/chat/{session_id}",
            "/config",
            "/about",
        ):
            assert hidden not in paths
        assert "/health" in paths
        assert "/v1/profile" in paths
        # Authenticated private-image routes stay; the public /static mount goes.
        assert "/v1/static/uploads/{filename}" in paths
        assert not any(
            getattr(r, "path", None) == "/static" for r in reloaded.app.routes
        )
    finally:
        monkeypatch.delenv("SERVE_WEB_UI", raising=False)
        importlib.reload(main_module)


def test_serve_web_ui_default_keeps_html_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SERVE_WEB_UI", raising=False)
    reloaded = importlib.reload(main_module)
    try:
        paths = set(reloaded.app.openapi()["paths"])
        assert "/login" in paths
        assert "/chat/{session_id}" in paths
        assert "/config" in paths
        assert any(getattr(r, "path", None) == "/static" for r in reloaded.app.routes)
    finally:
        importlib.reload(main_module)


def test_session_cookie_uses_configured_samesite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.auth import session as session_module

    monkeypatch.setattr(session_module, "_COOKIE_SAMESITE", "none")
    monkeypatch.setattr(session_module, "_COOKIE_SECURE", True)
    response = Response()
    session_module.set_session_cookie(response, "test-token")
    set_cookie = response.headers["set-cookie"]
    assert "yuzu_session=test-token" in set_cookie
    assert "SameSite=none" in set_cookie
    assert "Secure" in set_cookie


def test_clear_session_cookie_mirrors_configured_attributes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.auth import session as session_module

    monkeypatch.setattr(session_module, "_COOKIE_SAMESITE", "none")
    monkeypatch.setattr(session_module, "_COOKIE_SECURE", True)
    response = Response()
    session_module.clear_session_cookie(response)
    set_cookie = response.headers["set-cookie"]
    assert "yuzu_session=" in set_cookie
    assert "Max-Age=0" in set_cookie
    assert "SameSite=none" in set_cookie
    assert "Secure" in set_cookie


def test_invalid_samesite_falls_back_to_lax(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.auth import session as session_module

    monkeypatch.setenv("COOKIE_SAMESITE", "bogus")
    monkeypatch.delattr(session_module, "_COOKIE_SAMESITE", raising=False)
    importlib.reload(session_module)
    try:
        assert session_module._COOKIE_SAMESITE == "lax"
    finally:
        monkeypatch.delenv("COOKIE_SAMESITE", raising=False)
        importlib.reload(session_module)


def _write_fake_dist(dist_path) -> None:
    """Create a minimal SPA dist (assets/ + HTML entries) for hermetic tests."""
    (dist_path / "assets").mkdir(parents=True)
    for name in (
        "index.html",
        "login.html",
        "chat.html",
        "config.html",
        "about.html",
    ):
        (dist_path / name).write_text(f"<html>{name}</html>")
    (dist_path / "favicon.ico").write_bytes(b"icon")


def test_serve_spa_true_serves_built_entries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    dist = tmp_path / "dist"
    _write_fake_dist(dist)

    monkeypatch.setenv("SERVE_WEB_UI", "true")
    monkeypatch.setenv("SERVE_SPA", "true")
    monkeypatch.setenv("SPA_DIST_DIR", str(dist))
    reloaded = importlib.reload(main_module)
    try:
        paths = set(reloaded.app.openapi()["paths"])
        for expected in (
            "/",
            "/login",
            "/chat",
            "/chat/{session_id}",
            "/config",
            "/about",
        ):
            assert expected in paths
        # SPA mode swaps the Jinja /static mount for the dist /assets mount.
        route_paths = {getattr(r, "path", None) for r in reloaded.app.routes}
        assert "/assets" in route_paths
        assert "/static" not in route_paths
        # /chat/{session_id} serves the SPA entry, not a Jinja template.
        chat_route = next(
            r
            for r in reloaded.app.routes
            if getattr(r, "path", None) == "/chat/{session_id}"
        )
        assert chat_route.endpoint.__name__ == "spa_chat_session"
    finally:
        monkeypatch.delenv("SERVE_SPA", raising=False)
        monkeypatch.delenv("SPA_DIST_DIR", raising=False)
        importlib.reload(main_module)


def test_serve_spa_missing_dist_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("SERVE_WEB_UI", "true")
    monkeypatch.setenv("SERVE_SPA", "true")
    monkeypatch.setenv("SPA_DIST_DIR", str(tmp_path / "does-not-exist"))
    with pytest.raises(RuntimeError, match="SERVE_SPA=true requires a built SPA"):
        importlib.reload(main_module)
    monkeypatch.delenv("SERVE_SPA", raising=False)
    monkeypatch.delenv("SPA_DIST_DIR", raising=False)
    importlib.reload(main_module)


def test_serve_spa_ignored_in_api_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    dist = tmp_path / "dist"
    _write_fake_dist(dist)

    monkeypatch.setenv("SERVE_WEB_UI", "false")
    monkeypatch.setenv("SERVE_SPA", "true")
    monkeypatch.setenv("SPA_DIST_DIR", str(dist))
    reloaded = importlib.reload(main_module)
    try:
        paths = set(reloaded.app.openapi()["paths"])
        assert "/login" not in paths
        assert "/chat/{session_id}" not in paths
        route_paths = {getattr(r, "path", None) for r in reloaded.app.routes}
        assert "/assets" not in route_paths
    finally:
        monkeypatch.delenv("SERVE_SPA", raising=False)
        monkeypatch.delenv("SPA_DIST_DIR", raising=False)
        importlib.reload(main_module)
