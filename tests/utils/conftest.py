"""Override the root conftest autouse fixtures for utils tests.

The root `tests/conftest.py` has a broken `cleanup_test_data(storage, ...)`
autouse fixture that references dead Supabase settings. Pure-function tests
here have no storage dependency, so we shadow it with a no-op.
"""

import pytest


@pytest.fixture(autouse=True)
def cleanup_test_data():
    yield
