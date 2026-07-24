from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

# Ensure the project root is on sys.path so `import app...` works without an
# install step. This mirrors how main.py and web.py are launched.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── Multi-tenant isolation test fixtures ──────────────────────────────────
# Tests that exercise tenant-scoped database code inject a valid UUID string.


@pytest.fixture
def user_id() -> str:
    """Fresh UUID4 string simulating an authenticated tenant.

    Generated per-test so no two tests share a tenant identity — mirrors the
    isolation invariant the backend now enforces.
    """
    return str(uuid.uuid4())
