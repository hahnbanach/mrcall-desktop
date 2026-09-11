"""Offline evaluator tests never initialize or clean application storage."""

import pytest


@pytest.fixture(autouse=True)
def cleanup_test_data():
    yield
