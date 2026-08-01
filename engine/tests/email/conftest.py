"""Override the root conftest's Supabase-requiring autouse fixture.

These tests run against a temp SQLite file and a fake IMAP server; the
legacy `storage` fixture in tests/conftest.py would skip/error them.
"""

import pytest


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """No-op override of the parent autouse fixture."""
    yield
