# FILE: tests/conftest.py
# DESCRIPTION: Shared pytest fixtures and path setup.

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on sys.path so `import app...` works without an
# install step. This mirrors how main.py and web.py are launched.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
