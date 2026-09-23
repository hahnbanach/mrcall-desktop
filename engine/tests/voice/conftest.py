"""Voice uses real temporary SQLite, never the obsolete global Supabase fixture."""

import pytest


@pytest.fixture(autouse=True)
def cleanup_test_data():
    yield
