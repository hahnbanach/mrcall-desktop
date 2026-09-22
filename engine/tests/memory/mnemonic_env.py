"""Real profile and company databases for the milestone 3 commit tests.

Nothing here is a stand-in for storage. Each profile gets its own ``zylch.db``
booted through the real ``init_db``, each company its own store under a shared
``MEMORY_DB_DIR``, and switching profiles disposes the engines exactly as a
second process would find them on disk. Two owners sharing a key therefore
share a file, and a second company is a second file — which is the only way the
isolation assertions mean anything.

The embedder is the one stub: ``BagOfWordsEmbedder`` from ``conftest``, so a
test never downloads a model and cosine similarity means "shares words".

A *restart* here is `reboot()`: engines disposed, module caches dropped, the
same files reopened. That is what the durable-allowance and crash assertions
lean on, and it is as close to a real restart as one process can get without
forking — which the two-process tests do separately.
"""

from __future__ import annotations

import os
from pathlib import Path

from zylch.storage import database as dbm

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


def owner_env(owner: str) -> dict:
    """The environment a second OS process needs to open the same files."""
    return {
        **os.environ,
        "OWNER_ID": owner,
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
    }
