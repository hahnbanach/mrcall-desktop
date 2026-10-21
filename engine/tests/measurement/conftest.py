"""Override the root conftest autouse fixtures for the measurement capture tests."""

import pytest


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """No-op override — the capture harnesses boot their own throwaway profile."""
    yield
