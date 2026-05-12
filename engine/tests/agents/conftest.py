"""Override root conftest autouse fixtures for agents tests."""

import pytest


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """No-op override — these tests don't touch storage."""
    yield
