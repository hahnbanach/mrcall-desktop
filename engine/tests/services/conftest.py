"""Override the root conftest autouse fixtures for services tests."""

import pytest


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """No-op override — services tests use mocks, not real storage."""
    yield
