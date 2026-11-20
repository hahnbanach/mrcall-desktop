"""Sent recovery with real SQLite, disposable provider stores and CLI workers."""

from datetime import datetime
from email import policy
from email.parser import BytesParser
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest

from tests.rpc.test_exact_draft_publication import (
    setup as publication_setup,
    OWNER,
    UID,
    ID,
    ROOT,
    Mailbox,
    render,
    observation,
    db,
    Draft,
    Storage,
    DraftOperations,
    snapshot,
)
from zylch.services import exact_draft_retirement as recovery
from zylch.services import exact_draft_publication as publication

NEW_ID = "22345678-1234-1234-1234-123456789abc"


class RecoveryMailbox(Mailbox):
    def append(self, raw):
        with sqlite3.connect(self.path) as conn:
            number = conn.execute(
                "SELECT coalesce(max(id),0)+1 FROM (SELECT id FROM copies UNION ALL SELECT id FROM trash)"
            ).fetchone()[0]
            conn.execute("INSERT INTO copies(id,raw) VALUES (?,?)", (number, raw))
            conn.execute("INSERT INTO effects(kind) VALUES ('append')")
        return {"acknowledged": True}

    def inventory(self, special_use="Drafts", **query):
        mode = os.environ.get("RETIRE_KILL_STAGE")
        with sqlite3.connect(self.path) as conn:
            moved = conn.execute("SELECT count(*) FROM effects WHERE kind='move'").fetchone()[0]
        if mode == "before_dispatch" or (mode == "after_ack" and moved):
            Path(os.environ["RETIRE_MARKER"]).touch()
            time.sleep(60)
        table = {"Drafts": "copies", "Sent": "sent", "Trash": "trash"}[special_use]
        with sqlite3.connect(self.path) as conn:
            values = conn.execute(f"SELECT id,raw FROM {table} ORDER BY id").fetchall()
        rows = [observation(raw, str(uid), []) for uid, raw in values]
        if special_use == "Drafts":
            for row in rows:
                if str(row["message"].get("X-CS-Engine-Draft-ID")) == NEW_ID:
                    row["flags"] = ["\\Draft"]
        return rows, {
            "folder": special_use,
            "uidvalidity": "7",
            "complete": True,
            "digest": str([(r["uid"], r["raw_fingerprint"]) for r in rows]),
        }

    def move(self, target, trash):
        mode = os.environ.get("RETIRE_KILL_STAGE")
        if mode == "before_move":
            Path(os.environ["RETIRE_MARKER"]).touch()
            time.sleep(60)
        with sqlite3.connect(self.path) as conn:
            raw = conn.execute("SELECT raw FROM copies WHERE id=?", (target["uid"],)).fetchone()[0]
            cursor = conn.execute("INSERT INTO trash(raw) VALUES (?)", (raw,))
            conn.execute("DELETE FROM copies WHERE id=?", (target["uid"],))
            conn.execute("INSERT INTO effects(kind) VALUES ('move')")
            copied = str(cursor.lastrowid)
        if mode == "after_acceptance":
            Path(os.environ["RETIRE_MARKER"]).touch()
            time.sleep(60)
        if mode == "lost_ack":
            raise TimeoutError()
        return {"acknowledged": True, "copyuid": {"uidvalidity": "7", "uid": copied}}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    fixture = publication_setup.__wrapped__(tmp_path, monkeypatch)
    row, path = next(fixture)
    with db.get_session() as current:
        draft = current.query(Draft).filter_by(id=ID).one()
        draft.status = "sent"
        draft.sent_at = datetime(2026, 11, 5, 12)
        draft.sent_message_id = "<sent@example.test>"
    row = Storage.get_instance().get_draft(OWNER, ID)
    message = BytesParser(policy=policy.default).parsebytes(render(OWNER, UID, row, "old"))
    message["Date"] = "Thu, 05 Nov 2026 12:00:00 +0000"
    message["Message-ID"] = "<sent@example.test>"
    raw = message.as_bytes(policy=policy.SMTP).replace(b"In-Reply-To: ", b"In-Reply-To:\r\n\t")
    with sqlite3.connect(path / "provider.db") as conn:
        for table in ("sent", "trash"):
            conn.execute(f"CREATE TABLE {table}(id INTEGER PRIMARY KEY AUTOINCREMENT, raw BLOB)")
        conn.execute("INSERT INTO sent(raw) VALUES (?)", (raw,))
        conn.execute("INSERT INTO copies(raw) VALUES (?)", (raw,))
    monkeypatch.setattr(recovery, "RetirementMailbox", RecoveryMailbox)
    yield row, path
    try:
        next(fixture)
    except StopIteration:
        pass


def invoke(row, target=None, commit=False, operation="retire", factory=None):
    return recovery.retire(
        OWNER,
        UID,
        ID,
        snapshot(row),
        ROOT,
        operation,
        target or {"uid": "1", "uidvalidity": "7"},
        commit,
        lambda: (OWNER, UID),
        mailbox_factory=factory,
    )


def move_count(path):
    with sqlite3.connect(path / "provider.db") as conn:
        return conn.execute("SELECT count(*) FROM effects WHERE kind='move'").fetchone()[0]


def new_draft():
    with db.get_session() as current:
        current.add(
            Draft(
                id=NEW_ID,
                owner_id=OWNER,
                to_addresses=["customer@example.test"],
                subject="New reply",
                body="Current body.",
                body_format="plain",
                status="draft",
                thread_id=ROOT,
                in_reply_to=ROOT,
                references=[ROOT],
            )
        )
    return Storage.get_instance().get_draft(OWNER, NEW_ID)


def test_preview_commit_repeat_then_publish_preserves_sent(setup):
    row, path = setup
    preview = invoke(row)
    assert preview["ok"] and preview["dry_run"]
    assert DraftOperations().read(UID, "retire") is None
    assert invoke(row, preview["target"], True)["ok"]
    assert invoke(row, preview["target"], True)["ok"]
    fresh = new_draft()
    assert publication.publish(
        OWNER,
        UID,
        NEW_ID,
        snapshot(fresh),
        ROOT,
        "new",
        lambda: (OWNER, UID),
        mailbox_factory=RecoveryMailbox,
    )["ok"]
    assert invoke(row, preview["target"], True)["ok"]
    assert Storage.get_instance().get_draft(OWNER, ID) == row
    assert move_count(path) == 1
    with sqlite3.connect(path / "provider.db") as conn:
        assert conn.execute("SELECT count(*) FROM copies").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM sent").fetchone()[0] == 1


@pytest.mark.parametrize(
    "change",
    [
        "body",
        "recipient",
        "filename",
        "duplicate",
        "malformed",
        "duplicate-copy",
        "fingerprint",
        "validity",
    ],
)
def test_changed_or_ambiguous_copy_preserved(setup, change):
    row, path = setup
    target = invoke(row)["target"]
    if change == "validity":
        target["uidvalidity"] = "8"
    elif change == "fingerprint":
        target["raw_fingerprint"] = "a" * 64
    else:
        with sqlite3.connect(path / "provider.db") as conn:
            raw = conn.execute("SELECT raw FROM copies").fetchone()[0]
            message = BytesParser(policy=policy.default).parsebytes(raw)
            if change == "body":
                message.set_content("Edited")
            if change == "recipient":
                message.replace_header("To", "other@example.test")
            if change == "filename":
                message.set_param("name", "human.txt")
            if change == "duplicate":
                message._headers.append(("In-Reply-To", ROOT))
            if change == "malformed":
                message.replace_header("In-Reply-To", "<bad..id@example.test>")
            if change == "duplicate-copy":
                conn.execute("INSERT INTO copies(raw) VALUES (?)", (raw,))
            conn.execute("UPDATE copies SET raw=? WHERE id=1", (message.as_bytes(),))
    answer = invoke(row, target, True)
    assert not answer["ok"] and move_count(path) == 0
    assert Storage.get_instance().get_draft(OWNER, ID) == row


def test_lost_ack_reconciles_without_move_retry(setup, monkeypatch):
    row, path = setup
    target = invoke(row)["target"]
    monkeypatch.setenv("RETIRE_KILL_STAGE", "lost_ack")
    assert invoke(row, target, True)["effect_certainty"] == "unknown"
    assert DraftOperations().read(UID, "retire")["stage"] == "dispatch_possible"
    assert invoke(row, target, True)["ok"]
    assert move_count(path) == 1


SCRIPT = r"""
import asyncio,json,sys,os
sys.path.insert(0,sys.argv[1])
from tests.rpc.test_exact_draft_retirement import RecoveryMailbox,OWNER,UID
from zylch.services import exact_draft_retirement as recovery,exact_draft_publication as publication
from zylch.storage.storage import Storage
from zylch.rpc import exact_drafts
from cs import cli,config,rpc
store=object.__new__(Storage)
Storage.get_instance=lambda:store
recovery.RetirementMailbox=RecoveryMailbox
publication.ReviewMailbox=RecoveryMailbox
config.load=lambda:config.Settings(email_address=OWNER,engine_owner_uid=UID,engine_ws_url="wss://unused.example")
async def no_chat(*a,**kw):raise AssertionError("generation forbidden")
rpc.chat=no_chat
def call(settings,method,params,timeout=None):
 if method=="system.capabilities":return {"sent_mirror_recovery":1,"exact_draft_publication":1}
 return asyncio.run(exact_drafts.METHODS[method](params,None))
rpc.call_sync=call
raise SystemExit(cli.main(json.loads(sys.argv[2])))
"""


def cli_process(path, args, mode=None):
    env = dict(os.environ, HOME=str(path / "cli-home"), RETIRE_MARKER=str(path / "marker"))
    if mode:
        env["RETIRE_KILL_STAGE"] = mode
    return subprocess.Popen(
        [sys.executable, "-c", SCRIPT, os.environ["CS_KERNEL_SOURCE"], json.dumps(args)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def cli_args(preview=None):
    args = [
        "draft-retire",
        ID,
        "--sent-mirror",
        "--thread-id",
        ROOT,
        "--gmail-uid",
        "1",
        "--uidvalidity",
        "7",
        "--operation-id",
        "retire",
    ]
    if preview:
        args += [
            "--commit",
            "--gmail-folder",
            preview["target"]["folder"],
            "--gmail-fingerprint",
            preview["target"]["raw_fingerprint"],
            "--engine-snapshot",
            preview["expected_snapshot"],
        ]
    return args


@pytest.mark.skipif(not os.environ.get("CS_KERNEL_SOURCE"), reason="cross-repository CLI fixture")
@pytest.mark.parametrize(
    "mode", ["before_dispatch", "before_move", "after_acceptance", "after_ack"]
)
def test_killed_cli_retirement_blocks_or_reconciles_without_retry(setup, mode):
    row, path = setup
    preview = invoke(row)
    fresh = new_draft()
    process = cli_process(path, cli_args(preview), mode)
    try:
        deadline = time.monotonic() + 20
        while not (path / "marker").exists():
            assert time.monotonic() < deadline
            if process.poll() is not None:
                pytest.fail(str(process.communicate()))
            time.sleep(0.01)
        held = publication.publish(
            OWNER,
            UID,
            NEW_ID,
            snapshot(fresh),
            ROOT,
            "new",
            lambda: (OWNER, UID),
            mailbox_factory=RecoveryMailbox,
        )
        assert held["cause"] == "thread_operation_held"
        process.kill()
        process.wait(timeout=5)
        operation = DraftOperations().read(UID, "retire")
        assert (
            operation["stage"]
            == {
                "before_dispatch": "reserved",
                "before_move": "dispatch_possible",
                "after_acceptance": "dispatch_possible",
                "after_ack": "acknowledged",
            }[mode]
        )
        result = invoke(row, preview["target"], True)
        assert result["ok"] is (mode in {"after_acceptance", "after_ack"})
        assert move_count(path) == int(mode in {"after_acceptance", "after_ack"})
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


@pytest.mark.skipif(not os.environ.get("CS_KERNEL_SOURCE"), reason="cross-repository CLI fixture")
def test_real_cli_recovery_then_resume_no_generation(setup):
    row, path = setup

    def run(args):
        process = cli_process(path, args)
        out, err = process.communicate(timeout=20)
        assert process.returncode == 0, out + err
        return json.loads(out)

    preview = run(cli_args())
    assert run(cli_args(preview))["ok"]
    new_draft()
    assert run(["draft-reply", "--resume-draft", NEW_ID, "--thread-id", ROOT, "--json"])["ok"]
    assert run(cli_args(preview))["ok"]
    assert move_count(path) == 1
    assert Storage.get_instance().get_draft(OWNER, ID) == row


@pytest.mark.parametrize("kind", ["missing", "body", "duplicate-id", "malformed-id"])
def test_sent_proof_is_independent_and_strict(setup, kind):
    row, path = setup
    with sqlite3.connect(path / "provider.db") as conn:
        raw = conn.execute("SELECT raw FROM sent").fetchone()[0]
        message = BytesParser(policy=policy.default).parsebytes(raw)
        if kind == "body":
            message.set_content("Different sent content")
        if kind == "duplicate-id":
            message._headers.append(("Message-ID", "<sent@example.test>"))
        if kind == "malformed-id":
            message.replace_header("In-Reply-To", "<bad..id@example.test>")
        conn.execute("UPDATE sent SET raw=?", (message.as_bytes(),))
        if kind == "missing":
            conn.execute("DELETE FROM sent")
    assert not invoke(row)["ok"]
    assert move_count(path) == 0


def test_post_move_snapshot_change_stays_uncertain(setup):
    row, path = setup
    target = invoke(row)["target"]

    class Changed(RecoveryMailbox):
        def inventory(self, special_use="Drafts", **query):
            result = super().inventory(special_use, **query)
            if special_use == "Trash" and move_count(path):
                with db.get_session() as current:
                    current.query(Draft).filter_by(id=ID).one().body = "Changed"
            return result

    answer = invoke(row, target, True, factory=Changed)
    assert answer["cause"] == "draft_changed"
    assert answer["effect_certainty"] == "unknown"
    assert DraftOperations().read(UID, "retire")["active"]
    assert move_count(path) == 1


def test_provider_date_need_not_equal_engine_bookkeeping_time(setup):
    row, path = setup
    with db.get_session() as current:
        current.query(Draft).filter_by(id=ID).one().sent_at = datetime(2026, 11, 5, 12, 0, 1, 1234)
    row = Storage.get_instance().get_draft(OWNER, ID)
    preview = invoke(row)
    assert preview["ok"]
    assert invoke(row, preview["target"], True)["ok"]
    assert Storage.get_instance().get_draft(OWNER, ID) == row


def test_ordinary_sent_without_mirror_headers(setup):
    row, path = setup
    with sqlite3.connect(path / "provider.db") as conn:
        message = BytesParser(policy=policy.default).parsebytes(
            conn.execute("SELECT raw FROM sent").fetchone()[0]
        )
        for key in ("X-CS-Engine-Draft-ID", "X-CS-Engine-Owner-UID", "X-CS-Draft-Operation-ID"):
            del message[key]
        conn.execute("UPDATE sent SET raw=?", (message.as_bytes(),))
    preview = invoke(row)
    assert preview["ok"]
    assert invoke(row, preview["target"], True)["ok"]
    assert move_count(path) == 1
