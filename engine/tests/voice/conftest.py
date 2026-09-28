"""Voice uses real temporary SQLite, never the obsolete global Supabase fixture."""

import pytest


@pytest.fixture(autouse=True)
def cleanup_test_data():
    yield


@pytest.fixture
def fixture_db(tmp_path, monkeypatch):
    from tests.voice.m2_fixture import seed
    from zylch.storage import database

    key = seed(tmp_path, monkeypatch)
    yield key
    database.dispose_engine()
