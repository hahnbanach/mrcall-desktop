"""Regression test for `_apply_data_backfills` orchestration.

Ensures that the dispatcher invokes EVERY backfill on every init_db call,
regardless of whether the first one has work to do.

Background: until 2026-05-06, `_apply_data_backfills` had the
`sources.thread_id` backfill inlined in its body with an
`if not needs_lookup: return` early-out. That `return` short-circuited
the function before reaching the new Fase 3.1 (`email_blobs` index) and
Fase 3.2 (`task_items.channel`) backfills appended below. On any DB
where every task already had `sources.thread_id` populated (i.e. all
post-2026-04-17 installs), the two new backfills were silently skipped
forever — so the channel column stayed NULL on the gmail profile and the
Tasks-view channel filter / phone-task auto-close never had data to act on.

This test would have failed prior to the fix. Keep it green so the
pattern doesn't recur the next time someone appends a backfill.
"""

import os
import sqlite3
import uuid
from datetime import datetime

import pytest


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Build a tiny SQLite DB containing one task with channel NULL and
    `sources.thread_id` already populated (so the thread_id backfill has
    nothing to do — the exact shape that triggered the original bug).
    """
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))

    # Reset module-level singletons so the engine picks up the env var.
    from zylch.storage import database as dbm

    dbm.dispose_engine()

    # Bootstrap the schema (the first init_db call will create tables).
    dbm.init_db()

    # Inject one open task with a NULL channel and sources.thread_id set.
    # We bypass the ORM to keep the test independent of `Storage`.
    conn = sqlite3.connect(str(db_path))
    try:
        task_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO task_items "
            "(id, owner_id, event_type, event_id, contact_email, "
            "action_required, urgency, sources, created_at, channel) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (
                task_id,
                "owner@example.com",
                "email",
                "evt-1",
                "notification@transactional.mrcall.ai",
                1,
                "low",
                '{"emails": ["e1"], "thread_id": "t1"}',  # already populated
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # Force the next init_db to re-run backfills (engine cached the singleton).
    dbm.dispose_engine()
    yield db_path, task_id
    dbm.dispose_engine()


def test_init_db_invokes_channel_backfill_when_thread_id_backfill_is_noop(fresh_db):
    """Reproduces the 2026-05-06 regression: a fresh init_db on a DB
    where the thread_id backfill has nothing to do MUST still stamp the
    channel column on legacy NULL-channel tasks."""
    db_path, task_id = fresh_db

    from zylch.storage.database import init_db

    init_db()

    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT channel FROM task_items WHERE id = ?", (task_id,)
        ).fetchone()
    finally:
        conn.close()

    assert row is not None, "task row went missing"
    assert row[0] == "phone", (
        f"expected channel='phone' for notification@transactional.mrcall.ai "
        f"task, got {row[0]!r}. The dispatcher likely returned early before "
        "calling _backfill_task_channels."
    )


def test_apply_data_backfills_calls_every_step(monkeypatch, tmp_path):
    """Pure-orchestration check: even if every individual backfill is a
    no-op, _apply_data_backfills must invoke the full chain. Catches the
    'append a tail-call after an early return' class of bug at the
    dispatcher level instead of waiting for it to surface as a missing
    column value."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))

    from zylch.storage import database as dbm

    dbm.dispose_engine()
    dbm.init_db()  # create empty schema
    dbm.dispose_engine()

    called: list[str] = []
    monkeypatch.setattr(
        dbm, "_backfill_task_thread_id", lambda: called.append("thread_id")
    )
    monkeypatch.setattr(
        dbm, "_backfill_email_blobs_index", lambda: called.append("email_blobs")
    )
    monkeypatch.setattr(
        dbm, "_backfill_task_channels", lambda: called.append("channel")
    )

    dbm._apply_data_backfills()

    assert called == ["thread_id", "email_blobs", "channel"], (
        f"dispatcher skipped a backfill: called sequence was {called!r}. "
        "Every backfill must run on every init_db, regardless of whether "
        "earlier ones found work."
    )
