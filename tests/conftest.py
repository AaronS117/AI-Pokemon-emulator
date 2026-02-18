"""
Shared fixtures for the test suite.
"""
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root is importable
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def tmp_db(tmp_path):
    """Provide a temporary database path for isolated DB tests."""
    return tmp_path / "test_shiny_log.db"


@pytest.fixture
def init_tmp_db(tmp_db):
    """Initialize a fresh database at a temp path and return the path."""
    from modules.database import init_db
    init_db(tmp_db)
    return tmp_db
