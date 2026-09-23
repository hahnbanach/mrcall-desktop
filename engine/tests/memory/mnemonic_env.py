"""Real profile and company databases for the milestone 3 commit tests.

Nothing here is a stand-in for storage. Each profile gets its own ``zylch.db``
booted through the real ``init_db``, each company its own store under a shared
``MEMORY_DB_DIR``, and switching profiles disposes the engines exactly as a
second process would find them on disk. Two owners sharing a key therefore
share a file, and a second company is a second file — which is the only way the
isolation assertions mean anything.

The embedder is the one stub: :class:`BagOfWordsEmbedder`, defined here so every
mnemonic suite imports the same one wherever it lives — ``tests/memory``,
``tests/tools`` and ``tests/services`` all reach the boundary and a second
definition would let them disagree about what similarity means.

A *restart* here is `reboot()`: engines disposed, module caches dropped, the
same files reopened. That is what the durable-allowance and crash assertions
lean on, and it is as close to a real restart as one process can get without
forking — which the two-process tests do separately.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import List, Union

import numpy as np

from zylch.storage import database as dbm

DIM = 384


class BagOfWordsEmbedder:
    """Stand-in for ``EmbeddingEngine``: same ``encode`` contract, no model.

    Maps text to a 384-dim vector by hashing tokens, so cosine similarity means
    "shares words" — enough to prove which HALF of hybrid search served a
    result, and deterministic, so no test depends on a downloaded model.
    """

    dim = DIM

    def _one(self, text: str) -> "np.ndarray":
        vec = np.zeros(DIM, dtype=np.float32)
        for tok in re.findall(r"[a-z0-9@.+]+", (text or "").lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            vec[h % DIM] += 1.0
        return vec

    def encode(self, text: Union[str, List[str]]) -> "np.ndarray":
        if isinstance(text, str):
            return self._one(text)
        return np.array([self._one(t) for t in text], dtype=np.float32)


COMPANY_A = "AAAAAAAAAAAAAAAAAAAAAA"
COMPANY_B = "BBBBBBBBBBBBBBBBBBBBBB"
OWNER_A = "uid-owner-a"
OWNER_B = "uid-owner-b"


def write_env(profile_dir: Path, owner: str, key: str, *, budget_usd: str = "5") -> None:
    """The profile's saved settings.

    ``LLM_DAILY_BUDGET_USD`` goes in the file, not the environment: the budget
    is read from the saved profile so a process cannot widen its own cap by
    exporting a variable, and a test that set the variable would simply not be
    testing the budget.
    """
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / ".env").write_text(
        "\n".join(
            [
                f"EMAIL_ADDRESS={owner}@company.test",
                f"OWNER_ID={owner}",
                f"MEMORY_KEY={key}",
                "MEMORY_KEY_SOURCE=mint",
                "ANTHROPIC_API_KEY=sk-ant-test",
                f"LLM_DAILY_BUDGET_USD={budget_usd}",
            ]
        )
        + "\n"
    )


def clear_process_state() -> None:
    """Drop the module-level caches a freshly started process would not have.

    The dispatch-allowance table and the permit registry are process globals,
    so without this one test file's event id would carry its spent allowance
    into another's — and a test that inherited a zero allowance would fail for
    a reason that has nothing to do with what it is checking.
    """
    from zylch.memory import commit_permit
    from zylch.memory.mnemonic import authorization

    authorization._ALLOWANCE.clear()
    authorization._ISSUED.clear()
    commit_permit._ISSUED.clear()
    commit_permit._SPENT.clear()


def boot(monkeypatch, root: Path, owner: str, key: str) -> str:
    """Bring up one profile against its real databases. Returns the owner id.

    Every previous engine is disposed first, so the profile that was open
    before is left exactly as another process would find it on disk.
    """
    profile_dir = root / f"profile-{owner}"
    write_env(profile_dir, owner, key)
    monkeypatch.setenv("MEMORY_DB_DIR", str(root / "memory"))
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(profile_dir))
    monkeypatch.setenv("ZYLCH_DB_PATH", str(profile_dir / "zylch.db"))
    monkeypatch.setenv("OWNER_ID", owner)
    monkeypatch.setenv("EMAIL_ADDRESS", f"{owner}@company.test")
    monkeypatch.setenv("MEMORY_KEY", key)
    monkeypatch.setenv("MEMORY_KEY_SOURCE", "mint")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "5")
    dbm.dispose_engine()
    clear_process_state()
    dbm.init_db()
    return owner


def reboot() -> None:
    """Close and reopen every engine: the in-process stand-in for a restart.

    The dispatch allowance cache and the permit registry live in module state,
    so they are cleared too — a restarted process has neither, and a test that
    left them behind would prove nothing about what survives on disk.
    """
    dbm.dispose_engine()
    clear_process_state()
    dbm.init_db()


def memory_db(root: Path, key: str) -> Path:
    return root / "memory" / f"{key}.db"


def blob_table_digest(db_path: Path) -> str:
    """A hash over every blob row's durable content — unchanged by a migration."""
    import hashlib
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, owner_id, company_key, namespace, content, embedding, events, "
            "created_at, updated_at FROM blobs ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    digest = hashlib.sha256()
    for row in rows:
        for value in row:
            digest.update(b"\x00" + (value if isinstance(value, bytes) else str(value).encode()))
    return digest.hexdigest()


def stub_embedder(monkeypatch, embedder) -> None:
    import zylch.memory as memory_pkg
    import zylch.memory.embeddings as emb_mod

    monkeypatch.setattr(memory_pkg, "EmbeddingEngine", lambda *a, **k: embedder)
    monkeypatch.setattr(emb_mod, "EmbeddingEngine", lambda *a, **k: embedder)


# ─── The provider seam ────────────────────────────────────────────────
# The real `LLMClient` and the real reservation ledger, with only the transport
# replaced. Shared by every mnemonic suite for the same reason the embedder is:
# a second definition would let two suites disagree about what "the real client
# with a fake wire" means, and the budget assertions depend on it being real.


def usage(input_tokens: int = 400, output_tokens: int = 120):
    from types import SimpleNamespace

    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)


def text_response(body: str, stop_reason: str = "end_turn"):
    from types import SimpleNamespace

    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=body, refusal=None)],
        model="claude-haiku-4-5",
        stop_reason=stop_reason,
        usage=usage(),
        refusal=None,
    )


def client(*responses: str):
    """The real ``LLMClient`` with only the provider transport replaced."""
    from unittest.mock import Mock

    from zylch.llm.client import LLMClient

    llm = LLMClient(transport="direct", api_key="fake", model="claude-haiku-4-5")
    llm._client.messages.create = Mock(side_effect=[text_response(r) for r in responses])
    return llm


def with_client(monkeypatch, llm):
    """Route every ``submit`` in this test through ``llm``, keeping the real path.

    Patches the argument, not the behaviour: the real decision round, the real
    admission check and the real commit all still run.

    Both names are patched. The tools import ``submit`` from the package, so the
    module attribute alone would leave every real caller on the real wire — and a
    test that reached the provider would fail on the fake key rather than on what
    it was checking.
    """
    from zylch.memory import mnemonic as pkg
    from zylch.memory.mnemonic import commit as commit_mod

    # Idempotent: a test that routes two turns through two clients must not end
    # up with the second wrapper delegating to the first, which would hand the
    # second turn the already-exhausted client and fail for no visible reason.
    real = getattr(commit_mod.submit, "_real_submit", commit_mod.submit)

    def routed(event, **kwargs):
        return real(event, **{**kwargs, "client": llm})

    routed._real_submit = real
    monkeypatch.setattr(commit_mod, "submit", routed)
    monkeypatch.setattr(pkg, "submit", routed)
    return llm


def owner_env(owner: str) -> dict:
    """The environment a second OS process needs to open the same files."""
    return {
        **os.environ,
        "OWNER_ID": owner,
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
    }
