"""Override the root conftest autouse fixtures for storage tests."""

import pytest


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """No-op override — storage tests run against a temp SQLite file."""
    yield
