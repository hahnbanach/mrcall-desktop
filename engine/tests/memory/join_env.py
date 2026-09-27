"""Reads and set-up shared by the company-memory join suites.

A join moves a profile between two real company stores under one
``MEMORY_DB_DIR``; these helpers read both files the way another process would
find them on disk (``sqlite3``, not the engine's sessions), the per-test
profile ``.env`` the join writes, and the fences the source store holds.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path
from typing import Any, List, Sequence

from zylch.memory.store import memory_db_path, open_memory_engine, prepare_store

from .mnemonic_env import COMPANY_B


def isolate(monkeypatch) -> None:
    """Register the join's ``.env`` settings so the live environment is restored after the test.

    ``settings_io.update_env`` writes them into ``os.environ`` as well as the file.
    """
    monkeypatch.setenv("MEMORY_JOIN_TO", "")
    monkeypatch.setenv("MEMORY_JOIN_FROM", "")


def destination(key: str = COMPANY_B) -> None:
    """An existing company store for ``key``, as a colleague's mint leaves it."""
    engine = open_memory_engine(key, create=True)
    prepare_store(engine, key, created_by="mint")
    engine.dispose()


def env_path() -> Path:
    return Path(os.environ["ZYLCH_PROFILE_DIR"]) / ".env"


def env_bytes() -> bytes:
    return env_path().read_bytes()


def env_value(name: str) -> str:
    from zylch.services.settings_io import read_env

    return read_env().get(name, "")


def rows(key: str, sql: str, params: Sequence[Any] = ()) -> List[tuple]:
    conn = sqlite3.connect(memory_db_path(key))
    try:
        return conn.execute(sql, tuple(params)).fetchall()
    finally:
        conn.close()


def count(key: str, table: str) -> int:
    return rows(key, f"SELECT COUNT(*) FROM {table}")[0][0]


def phases(key: str) -> List[str]:
    """Every fence the store holds, oldest first, by phase."""
    return [r[0] for r in rows(key, "SELECT phase FROM memory_join_fences ORDER BY created_at, id")]


def receipts(key: str = COMPANY_B) -> List[str]:
    return [r[0] for r in rows(key, "SELECT event_id FROM memory_operations WHERE event_id LIKE 'join-%'")]


def blob_ids(key: str) -> set:
    return {r[0] for r in rows(key, "SELECT id FROM blobs")}


def store_digest(key: str) -> str:
    """Every memory row of the store and its mutation sequence — the fences left out.

    What "nothing was written into the source" compares: a fence's own phase
    moves are the join's bookkeeping, everything else must stay byte for byte.
    """
    digest = hashlib.sha256()
    for table in (
        "blobs",
        "blob_versions",
        "blob_sentences",
        "email_blobs",
        "calendar_blobs",
        "whatsapp_blobs",
        "person_identifiers",
        "blob_aliases",
        "fact_history",
        "memory_operations",
        "memory_meta",
    ):
        for row in rows(key, f"SELECT * FROM {table} ORDER BY 1"):
            digest.update(repr(row).encode("utf-8"))
    return digest.hexdigest()


def file_bytes(key: str) -> bytes:
    """The store's database file and its write-ahead log, as the disk holds them."""
    path = Path(memory_db_path(key))
    wal = path.with_name(path.name + "-wal")
    return path.read_bytes() + (wal.read_bytes() if wal.exists() else b"")
