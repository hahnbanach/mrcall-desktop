"""Real path traversal, Ed25519 approval, privileged denial and join preflight."""

import io
import json
import os
import runpy
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select, text

from zylch.memory.mnemonic import fence
from zylch.services import task_assignment_store as store
from zylch.services import task_assignment_trust as trust
from zylch.services.task_assignment_join import refusal
from zylch.services.task_assignment_types import AssignmentError

PROTECTED_READ = trust.protected_read
THREAD = "<join@example.test>"


def test_unprivileged_actual_signing_process_refuses_without_reading_intent(env, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "scripts/server/assignment_approve.py",
            str(tmp_path / "not-present.json"),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert os.geteuid() != 0
    assert result.returncode == 1
    assert "Assignment approval refused" in result.stderr
    assert not result.stdout


def test_signer_command_exact_intent_and_real_verification_fixture(
    env, monkeypatch, tmp_path, capsys
):
    intent = store.preview("assign", THREAD, 0, "bob")
    path = tmp_path / "intent.json"
    path.write_text(json.dumps(intent))
    monkeypatch.setattr(sys, "argv", ["assignment_approve.py", str(path)])
    monkeypatch.setattr(sys, "stdin", io.StringIO("APPROVE\n"))
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    with pytest.raises(SystemExit) as result:
        runpy.run_path("scripts/server/assignment_approve.py", run_name="__main__")
    assert result.value.code == 0
    printed = capsys.readouterr()
    assert intent["thread_key"] in printed.err and "APPROVE" in printed.err
    grant = json.loads(printed.out)
    assert store.commit(intent, grant)["acknowledged"]


def test_signer_cancellation_does_not_sign(env, monkeypatch, tmp_path, capsys):
    intent = store.preview("assign", THREAD, 0, "bob")
    path = tmp_path / "intent.json"
    path.write_text(json.dumps(intent))
    monkeypatch.setattr(sys, "argv", ["assignment_approve.py", str(path)])
    monkeypatch.setattr(sys, "stdin", io.StringIO("no\n"))
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    with pytest.raises(SystemExit) as result:
        runpy.run_path("scripts/server/assignment_approve.py", run_name="__main__")
    assert result.value.code == 1 and not capsys.readouterr().out


def test_actual_tenant_owned_trust_refused(tmp_path):
    path = tmp_path / "untrusted.json"
    path.write_text("{}")
    with pytest.raises(AssignmentError, match="permissions"):
        PROTECTED_READ(path)


@pytest.mark.parametrize(
    "mode,private,accepted",
    [
        (0o100644, False, True),
        (0o100664, False, False),
        (0o100600, True, True),
        (0o100640, True, False),
        (0o040755, False, True),
        (0o040775, False, False),
    ],
)
def test_protected_stat_modes(mode, private, accepted):
    info = os.stat_result((mode, 1, 1, 1, 0, 0, 10, 0, 0, 0))
    if accepted:
        trust._check(info, directory=stat.S_ISDIR(mode), private=private)
    else:
        with pytest.raises(AssignmentError, match="permissions"):
            trust._check(info, directory=stat.S_ISDIR(mode), private=private)


def test_real_openat_symlinks_and_permissions_with_fixture_ownership(tmp_path, monkeypatch):
    directory = tmp_path / "protected"
    directory.mkdir(mode=0o755)
    path = directory / "trust.json"
    path.write_bytes(b"real-file")
    path.chmod(0o644)
    original = os.fstat

    def fixture_root_stat(fd):
        info = original(fd)
        target = Path(os.readlink(f"/proc/self/fd/{fd}"))
        mode = info.st_mode
        if directory not in target.parents and target != directory:
            mode = stat.S_IFMT(mode) | 0o755
        return os.stat_result(
            (
                mode,
                info.st_ino,
                info.st_dev,
                info.st_nlink,
                0,
                info.st_gid,
                info.st_size,
                info.st_atime,
                info.st_mtime,
                info.st_ctime,
            )
        )

    monkeypatch.setattr(os, "fstat", fixture_root_stat)
    assert PROTECTED_READ(path) == b"real-file"
    link = directory / "link"
    link.symlink_to(path)
    with pytest.raises(AssignmentError):
        PROTECTED_READ(link)
    alias = tmp_path / "aliased"
    alias.symlink_to(directory, target_is_directory=True)
    with pytest.raises(AssignmentError):
        PROTECTED_READ(alias / "trust.json")
    path.chmod(0o666)
    with pytest.raises(AssignmentError, match="permissions"):
        PROTECTED_READ(path)
    path.chmod(0o644)
    with pytest.raises(AssignmentError, match="permissions"):
        PROTECTED_READ(path, private=True)
    directory.chmod(0o777)
    with pytest.raises(AssignmentError, match="permissions"):
        PROTECTED_READ(path)


def test_join_refuses_before_drain_recovery_fence_env_or_destination_changes(env, monkeypatch):
    from zylch.memory import join, join_recover
    from zylch.memory.company_key import mint_key
    from zylch.memory.store import open_memory_engine, prepare_store

    destination = mint_key()
    other = open_memory_engine(destination, create=True)
    prepare_store(other, destination, created_by="fixture")
    intent = store.preview("assign", THREAD, 0, "bob")
    store.commit(intent, env.sign(intent))
    before_env = (Path(os.environ["ZYLCH_PROFILE_DIR"]) / ".env").read_bytes()
    calls = []
    monkeypatch.setattr(join, "_drain", lambda owner: calls.append("drain"))
    monkeypatch.setattr(join_recover, "recover_locked", lambda: calls.append("recover"))
    assert not join.join(destination, drain=True)["ok"]
    assert calls == []
    assert (Path(os.environ["ZYLCH_PROFILE_DIR"]) / ".env").read_bytes() == before_env
    with env.memory.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM memory_join_fences")).scalar() == 0
    with other.connect() as conn:
        assert conn.execute(select(store.T)).all() == []
    other.dispose()


def test_closed_history_and_incomplete_schema_block_join(env):
    for model in (store.E, store.R):
        assert refusal(env.memory) is None
    partial = create_engine("sqlite://")
    store.T.create(partial)
    assert "incomplete" in refusal(partial)
    partial.dispose()
    partial = create_engine("sqlite://")
    with partial.begin() as conn:
        for name in ("assigned_tasks", "assigned_task_events", "assigned_task_receipts"):
            conn.execute(text(f"CREATE TABLE {name}(id TEXT)"))
    assert "incomplete" in refusal(partial)
    partial.dispose()
    intent = store.preview("assign", THREAD, 0, "bob")
    store.commit(intent, env.sign(intent))
    with env.memory.begin() as conn:
        conn.execute(store.T.update().values(state="closed"))
    assert "history" in refusal(env.memory)


def test_fence_atomic_guard_and_assignment_denied_during_join(env):
    intent = store.preview("assign", THREAD, 0, "bob")
    grant = env.sign(intent)
    fence_id = fence.place(env.company, ["alice"], "destination")
    with pytest.raises(AssignmentError, match="join"):
        store.commit(intent, grant)
    assert fence.release(fence_id)
    store.commit(intent, grant)
    with env.memory.connect() as conn:
        before = conn.execute(text("SELECT COUNT(*) FROM memory_join_fences")).scalar()
    with pytest.raises(fence.CompanyFenced, match="assignment history"):
        fence.place(env.company, ["alice"], "destination")
    with env.memory.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM memory_join_fences")).scalar() == before


def test_first_company_statement_is_writer_lock(env):
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    intent, grant = store.preview("assign", THREAD, 0, "bob"), None
    grant = env.sign(intent)
    event.listen(env.memory, "before_cursor_execute", record)
    try:
        store.commit(intent, grant)
    finally:
        event.remove(env.memory, "before_cursor_execute", record)
    writer = next(
        index for index, value in enumerate(statements) if value.startswith("UPDATE project_space")
    )
    assert statements[writer - 1] == "BEGIN"


def test_concurrent_fence_and_assignment_admit_exactly_one_authority(env):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    intent = store.preview("assign", THREAD, 0, "bob")
    grant = env.sign(intent)
    barrier = Barrier(2)

    def assign():
        barrier.wait()
        try:
            store.commit(intent, grant)
            return "assigned"
        except AssignmentError:
            return "assignment-refused"

    def join():
        barrier.wait()
        try:
            fence.place(env.company, ["alice"], "destination")
            return "fenced"
        except fence.CompanyFenced:
            return "join-refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assigned, joined = pool.submit(assign), pool.submit(join)
        results = {assigned.result(), joined.result()}
    assert results in ({"assigned", "join-refused"}, {"assignment-refused", "fenced"})
