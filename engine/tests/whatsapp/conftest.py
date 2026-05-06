"""Local conftest for whatsapp tests.

Overrides the parent ``engine/tests/conftest.py`` autouse fixture
``cleanup_test_data`` (and the ``storage`` fixture it depends on) so
these tests run without a Supabase connection. They use a fresh
SQLite file per test via ``ZYLCH_DB_PATH``.
"""

import pytest


@pytest.fixture
def storage():  # override parent fixture; parent's pytest.skip would skip us
    return None


@pytest.fixture(autouse=True)
def cleanup_test_data():  # override parent autouse so it does not pull `storage`
    yield
