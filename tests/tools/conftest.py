"""Isolate tests/tools from the Supabase-requiring autouse fixture
in tests/conftest.py — these unit tests need no storage at all.
"""

import pytest


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """Override parent autouse fixture; no-op here."""
    yield
