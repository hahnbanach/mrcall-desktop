"""Fixtures for the company-scope tests: a real SQLite store, a fake embedder.

The embedder is the one piece of test infrastructure the plan names as
not existing yet. ``BagOfWordsEmbedder`` maps text to a 384-dim vector by
hashing tokens, so cosine similarity means "shares words" — enough to
prove which HALF of hybrid search served a result (a query sharing no
token with a blob's identifiers cannot be served by FTS), and
deterministic, so no test depends on a downloaded model.
"""

from __future__ import annotations

import hashlib
import re
from typing import List, Union

import numpy as np
import pytest

from zylch.storage import database as dbm

DIM = 384


class BagOfWordsEmbedder:
    """Stand-in for ``EmbeddingEngine``: same ``encode`` contract, no model."""

    dim = DIM

    def _one(self, text: str) -> np.ndarray:
        vec = np.zeros(DIM, dtype=np.float32)
        for tok in re.findall(r"[a-z0-9@.+]+", (text or "").lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            vec[h % DIM] += 1.0
        return vec

    def encode(self, text: Union[str, List[str]]) -> np.ndarray:
        if isinstance(text, str):
            return self._one(text)
        return np.array([self._one(t) for t in text], dtype=np.float32)


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
