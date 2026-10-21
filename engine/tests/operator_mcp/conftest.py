import pytest


@pytest.fixture(autouse=True)
def cleanup_test_data():
    yield
