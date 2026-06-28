
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
# Phase 4 introduced mandatory user_id scoping on semantic_facts queries and
# threaded user_id through the Database facade. Tests that exercise those
# code paths must inject a valid UUID string to satisfy the HARD-FAIL guard
# in build_metadata_conditions and the new facade signatures.


@pytest.fixture
def user_id() -> str:
    """Fresh UUID4 string simulating an authenticated tenant.

    Generated per-test so no two tests share a tenant identity — mirrors the
    isolation invariant the backend now enforces.
    """
    return str(uuid.uuid4())
