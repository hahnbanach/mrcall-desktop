"""Real SQLite reservation, process death and migration checks without provider effects."""

import json
import subprocess
import sys
import time

import pytest
from sqlalchemy import create_engine, inspect, text

from zylch.storage import database as db
from zylch.storage.draft_operation_models import STEP
from zylch.storage.draft_operations import DraftOperations, OperationConflict
from zylch.storage.migrations import applied_step_ids, run_migrations


@pytest.fixture
def journal(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'journal.db'}")
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
    run_migrations(engine, str(tmp_path / "journal.db"), steps=[STEP])
    yield DraftOperations(engine)
    engine.dispose()


def request(**changes):
    return (
        dict(
            owner_uid="owner-1",
            operation_id="op-1",
            canonical_root="<root@example.test>",
            operation_type="publish",
            draft_id="draft-1",
            expected_snapshot="snapshot-1",
            binding={"source_id": "source-1", "recipients": ["recipient@example.test"]},
            output_mime_digest="mime-digest-1",
        )
        | changes
    )


def inventory():
    return {"complete": True, "folder": "Drafts", "uidvalidity": "7", "digest": "inventory-1"}


def prepared(journal):
    reserved = journal.reserve(**request())
    journal.advance(
        "owner-1",
        "op-1",
        executor_token=reserved.executor_token,
        expected_version=0,
        stage="inventoried",
        evidence=inventory(),
    )
    return reserved.executor_token


def test_idempotent_readback_never_grants_execution(journal):
    first = journal.reserve(**request())
    assert first.acquired
    second = journal.reserve(**request())
    assert not second.acquired
    assert second.operation == first.operation == journal.read("owner-1", "op-1")
    assert "executor_token" not in second.operation
    with pytest.raises(OperationConflict, match="executor_changed"):
        journal.advance(
            "owner-1",
            "op-1",
            executor_token="",
            expected_version=0,
            stage="inventoried",
            evidence=inventory(),
        )


@pytest.mark.parametrize(
    "changed",
    [
        {"draft_id": "draft-2"},
        {"expected_snapshot": "changed"},
        {"canonical_root": "<other@example.test>"},
        {"operation_type": "retire_sent_mirror"},
        {"binding": {"source_id": "foreign"}},
        {"output_mime_digest": "changed"},
    ],
)
def test_operation_id_cannot_be_rebound(journal, changed):
    journal.reserve(**request())
    with pytest.raises(OperationConflict, match="binding_changed"):
        journal.reserve(**request(**changed))


def test_owner_isolation_and_root_exclusion(journal):
    journal.reserve(**request())
    held = journal.reserve(**request(operation_id="op-2", draft_id="draft-2"))
    assert not held.acquired and held.operation["operation_id"] == "op-1"
    assert journal.reserve(**request(owner_uid="owner-2")).acquired
    assert journal.read("foreign-owner", "op-1") is None
    assert journal.active("foreign-owner", "<root@example.test>") is None
    assert journal.reserve(
        **request(operation_id="op-3", canonical_root="<other@example.test>")
    ).acquired


def test_dispatch_marker_is_durable_and_nonexpiring(journal):
    token = prepared(journal)
    marked = journal.advance(
        "owner-1", "op-1", executor_token=token, expected_version=1, stage="dispatch_possible"
    )
    assert marked["active"] and marked["inventory"] == inventory()
    with pytest.raises(OperationConflict, match="invalid_operation_transition"):
        journal.reconcile(
            "owner-1",
            "op-1",
            expected_version=2,
            stage="not_dispatched",
            evidence={"complete_inventory_empty": True},
        )
    restarted = DraftOperations(create_engine(journal.engine.url))
    try:
        assert restarted.read("owner-1", "op-1") == marked
        assert not restarted.reserve(**request(operation_id="op-2")).acquired
    finally:
        restarted.engine.dispose()


def test_acknowledgment_and_completion_are_separate_commits(journal):
    token = prepared(journal)
    journal.advance(
        "owner-1", "op-1", executor_token=token, expected_version=1, stage="dispatch_possible"
    )
    ack = journal.advance(
        "owner-1",
        "op-1",
        executor_token=token,
        expected_version=2,
        stage="acknowledged",
        evidence={"append_uid": "8", "uidvalidity": "7"},
    )
    assert ack["active"] and ack["verification"] is None
    assert not journal.reserve(**request(operation_id="op-2")).acquired
    final = journal.reconcile(
        "owner-1",
        "op-1",
        expected_version=3,
        stage="completed",
        evidence={"exact_copy": True, "uid": "8", "inventory_digest": "after"},
    )
    assert not final["active"] and final["acknowledgment"] == ack["acknowledgment"]
    assert not journal.reserve(**request()).acquired
    assert journal.reserve(**request(operation_id="op-2")).acquired
    with pytest.raises(OperationConflict):
        journal.advance(
            "owner-1",
            "op-1",
            executor_token=token,
            expected_version=3,
            stage="completed",
            evidence={"stale": True},
        )


@pytest.mark.parametrize("stage", ["reserved", "inventoried"])
def test_proven_predispatch_cancellation_fences_live_worker(journal, stage):
    reserved = journal.reserve(**request())
    version = 0
    if stage == "inventoried":
        journal.advance(
            "owner-1",
            "op-1",
            executor_token=reserved.executor_token,
            expected_version=0,
            stage=stage,
            evidence=inventory(),
        )
        version = 1
    journal.reconcile(
        "owner-1",
        "op-1",
        expected_version=version,
        stage="not_dispatched",
        evidence={"cancel_before_dispatch": True},
    )
    with pytest.raises(OperationConflict):
        journal.advance(
            "owner-1",
            "op-1",
            executor_token=reserved.executor_token,
            expected_version=version,
            stage="dispatch_possible",
        )
    assert journal.reserve(**request(operation_id="op-2")).acquired


def test_complete_existing_copy_can_finish_without_append(journal):
    token = prepared(journal)
    result = journal.advance(
        "owner-1",
        "op-1",
        executor_token=token,
        expected_version=1,
        stage="completed",
        evidence={"complete_exact_existing_uid": "8"},
    )
    assert not result["active"] and result["acknowledgment"] is None


_SCRIPT = r"""
import json, os, sys, time
from pathlib import Path
from sqlalchemy import create_engine
from zylch.storage.draft_operations import DraftOperations, OperationConflict
path, start, ready, mode, operation_id = sys.argv[1:]
store = DraftOperations(create_engine("sqlite:///" + path))
Path(ready).write_text("ready")
while not Path(start).exists():
    time.sleep(.01)
r = store.reserve(owner_uid="owner-1", operation_id=operation_id,
 canonical_root="<root@example.test>", operation_type="publish", draft_id="draft-1",
 expected_snapshot="snapshot-1", binding={"source_id":"source-1", "recipients":["recipient@example.test"]},
 output_mime_digest="mime-digest-1")
if mode == "race":
    print(json.dumps({"acquired":r.acquired, "operation":r.operation}), flush=True)
else:
    if mode != "reserved":
        store.advance("owner-1", operation_id, executor_token=r.executor_token,
          expected_version=0, stage="inventoried", evidence={"complete":True,"digest":"inventory-1"})
    if mode in ("dispatch_possible", "acknowledged"):
        store.advance("owner-1", operation_id, executor_token=r.executor_token,
          expected_version=1, stage="dispatch_possible")
    if mode == "acknowledged":
        store.advance("owner-1", operation_id, executor_token=r.executor_token,
          expected_version=2, stage="acknowledged", evidence={"uid":"8"})
    print(json.dumps(store.read("owner-1", operation_id)), flush=True)
    while True:
        time.sleep(1)
"""


def spawn(journal, tmp_path, index, mode, operation_id):
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            _SCRIPT,
            str(journal.engine.url.database),
            str(tmp_path / "start"),
            str(tmp_path / f"ready{index}"),
            mode,
            operation_id,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def start_when_ready(tmp_path, processes):
    deadline = time.monotonic() + 15
    while not all((tmp_path / f"ready{i}").exists() for i in range(len(processes))):
        assert time.monotonic() < deadline, "subprocess startup timed out"
        assert all(p.poll() is None for p in processes)
        time.sleep(0.01)
    (tmp_path / "start").touch()


@pytest.mark.parametrize("same_id", [False, True])
def test_independent_processes_get_one_execution_owner(journal, tmp_path, same_id):
    processes = [
        spawn(journal, tmp_path, i, "race", "op-1" if same_id else f"op-{i}") for i in range(2)
    ]
    try:
        start_when_ready(tmp_path, processes)
        outputs = []
        for process in processes:
            out, err = process.communicate(timeout=20)
            assert process.returncode == 0, err
            outputs.append(json.loads(out))
        assert sum(o["acquired"] for o in outputs) == 1
        assert outputs[0]["operation"] == outputs[1]["operation"]
        with journal.engine.connect() as conn:
            assert (
                conn.execute(text("SELECT count(*) FROM draft_provider_operations")).scalar() == 1
            )
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


@pytest.mark.parametrize("stage", ["reserved", "inventoried", "dispatch_possible", "acknowledged"])
def test_sigkill_restart_retains_operation_and_never_regrants_execution(journal, tmp_path, stage):
    process = spawn(journal, tmp_path, 0, stage, "op-1")
    try:
        start_when_ready(tmp_path, [process])
        import select

        readable, _, _ = select.select([process.stdout], [], [], 15)
        assert readable, "durable stage marker timed out"
        before = json.loads(process.stdout.readline())
        process.kill()
        process.wait(timeout=5)
        restarted = DraftOperations(create_engine(journal.engine.url))
        try:
            assert restarted.read("owner-1", "op-1") == before
            assert before["stage"] == stage
            assert not restarted.reserve(**request()).acquired
            assert not restarted.reserve(**request(operation_id="op-2")).acquired
        finally:
            restarted.engine.dispose()
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


def test_additive_migration_preserves_rows_and_registers_only_in_profile(tmp_path, monkeypatch):
    path = tmp_path / "existing.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE drafts (id TEXT, status TEXT)")
        conn.exec_driver_sql("INSERT INTO drafts VALUES ('sent-old', 'sent')")
    assert run_migrations(engine, str(path), steps=[STEP]) == [STEP.id]
    assert run_migrations(engine, str(path), steps=[STEP]) == []
    assert STEP.id in applied_step_ids(engine)
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT * FROM drafts").all() == [("sent-old", "sent")]
    assert "draft_provider_operations" in inspect(engine).get_table_names()
    db._register_profile_steps()
    assert STEP in db.PROFILE_STEPS
    assert "draft_provider_operations" in {t.name for t in db.profile_tables()}
    assert "draft_provider_operations" not in {t.name for t in db.memory_tables()}
    engine.dispose()


_CAS_SCRIPT = r"""
import json, sys, time
from pathlib import Path
from sqlalchemy import create_engine
from zylch.storage.draft_operations import DraftOperations, OperationConflict
path, start, ready, token = sys.argv[1:]
store = DraftOperations(create_engine("sqlite:///" + path))
Path(ready).write_text("ready")
while not Path(start).exists():
    time.sleep(.01)
try:
    store.advance("owner-1", "op-1", executor_token=token,
                  expected_version=1, stage="dispatch_possible")
    print(json.dumps({"dispatch_granted": True}))
except OperationConflict:
    print(json.dumps({"dispatch_granted": False}))
"""


def test_same_executor_cannot_dispatch_twice_concurrently(journal, tmp_path):
    token = prepared(journal)
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                _CAS_SCRIPT,
                str(journal.engine.url.database),
                str(tmp_path / "start"),
                str(tmp_path / f"ready{i}"),
                token,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for i in range(2)
    ]
    try:
        start_when_ready(tmp_path, processes)
        results = []
        for process in processes:
            out, err = process.communicate(timeout=20)
            assert process.returncode == 0, err
            results.append(json.loads(out))
        assert sum(result["dispatch_granted"] for result in results) == 1
        assert journal.read("owner-1", "op-1")["stage"] == "dispatch_possible"
        with journal.engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA synchronous").scalar() == 2
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
