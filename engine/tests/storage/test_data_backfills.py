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
