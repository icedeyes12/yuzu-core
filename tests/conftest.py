from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def user_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def api_client():
    from fastapi.testclient import TestClient

    from main import app

    with TestClient(app) as client:
        yield client


def pytest_collection_modifyitems(items):
    import pytest

    domain_markers = {
        "api": "contract",
        "contracts": "contract",
        "cli": "unit",
        "db": "db",
        "integration": "integration",
        "e2e": "e2e",
        "frontend": "contract",
        "memory": "unit",
        "providers": "unit",
        "regression": "contract",
        "runtime": "integration",
        "services": "unit",
        "tools": "unit",
    }
    for item in items:
        domain = item.path.parts[-2] if len(item.path.parts) >= 2 else ""
        marker = domain_markers.get(domain)
        if marker:
            item.add_marker(getattr(pytest.mark, marker))
        if "live_models" in item.nodeid:
            item.add_marker(pytest.mark.slow)
        if item.nodeid.endswith(
            "test_startup_bootstrap.py::test_lifespan_bootstraps_schema_before_serving"
        ):
            item.add_marker(pytest.mark.integration)
            item.add_marker(pytest.mark.e2e)
            item.add_marker(pytest.mark.slow)
