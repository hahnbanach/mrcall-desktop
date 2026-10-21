"""Owned preparation flags only; never imports or invokes preparation.resume."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from m10_acceptance_budget_controls_files import Refused

SCHEMA = """CREATE TABLE preparation_state (
owner TEXT PRIMARY KEY, paused INTEGER NOT NULL DEFAULT 0,
run_id TEXT, running INTEGER NOT NULL DEFAULT 0, attempted INTEGER NOT NULL DEFAULT 0,
completed INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0,
item_limit INTEGER NOT NULL DEFAULT 25, stop_reason TEXT NOT NULL DEFAULT '',
pid INTEGER, started REAL)"""
COLUMNS = (
    "owner",
    "paused",
    "run_id",
    "running",
    "attempted",
    "completed",
    "failed",
    "item_limit",
    "stop_reason",
    "pid",
    "started",
)
STATS = ("attempted", "completed", "failed", "item_limit")
MARKER = "Paused for owned M10 acceptance; restoration never starts a run."


@contextmanager
def transaction(path: str):
    conn = sqlite3.connect(
        Path(path).as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=30
    )
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def snapshot(conn: sqlite3.Connection, owner: str) -> dict:
    exists = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='preparation_state'"
    ).fetchone()
    if exists is None:
        return dict(schema=None, row=None)
    columns = conn.execute("PRAGMA table_info(preparation_state)").fetchall()
    if set(row["name"] for row in columns) != set(COLUMNS):
        raise Refused("Unsupported preparation schema")
    row = conn.execute("SELECT * FROM preparation_state WHERE owner=?", (owner,)).fetchone()
    return dict(schema=exists[0], row=None if row is None else dict(row))


def pause(path: str, owner: str, before: dict) -> dict:
    with transaction(path) as conn:
        if snapshot(conn, owner) != before:
            raise Refused("Preparation changed before pause")
        if before["row"] and before["row"]["running"]:
            raise Refused("Preparation must be stopped and drained")
        if before["schema"] is None:
            conn.execute(SCHEMA)
        conn.execute("INSERT OR IGNORE INTO preparation_state(owner) VALUES(?)", (owner,))
        conn.execute(
            "UPDATE preparation_state SET paused=1,stop_reason=? WHERE owner=?", (MARKER, owner)
        )
        return snapshot(conn, owner)


def restore(path: str, owner: str, before: dict, owned: dict) -> None:
    with transaction(path) as conn:
        current = snapshot(conn, owner)
        if current["schema"] != owned["schema"] or current["row"] is None:
            raise Refused("Preparation schema/row changed during owned pause")
        old, now, expected = before["row"], current["row"], owned["row"]
        for key in COLUMNS:
            if key not in STATS and now[key] != expected[key]:
                raise Refused("Preparation owned flag/metadata drift; retain pause")
        if old is None:
            if now != expected:
                raise Refused("Cannot erase new preparation statistics; retain pause")
            if before["schema"] is None:
                if conn.execute("SELECT COUNT(*) FROM preparation_state").fetchone()[0] != 1:
                    raise Refused("Cannot remove preparation schema with unrelated rows")
                conn.execute("DROP TABLE preparation_state")
            else:
                conn.execute("DELETE FROM preparation_state WHERE owner=?", (owner,))
        else:
            conn.execute(
                "UPDATE preparation_state SET paused=?,stop_reason=? WHERE owner=?",
                (old["paused"], old["stop_reason"], owner),
            )


def encoded(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
