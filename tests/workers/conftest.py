"""Override the root conftest autouse fixtures for worker tests."""

import pytest


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """No-op override — worker tests use mocks, not real storage."""
    yield
