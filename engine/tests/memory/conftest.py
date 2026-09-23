"""Fixtures for the company-scope tests: a real SQLite store, a fake embedder.

The embedder lives in :mod:`tests.memory.mnemonic_env` — one definition, shared
with the mnemonic suites under ``tests/tools`` and ``tests/services``.
"""

from __future__ import annotations

import pytest

from zylch.storage import database as dbm

from .mnemonic_env import DIM, BagOfWordsEmbedder  # noqa: F401


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """Override the root conftest's Supabase-era autouse fixture: these
    tests run against a temp SQLite file (same as tests/storage)."""
    yield


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def company_db(tmp_path, monkeypatch, embedder):
    """A fresh profile DB booted through the real ``init_db`` — which mints
    the company key and records the migration — plus a stubbed embedder
    everywhere the engine constructs one at call time."""
    db_path = tmp_path / "zylch.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))
    monkeypatch.delenv("MEMORY_KEY", raising=False)
    # Real-boot shape: the key is minted by the migration step, not preset.
    import zylch.memory as memory_pkg
    import zylch.memory.embeddings as emb_mod

    monkeypatch.setattr(memory_pkg, "EmbeddingEngine", lambda *a, **k: embedder)
    monkeypatch.setattr(emb_mod, "EmbeddingEngine", lambda *a, **k: embedder)
    dbm.dispose_engine()
    dbm.init_db()
    yield str(db_path)
    dbm.dispose_engine()
