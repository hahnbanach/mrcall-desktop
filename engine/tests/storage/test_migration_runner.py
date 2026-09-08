"""M0 — the single-owner, idempotent migration runner (brief C9).

What is proven here, and why each is a real check and not a gesture:

- A versioned step runs exactly once across boots and is recorded; forgetting
  it re-runs it (forward -> reverse -> forward converges).
- A destructive step backs the file up first, and the backup actually
  restores: "last resort" is a tested path.
- **Two real processes** racing on one file: exactly one applies the step,
  and the loser does not return — cannot serve — until the winner's step
  has finished. Threads would share the process's flock and prove nothing.
- Two real processes booting `init_db()` on a fresh file both exit 0.
- The bounded wait really is bounded.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time

import pytest
from sqlalchemy import text

from zylch.storage import database as dbm
from zylch.storage.migrations import (
    MigrationLockTimeout,
    MigrationStep,
    applied_step_ids,
    backup_sqlite,
    db_file_lock,
    pending_step_ids,
    restore_sqlite,
    run_migrations,
    unrecord_step,
)


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "zylch.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(path))
    dbm.dispose_engine()
    yield str(path)
    dbm.dispose_engine()


def _count(engine, sql: str) -> int:
    with engine.begin() as conn:
        return conn.execute(text(sql)).scalar_one()


def test_init_db_is_idempotent_and_records_schema_version(db_path):
    dbm.init_db()
    engine = dbm.get_engine()
    assert _count(engine, "SELECT COUNT(*) FROM sqlite_master WHERE name='schema_version'") == 1
    tables_before = _count(engine, "SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
    dbm.init_db()  # second boot: pure no-op
    assert _count(engine, "SELECT COUNT(*) FROM sqlite_master WHERE type='table'") == tables_before
    assert pending_step_ids(engine, dbm.PROFILE_STEPS) == []


def test_step_runs_once_then_forward_reverse_forward_converges(db_path):
    dbm.init_db()
    engine = dbm.get_engine()
    runs: list[int] = []

    def apply(conn):
        conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS m0_probe (n INTEGER)")
        conn.exec_driver_sql("INSERT INTO m0_probe VALUES (1)")
        runs.append(1)

    step = MigrationStep(id="9999_probe", apply=apply, description="probe")
    assert run_migrations(engine, db_path, steps=[step]) == ["9999_probe"]
    assert run_migrations(engine, db_path, steps=[step]) == []
    assert len(runs) == 1 and applied_step_ids(engine) >= {"9999_probe"}

    # Reverse half: un-record. Forward re-runs and must tolerate its own
    # earlier effects (idempotence over a partially-reverted DB).
    unrecord_step(engine, "9999_probe")
    assert pending_step_ids(engine, [step]) == ["9999_probe"]
    assert run_migrations(engine, db_path, steps=[step]) == ["9999_probe"]
    assert len(runs) == 2
    assert _count(engine, "SELECT COUNT(*) FROM m0_probe") == 2


def test_destructive_step_backs_up_first_and_the_backup_restores(db_path):
    dbm.init_db()
    engine = dbm.get_engine()
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE precious (v TEXT)")
        conn.exec_driver_sql("INSERT INTO precious VALUES ('keep me')")

    def wipe(conn):
        conn.exec_driver_sql("DELETE FROM precious")

    # init_db already applied the (destructive) 0001_company_key step, so a
    # backup for THAT exists; what this test owns is the delta.
    backups_dir = os.path.join(os.path.dirname(db_path), "backups")
    before = set(os.listdir(backups_dir)) if os.path.isdir(backups_dir) else set()

    step = MigrationStep(id="9998_wipe", apply=wipe, destructive=True)
    run_migrations(engine, db_path, steps=[step])
    assert _count(engine, "SELECT COUNT(*) FROM precious") == 0

    new_backups = sorted(set(os.listdir(backups_dir)) - before)
    assert len(new_backups) == 1 and "9998_wipe" in new_backups[0]

    # M0.5b — restore is exercised, not assumed.
    dbm.dispose_engine()
    restore_sqlite(os.path.join(backups_dir, new_backups[0]), db_path)
    engine = dbm.get_engine()
    assert _count(engine, "SELECT COUNT(*) FROM precious") == 1
    # The backup predates the step's record, so the step is pending again —
    # exactly what a real rollback wants.
    assert pending_step_ids(engine, [step]) == ["9998_wipe"]


def test_non_destructive_step_takes_no_backup(db_path):
    dbm.init_db()
    engine = dbm.get_engine()
    step = MigrationStep(
        id="9997_add", apply=lambda c: c.exec_driver_sql("CREATE TABLE IF NOT EXISTS t (x)")
    )
    backups_dir = os.path.join(os.path.dirname(db_path), "backups")
    before = set(os.listdir(backups_dir)) if os.path.isdir(backups_dir) else set()
    run_migrations(engine, db_path, steps=[step])
    after = set(os.listdir(backups_dir)) if os.path.isdir(backups_dir) else set()
    assert after == before  # nothing new: a non-destructive step takes no backup


def test_backup_api_includes_wal_pages(db_path):
    """A raw file copy would miss rows still in the -wal; the backup API must not."""
    dbm.init_db()
    engine = dbm.get_engine()
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE walrows (v TEXT)")
        conn.exec_driver_sql("INSERT INTO walrows VALUES ('in wal')")
    # No checkpoint, no dispose: the row may live only in zylch.db-wal.
    bak = backup_sqlite(db_path, label="waltest")
    import sqlite3

    c = sqlite3.connect(bak)
    try:
        assert c.execute("SELECT COUNT(*) FROM walrows").fetchone()[0] == 1
    finally:
        c.close()


def test_lock_wait_is_bounded(db_path):
    with db_file_lock(db_path):
        t0 = time.monotonic()
        with pytest.raises(MigrationLockTimeout):
            with db_file_lock(db_path, timeout_s=0.3):
                pass
        assert 0.25 <= time.monotonic() - t0 < 3.0


# ---------------------------------------------------------------------------
# Two real processes. The scripts below run in the venv interpreter with the
# installed package; each writes a JSON line of what it observed.
# ---------------------------------------------------------------------------

_RACE_SCRIPT = textwrap.dedent("""
    import json, os, sys, time
    from sqlalchemy import create_engine
    from zylch.storage.migrations import MigrationStep, run_migrations

    db_path, marker_dir, hold_s = sys.argv[1], sys.argv[2], float(sys.argv[3])
    engine = create_engine(f"sqlite:///{db_path}")
    applied_by_me = {"v": False}

    def apply(conn):
        applied_by_me["v"] = True
        conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS raced (pid INTEGER)")
        conn.exec_driver_sql(f"INSERT INTO raced VALUES ({os.getpid()})")
        time.sleep(hold_s)  # still inside the step: the file is being rewritten
        with open(os.path.join(marker_dir, "step_end"), "w") as f:
            f.write(repr(time.time()))

    step = MigrationStep(id="0001_raced", apply=apply)
    run_migrations(engine, db_path, steps=[step], lock_timeout_s=30)
    print(json.dumps({"pid": os.getpid(), "applied": applied_by_me["v"], "returned_at": time.time()}))
    """)

_BOOT_SCRIPT = textwrap.dedent("""
    import json, os, sys
    os.environ["ZYLCH_DB_PATH"] = sys.argv[1]
    from zylch.storage import database as dbm
    dbm.init_db()
    from sqlalchemy import text
    with dbm.get_engine().begin() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")).scalar_one()
    print(json.dumps({"pid": os.getpid(), "tables": n}))
    """)


def _spawn(script: str, *args: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", script, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_two_processes_one_migrates_and_the_loser_waits_for_it(tmp_path):
    db_path = str(tmp_path / "raced.db")
    marker_dir = str(tmp_path)
    hold_s = "1.5"
    procs = [_spawn(_RACE_SCRIPT, db_path, marker_dir, hold_s) for _ in range(2)]
    outs = []
    for p in procs:
        out, err = p.communicate(timeout=60)
        assert p.returncode == 0, err
        outs.append(json.loads(out.strip().splitlines()[-1]))

    winners = [o for o in outs if o["applied"]]
    losers = [o for o in outs if not o["applied"]]
    assert len(winners) == 1 and len(losers) == 1, outs

    with open(os.path.join(marker_dir, "step_end")) as f:
        step_end = float(f.read())
    # The loser could not return before the winner's step finished: it
    # blocked on the lock instead of skipping and serving early.
    assert losers[0]["returned_at"] >= step_end, (losers, step_end)

    import sqlite3

    c = sqlite3.connect(db_path)
    try:
        assert c.execute("SELECT COUNT(*) FROM raced").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 1
    finally:
        c.close()


def test_two_processes_booting_init_db_on_a_fresh_file_both_succeed(tmp_path):
    db_path = str(tmp_path / "boot.db")
    procs = [_spawn(_BOOT_SCRIPT, db_path) for _ in range(2)]
    results = []
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err
        results.append(json.loads(out.strip().splitlines()[-1]))
    assert results[0]["tables"] == results[1]["tables"] > 20
