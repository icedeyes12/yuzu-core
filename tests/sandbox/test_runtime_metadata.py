from __future__ import annotations

from app.services.sandbox_runtime_metadata import parse_os_release


def test_parse_os_release_returns_canonical_runtime_metadata():
    metadata = parse_os_release(
        'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\n'
        "ID=debian\n"
        'VERSION_ID="13"\n'
        "VERSION_CODENAME=trixie\n"
    )

    assert metadata == {
        "distribution": "debian",
        "version_id": "13",
        "codename": "trixie",
        "pretty_name": "Debian GNU/Linux 13 (trixie)",
    }


def test_parse_os_release_rejects_incomplete_metadata():
    try:
        parse_os_release("ID=debian\n")
    except ValueError as error:
        assert "VERSION_ID" in str(error)
    else:
        raise AssertionError("Incomplete os-release must be rejected")
