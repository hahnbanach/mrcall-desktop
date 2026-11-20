"""Source correspondence diagnostics preserve the held ownership result."""

import json
import sqlite3
import time
from pathlib import Path

import pytest

from mail_fixture import MailFixture, ROOT, REPLY
from zylch import observability, observability_producers
from zylch.services import task_assignment_mail as mail
from zylch.services import task_assignment_projection as projection
from zylch.services import task_assignment_sent_index as index
from zylch.services.task_assignment_types import AssignmentError
from zylch.storage import database as db
from zylch.storage.models import Email

MID = "<private-correspondence-sentinel@example.test>"


@pytest.fixture
def diagnostic(env, monkeypatch, tmp_path):
    index.clear()
    fixture = MailFixture(monkeypatch)
    fixture.messages['"Sent"'].clear()
    with db.get_session() as session:
        session.query(Email).filter(Email.id == fixture.reply_id).delete()
    store = observability.EventStore(tmp_path / "diagnostics", "alice")
    monkeypatch.setattr(observability_producers, "store", lambda: store)
    actor, _, current = projection.evidence.admission()
    known = mail.rows(actor, ROOT)
    yield fixture, store, actor, current, known
    index.clear()


def events(store):
    return [event for event in store.events(limit=100)["events"]
            if event.get("command", "").startswith("assignment.sent_correspondence.")]


def observe(diagnostic, *, stored=False):
    fixture, store, actor, current, known = diagnostic
    fixture.add(MID, "alice@example.test", "customer@example.test",
                folder='"Sent"', reply=ROOT, store=stored)
    result = index.candidates(actor, current, known, ROOT, deadline=time.monotonic() + 5)
    return result, events(store)


@pytest.mark.parametrize("stored,command,count", [
    (False, "archive_absent", 0),
    (True, "archive_present_unscoped", 1),
])
def test_current_archive_distinguished_without_changing_unknown(diagnostic, stored, command, count):
    result, records = observe(diagnostic, stored=stored)
    assert result == [{"complete": False, "judgement": "UNKNOWN",
                       "reason": "SENT_REPLY_NOT_SYNCED", "source": None}]
    assert len(records) == 1
    record = records[0]
    assert record["command"] == "assignment.sent_correspondence." + command
    assert record["count"] == 0 and record["pending_count"] == count and record["available"]
    assert record["error_file"] == "services/task_assignment_sent_index.py"
    assert all(len(record[name]) == 64 for name in ("root_id", "provider_id", "request_revision"))
    raw = json.dumps(records)
    assert MID not in raw and ROOT not in raw and "alice@example.test" not in raw


def test_existing_unique_source_retains_result(diagnostic):
    fixture, store, actor, current, _ = diagnostic
    source = fixture.add(MID, "alice@example.test", "customer@example.test",
                         folder='"Sent"', reply=ROOT)
    result = index.candidates(actor, current, mail.rows(actor, ROOT), ROOT,
                              deadline=time.monotonic() + 5)
    assert result == [{"source_id": source}]
    assert events(store)[0]["command"] == "assignment.sent_correspondence.matched"
    assert events(store)[0]["count"] == 1


def test_duplicate_known_is_logged_before_original_rejection(diagnostic):
    fixture, store, actor, current, known = diagnostic
    fixture.add(MID, "alice@example.test", "customer@example.test",
                folder='"Sent"', reply=ROOT)
    scoped = mail.rows(actor, ROOT)
    duplicate = next(row for row in scoped if row["message_id_header"] == MID)
    scoped.append({**duplicate, "id": "second-id"})
    with pytest.raises(AssignmentError, match="Ambiguous scoped RFC identity"):
        index.candidates(actor, current, scoped, ROOT, deadline=time.monotonic() + 5)
    assert events(store)[0]["command"] == "assignment.sent_correspondence.scoped_multiple"
    assert events(store)[0]["count"] == 2


def test_current_archive_duplicate_is_not_collapsed_to_one(diagnostic):
    fixture, store, actor, current, known = diagnostic
    fixture.add(MID, "alice@example.test", "customer@example.test",
                folder='"Sent"', reply=ROOT)
    duplicate = fixture.add("<other-gmail-identity@example.test>", "alice@example.test", "customer@example.test",
                            folder='"Sent"', reply=ROOT)
    fixture.messages['"Sent"'].pop(max(fixture.messages['"Sent"']))
    with db.get_session() as session:
        session.query(Email).filter(Email.id == duplicate).one().message_id_header = MID
    result = index.candidates(actor, current, known, ROOT, deadline=time.monotonic() + 5)
    assert result[0]["reason"] == "SENT_REPLY_NOT_SYNCED"
    record = events(store)[0]
    assert record["command"] == "assignment.sent_correspondence.archive_multiple_unscoped"
    assert record["count"] == 0 and record["pending_count"] == 2


def test_foreign_archive_owner_does_not_supply_match(diagnostic):
    fixture, store, actor, current, known = diagnostic
    source = fixture.add(MID, "alice@example.test", "customer@example.test",
                         folder='"Sent"', reply=ROOT)
    with db.get_session() as session:
        session.query(Email).filter(Email.id == source).one().owner_id = "bob@example.test"
    result = index.candidates(actor, current, known, ROOT, deadline=time.monotonic() + 5)
    assert result[0]["reason"] == "SENT_REPLY_NOT_SYNCED"
    assert events(store)[0]["command"] == "assignment.sent_correspondence.archive_absent"


def test_foreign_log_owner_is_refused_before_archive_read(diagnostic, monkeypatch):
    fixture, store, actor, current, known = diagnostic
    store.owner_uid = "bob"
    monkeypatch.setattr(index, "_archive_matches", lambda *args: pytest.fail("foreign log owner read"))
    result, records = observe(diagnostic)
    assert result[0]["reason"] == "SENT_REPLY_NOT_SYNCED" and records == []


def test_unavailable_logging_preserves_business_unknown(diagnostic, monkeypatch):
    monkeypatch.setattr(observability_producers, "observe",
                        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("private-sink-sentinel")))
    result, records = observe(diagnostic)
    assert result[0]["reason"] == "SENT_REPLY_NOT_SYNCED" and records == []


def test_expired_archive_observation_is_explicitly_unknown(diagnostic):
    from types import SimpleNamespace
    fixture, store, actor, _, known = diagnostic
    index._correspondence(actor, SimpleNamespace(id=fixture.box), ROOT, known, MID, 0,
                          time.monotonic() - 1, '"Sent"', SimpleNamespace(uidvalidity=11))
    record = events(store)[0]
    assert record["command"] == "assignment.sent_correspondence.archive_unknown"
    assert record["available"] is False and "pending_count" not in record


def test_wal_read_does_not_expose_uncommitted_row_or_change_shared_timeout(diagnostic):
    from types import SimpleNamespace
    fixture, _, actor, _, _ = diagnostic
    path = db.get_engine().url.database
    with db.get_engine().connect() as conn:
        before = conn.exec_driver_sql("PRAGMA busy_timeout").scalar_one()
    writer = sqlite3.connect(path)
    try:
        assert writer.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE emails SET message_id_header=? WHERE id=?", (MID, fixture.root_id))
        started = time.monotonic()
        assert index._archive_matches(actor, SimpleNamespace(id=fixture.box), MID, started + 1) == 0
        assert time.monotonic() - started < 0.2
    finally:
        writer.rollback()
        writer.close()
    with db.get_engine().connect() as conn:
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == before == 30000
        assert conn.exec_driver_sql("SELECT message_id_header FROM emails WHERE id=?",
                                    (fixture.root_id,)).scalar_one() == ROOT


def test_busy_archive_is_bounded_and_does_not_mutate_shared_timeout(diagnostic):
    from types import SimpleNamespace
    fixture, _, actor, _, _ = diagnostic
    engine = db.get_engine()
    path = engine.url.database
    engine.dispose()
    writer = sqlite3.connect(path)
    try:
        assert writer.execute("PRAGMA journal_mode=DELETE").fetchone()[0].lower() == "delete"
        writer.execute("BEGIN EXCLUSIVE")
        started = time.monotonic()
        assert index._archive_matches(actor, SimpleNamespace(id=fixture.box), MID, started + 1) is None
        assert time.monotonic() - started < 0.25
    finally:
        writer.rollback()
        writer.close()
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 30000


def test_engine_binding_race_is_unknown_and_read_connection_closes(diagnostic, monkeypatch):
    from types import SimpleNamespace
    fixture, _, actor, _, _ = diagnostic
    engine = db.get_engine()
    native = sqlite3.connect
    opened = []
    def changed(*args, **kwargs):
        connection = native(*args, **kwargs)
        opened.append(connection)
        db._engine = None
        return connection
    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(index.sqlite3, "connect", changed)
            assert index._archive_matches(actor, SimpleNamespace(id=fixture.box), MID,
                                          time.monotonic() + 1) is None
    finally:
        db._engine = engine
    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].execute("SELECT 1")


def test_file_replacement_race_is_unknown(diagnostic, monkeypatch):
    from types import SimpleNamespace
    fixture, _, actor, _, _ = diagnostic
    engine = db.get_engine()
    path = Path(engine.url.database)
    native = sqlite3.connect
    replacement = path.with_suffix(".replacement")
    temporary = path.with_suffix(".original")
    other = native(replacement)
    other.execute("CREATE TABLE emails (id, owner_id, mailbox_id, message_id_header)")
    other.commit()
    other.close()
    def replaced(*args, **kwargs):
        connection = native(*args, **kwargs)
        path.rename(temporary)
        replacement.rename(path)
        return connection
    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(index.sqlite3, "connect", replaced)
            assert index._archive_matches(actor, SimpleNamespace(id=fixture.box), MID,
                                          time.monotonic() + 1) is None
    finally:
        if temporary.exists():
            path.unlink()
            temporary.rename(path)


def test_no_database_creation_or_cross_backend_fallback(diagnostic, monkeypatch, tmp_path):
    from types import SimpleNamespace
    fixture, _, actor, _, _ = diagnostic
    engine = db.get_engine()
    absent = tmp_path / "must-not-be-created.db"
    for name, database in (("sqlite", str(absent)), ("sqlite", ":memory:"), ("other", str(absent))):
        with monkeypatch.context() as scoped:
            scoped.setattr(db, "_engine", SimpleNamespace(url=SimpleNamespace(
                get_backend_name=lambda: name, database=database)))
            assert index._archive_matches(actor, SimpleNamespace(id=fixture.box), MID,
                                          time.monotonic() + 1) is None
    assert db.get_engine() is engine and not absent.exists()


@pytest.mark.parametrize("case", ["absent", "stale", "unknown", "matched"])
def test_actual_authenticated_cli_collector_and_inbox(diagnostic, monkeypatch, tmp_path, case):
    import hashlib
    import os
    import ssl
    import subprocess
    import threading
    import uuid
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlsplit

    kernel = Path("/home/mal/hb/cs-kernel-release-20261025")
    monkeypatch.syspath_prepend(str(kernel))
    from cs import config, manifest
    from cs.monitor_config import Component, Endpoint, MonitorConfig

    fixture, store, actor, current, known = diagnostic
    fixture.add(MID, "alice@example.test", "customer@example.test",
                folder='"Sent"', reply=ROOT, store=case in {"stale", "matched"})
    if case == "matched":
        known = mail.rows(actor, ROOT)
    if case == "unknown":
        monkeypatch.setattr(index, "_archive_matches", lambda *args: None)
    result = index.candidates(actor, current, known, ROOT, deadline=time.monotonic() + 5)
    actual_records = events(store)
    assert len(actual_records) == 1
    certificate, key = tmp_path / "reader.crt", tmp_path / "reader.key"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-keyout", str(key), "-out", str(certificate), "-days", "1",
                    "-subj", "/CN=localhost", "-addext", "subjectAltName=IP:127.0.0.1"],
                   check=True, capture_output=True)
    class Reader(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            if self.headers.get("Authorization") != "Bearer local-fixture-only":
                self.send_response(401)
                self.end_headers()
                return
            query = parse_qs(urlsplit(self.path).query)
            page = store.events(cursor=query.get("cursor", [None])[0], limit=200)
            raw = json.dumps(page).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    server = HTTPServer(("127.0.0.1", 0), Reader)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(certificate, key)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SSL_CERT_FILE", str(certificate))
    monkeypatch.setenv("SENT_DIAGNOSTIC_READER_TOKEN", "local-fixture-only")
    address = f"https://127.0.0.1:{server.server_port}"
    settings = config.Settings(_env_file=(), slug="sourceprobe", engine_owner_uid="alice",
                               accounts="", db_path=":memory:",
                               observability=manifest.Observability(
                                   reader_url=address, reader_token_env="SENT_DIAGNOSTIC_READER_TOKEN"))
    cfg = MonitorConfig(mode="filesystem", clone_label="sourceprobe", monitor_id="b" * 32,
                        owner_uid="alice", state_dir=str(home / "monitor"),
                        expected_start_utc=int(time.time()), scan_seconds=600,
                        components=[Component(id="engine", kind="engine", reader=Endpoint(
                            url=address, token_env="SENT_DIAGNOSTIC_READER_TOKEN"))])
    cfgpath = home / "monitor.json"
    cfgpath.write_text(cfg.model_dump_json())
    cfgpath.chmod(0o600)
    try:
        assert settings.state_dir.is_relative_to(home)
        env = {**os.environ, "PYTHONPATH": str(kernel), "NO_PROXY": "127.0.0.1,localhost"}
        kernel_python = "/home/mal/hb/cs-kernel/.venv/bin/python"
        arguments = {"slug": "sourceprobe", "engine_owner_uid": "alice", "accounts": "", "db_path": ":memory:",
                     "observability": {"reader_url": address, "reader_token_env": "SENT_DIAGNOSTIC_READER_TOKEN"}}
        launcher = ("import json,sys; from cs import cli,config; "
                    "s=config.Settings(_env_file=(),**json.loads(sys.argv[1])); "
                    "config.load=lambda:s; "
                    "raise SystemExit(cli.main(['logs','events','--json','--limit','200']))")
        accessed = subprocess.run([kernel_python, "-c", launcher, json.dumps(arguments)],
                                  env=env, capture_output=True, text=True, timeout=10)
        assert accessed.returncode == 0, accessed.stderr
        logs = json.loads(accessed.stdout)
        assert logs["remote"]["events"][0]["command"] == actual_records[0]["command"]
        monitored = subprocess.run([kernel_python, "-m", "cs", "monitor", "once",
                                    "--config", str(cfgpath)], env=env,
                                   capture_output=True, text=True, timeout=15)
        assert monitored.returncode in (0, 1), monitored.stderr
        inbox = json.loads((home / "monitor/problems.json").read_text())
        commands = [problem["evidence"].get("command") for problem in inbox["problems"]]
        if case == "matched":
            assert actual_records[0]["command"] not in commands
        else:
            assert actual_records[0]["command"] in commands
        corpus = Path("/tmp/mrcall-ai-kit/20261025-release-alignment/v63/sent-correspondence")
        (corpus / "corpus").mkdir(exist_ok=True, mode=0o700)
        (corpus / "private-answer-key").mkdir(exist_ok=True, mode=0o700)
        identity = uuid.uuid4().hex
        wire = json.dumps({"logs": logs, "inbox": inbox})
        assert MID not in wire and ROOT not in wire and "local-fixture-only" not in wire
        (corpus / "corpus" / (identity + ".json")).write_text(wire)
        (corpus / "private-answer-key" / (identity + ".json")).write_text(json.dumps({
            "case": case, "command": actual_records[0]["command"], "business_result": result,
            "monitor_exit": monitored.returncode, "event_sha256": hashlib.sha256(
                json.dumps(actual_records[0], sort_keys=True).encode()).hexdigest(),
            "transport": "actual local HTTPS/Bearer fixture, real CLI and subprocess collector",
            "coverage_limit": "standalone fixture has no engine heartbeat; liveness finding is expected",
        }))
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)


def test_exact_mailbox_scope_and_read_only_connection(diagnostic, monkeypatch):
    from types import SimpleNamespace
    fixture, _, actor, _, _ = diagnostic
    fixture.add(MID, "alice@example.test", "customer@example.test",
                folder='"Sent"', reply=ROOT)
    native = sqlite3.connect
    calls = []
    def guarded(*args, **kwargs):
        assert args[0].endswith("?mode=ro") and kwargs["uri"] is True
        assert 0 < kwargs["timeout"] <= 0.05
        connection = native(*args, **kwargs)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("UPDATE emails SET body_plain='must-not-write'")
        calls.append(connection)
        return connection
    with monkeypatch.context() as scoped:
        scoped.setattr(index.sqlite3, "connect", guarded)
        assert index._archive_matches(actor, SimpleNamespace(id=fixture.box), MID,
                                      time.monotonic() + 1) == 1
        assert index._archive_matches(actor, SimpleNamespace(id="foreign-mailbox"), MID,
                                      time.monotonic() + 1) == 0
    assert len(calls) == 2


@pytest.mark.parametrize("race", ["file", "parent", "ancestor", "symlink"])
def test_restored_path_cannot_hide_opened_file_rebinding(diagnostic, monkeypatch, tmp_path, race):
    from types import SimpleNamespace
    fixture, _, actor, _, _ = diagnostic
    engine = db.get_engine()
    path = Path(engine.url.database)
    engine.dispose()
    native = sqlite3.connect
    preparation = native(path)
    preparation.execute("PRAGMA journal_mode=DELETE")
    preparation.close()
    original = path if race == "file" else path.parent if race in {"parent", "symlink"} else path.parent.parent
    held = original.with_name(original.name + "-held")
    replacement = original.with_name(original.name + "-replacement")
    if race == "file":
        other_database = replacement
    else:
        replacement.mkdir()
        other_database = replacement / path.relative_to(original)
        other_database.parent.mkdir(parents=True, exist_ok=True)
    other = native(other_database)
    other.execute("CREATE TABLE emails(id, owner_id, mailbox_id, message_id_header)")
    other.execute("INSERT INTO emails VALUES(?,?,?,?)", ("foreign-source", actor.mailbox, fixture.box, MID))
    other.commit()
    other.close()
    def raced(*args, **kwargs):
        original.rename(held)
        if race == "symlink":
            original.symlink_to(replacement, target_is_directory=True)
        else:
            replacement.rename(original)
        try:
            return native(*args, **kwargs)
        finally:
            if race == "symlink":
                original.unlink()
            else:
                original.rename(replacement)
            held.rename(original)
    with monkeypatch.context() as scoped:
        scoped.setattr(index.sqlite3, "connect", raced)
        assert index._archive_matches(actor, SimpleNamespace(id=fixture.box), MID,
                                      time.monotonic() + 1) is None
    actual = native(path)
    try:
        assert actual.execute("SELECT COUNT(*) FROM emails WHERE message_id_header=?", (MID,)).fetchone()[0] == 0
    finally:
        actual.close()


def test_namespace_overflow_is_unknown_before_sqlite_open(diagnostic, monkeypatch):
    import struct
    from types import SimpleNamespace
    fixture, _, actor, _, _ = diagnostic
    packet = struct.pack("=iIII", -1, 0x4000, 0, 0)
    with monkeypatch.context() as scoped:
        scoped.setattr(index.os, "read", lambda *args: packet)
        scoped.setattr(index.sqlite3, "connect", lambda *a, **k: pytest.fail("overflow reached SQLite"))
        assert index._archive_matches(actor, SimpleNamespace(id=fixture.box), MID,
                                      time.monotonic() + 1) is None


def test_watch_failure_is_unknown_and_closes_acquired_descriptors(diagnostic, monkeypatch):
    import os
    from types import SimpleNamespace
    fixture, _, actor, _, _ = diagnostic
    library = index.ctypes.CDLL(None, use_errno=True)
    native_open = os.open
    acquired = []
    def initialize(flags):
        descriptor = library.inotify_init1(flags)
        acquired.append(descriptor)
        return descriptor
    def denied(*args):
        return -1
    def tracked(*args, **kwargs):
        descriptor = native_open(*args, **kwargs)
        acquired.append(descriptor)
        return descriptor
    with monkeypatch.context() as scoped:
        scoped.setattr(index.ctypes, "CDLL", lambda *a, **k: SimpleNamespace(
            inotify_init1=initialize, inotify_add_watch=denied))
        scoped.setattr(index.os, "open", tracked)
        assert index._archive_matches(actor, SimpleNamespace(id=fixture.box), MID,
                                      time.monotonic() + 1) is None
    assert acquired
    for descriptor in acquired:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_namespace_setup_is_inside_total_deadline(diagnostic, monkeypatch):
    from types import SimpleNamespace
    fixture, _, actor, _, _ = diagnostic
    native = index.os.open
    started = time.monotonic()
    def slow(*args, **kwargs):
        descriptor = native(*args, **kwargs)
        time.sleep(0.055)
        return descriptor
    with monkeypatch.context() as scoped:
        scoped.setattr(index.os, "open", slow)
        scoped.setattr(index.sqlite3, "connect", lambda *a, **k: pytest.fail("expired setup reached SQLite"))
        assert index._archive_matches(actor, SimpleNamespace(id=fixture.box), MID,
                                      started + 1) is None
    assert time.monotonic() - started < 0.2


def test_existing_symlink_ancestor_cannot_be_followed(diagnostic, tmp_path, monkeypatch):
    from types import SimpleNamespace
    fixture, _, actor, _, _ = diagnostic
    engine = db.get_engine()
    path = Path(engine.url.database)
    alias = tmp_path / "alias"
    alias.symlink_to(path.parent, target_is_directory=True)
    with monkeypatch.context() as scoped:
        scoped.setattr(db, "_engine", SimpleNamespace(url=SimpleNamespace(
            get_backend_name=lambda: "sqlite", database=str(alias / path.name))))
        assert index._archive_matches(actor, SimpleNamespace(id=fixture.box), MID,
                                      time.monotonic() + 1) is None


@pytest.mark.parametrize("boundary", ["eagain", "final_return"])
def test_final_namespace_poll_expiry_is_unknown(diagnostic, monkeypatch, boundary):
    from types import SimpleNamespace
    fixture, _, actor, _, _ = diagnostic
    native_poll = index._archive_namespace_unchanged
    native_read = index.os.read
    polls = [0]
    def counted(*args):
        polls[0] += 1
        if boundary == "final_return" and polls[0] == 3:
            time.sleep(0.06)
            return True
        return native_poll(*args)
    def delayed(*args):
        if boundary == "eagain" and polls[0] == 3:
            time.sleep(0.06)
            raise BlockingIOError()
        return native_read(*args)
    with monkeypatch.context() as scoped:
        scoped.setattr(index, "_archive_namespace_unchanged", counted)
        scoped.setattr(index.os, "read", delayed)
        started = time.monotonic()
        assert index._archive_matches(actor, SimpleNamespace(id=fixture.box), MID,
                                      started + 1) is None
    assert polls[0] == 3 and time.monotonic() - started < 0.2


@pytest.mark.parametrize("kind", ["fifo", "socket"])
def test_nonregular_archive_cannot_block_open(diagnostic, monkeypatch, tmp_path, kind):
    import multiprocessing
    import os
    import socket
    from types import SimpleNamespace
    fixture, _, actor, _, _ = diagnostic
    path = tmp_path / "nonregular.db"
    listener = None
    if kind == "fifo":
        os.mkfifo(path)
    else:
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(path))
    context = multiprocessing.get_context("fork")
    queue = context.Queue()
    def read_archive():
        started = time.monotonic()
        value = index._archive_matches(actor, SimpleNamespace(id=fixture.box), MID, started + 1)
        queue.put((value, time.monotonic() - started))
    worker = context.Process(target=read_archive)
    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(db, "_engine", SimpleNamespace(url=SimpleNamespace(
                get_backend_name=lambda: "sqlite", database=str(path))))
            worker.start()
            worker.join(0.3)
            assert not worker.is_alive(), "nonregular archive blocked acquisition"
            assert worker.exitcode == 0
            value, elapsed = queue.get(timeout=0.2)
            assert value is None and elapsed < 0.2
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(1)
        queue.close()
        queue.join_thread()
        if listener is not None:
            listener.close()
