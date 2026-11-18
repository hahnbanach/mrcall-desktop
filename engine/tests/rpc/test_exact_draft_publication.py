"""Exact publication through real SQLite reservations and disposable provider boundaries."""

import asyncio
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest

from zylch.storage import database as db
from zylch.storage.models import Draft
from zylch.storage.draft_operation_models import DraftOperation
from zylch.storage.draft_operations import DraftOperations
from zylch.storage.storage import Storage
from zylch.services import exact_draft_publication as service
from zylch.services.exact_draft_publication_mime import render, observation, identifier
from zylch.services.exact_draft_delivery import snapshot

OWNER = "owner@example.test"
UID = "owner-uid"
ID = "12345678-1234-1234-1234-123456789abc"
ROOT = "<root@example.test>"


class Mailbox:
    def __init__(self, owner):
        self.owner = owner
        self.path = os.environ["PUBLICATION_PROVIDER_DB"]

    def inventory(self):
        stage = os.environ.get("PUBLICATION_KILL_STAGE")
        self.reads = getattr(self, "reads", 0) + 1
        if stage == "before_dispatch" or (stage == "after_ack" and self.reads == 2):
            Path(os.environ["PUBLICATION_MARKER"]).touch()
            time.sleep(60)
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute("SELECT id,raw FROM copies ORDER BY id").fetchall()
        observed = [observation(raw, str(uid), ["\\Draft"]) for uid, raw in rows]
        return observed, {
            "complete": True,
            "folder": "Drafts",
            "uidvalidity": "7",
            "digest": str([(r["uid"], r["raw_fingerprint"]) for r in observed]),
        }

    def append(self, raw):
        marker = os.environ.get("PUBLICATION_KILL_STAGE")
        if marker == "before_append":
            Path(os.environ["PUBLICATION_MARKER"]).touch()
            time.sleep(60)
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO copies(raw) VALUES (?)", (raw,))
            conn.execute("INSERT INTO effects(kind) VALUES (?)", ("append",))
        if marker == "after_acceptance":
            Path(os.environ["PUBLICATION_MARKER"]).touch()
            time.sleep(60)
        if marker == "ack_lost":
            raise TimeoutError()
        return {"acknowledged": True}

    def close(self):
        pass


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from zylch.auth import clear_session

    clear_session()
    db.dispose_engine()
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "engine.db"))
    monkeypatch.setenv("EMAIL_ADDRESS", OWNER)
    monkeypatch.setenv("OWNER_ID", UID)
    monkeypatch.setenv("PUBLICATION_PROVIDER_DB", str(tmp_path / "provider.db"))
    with sqlite3.connect(tmp_path / "provider.db") as conn:
        conn.execute("CREATE TABLE copies(id INTEGER PRIMARY KEY, raw BLOB)")
        conn.execute("CREATE TABLE effects(kind TEXT)")
    Draft.__table__.create(db.get_engine())
    DraftOperation.__table__.create(db.get_engine())
    with db.get_session() as current:
        current.add(
            Draft(
                id=ID,
                owner_id=OWNER,
                to_addresses=["customer@example.test"],
                subject="Reply",
                body="Complete body.",
                body_format="plain",
                status="draft",
                thread_id=ROOT,
                in_reply_to=ROOT,
                references=[ROOT],
            )
        )
    store = object.__new__(Storage)
    monkeypatch.setattr(Storage, "get_instance", lambda: store)
    monkeypatch.setattr(service, "ReviewMailbox", Mailbox)
    yield store.get_draft(OWNER, ID), tmp_path
    clear_session()
    db.dispose_engine()


def invoke(row, operation="op-1", **changes):
    return service.publish(
        OWNER, UID, ID, snapshot(row), ROOT, operation, lambda: (OWNER, UID), **changes
    )


def effects(tmp_path):
    with sqlite3.connect(tmp_path / "provider.db") as conn:
        return conn.execute("SELECT count(*) FROM effects").fetchone()[0]


def test_publish_replay_and_complete_journal(setup):
    row, path = setup
    assert invoke(row)["ok"]
    assert invoke(row)["ok"]
    assert effects(path) == 1
    op = DraftOperations().read(UID, "op-1")
    assert op["stage"] == "completed" and not op["active"]
    assert op["inventory"] and op["acknowledgment"] and op["verification"]


def test_conflict_keeps_saved_id_and_blocking_handle(setup):
    row, path = setup
    other = dict(row, id="22345678-1234-1234-1234-123456789abc")
    Mailbox(OWNER).append(render(OWNER, UID, other, "old"))
    answer = invoke(row)
    assert answer["cause"] == "thread_copy_conflict"
    assert answer["draft_id"] == ID and answer["achieved_stages"] == ["engine-saved"]
    assert answer["provider_handles"][0]["uid"] == "1"
    assert effects(path) == 1


def test_edited_same_id_is_preserved(setup):
    row, path = setup
    Mailbox(OWNER).append(render(OWNER, UID, dict(row, body="Human edit"), "other"))
    assert invoke(row)["cause"] == "thread_copy_conflict"
    assert effects(path) == 1


def test_ack_loss_reconciles_without_second_append(setup, monkeypatch):
    row, path = setup
    monkeypatch.setenv("PUBLICATION_KILL_STAGE", "ack_lost")
    assert invoke(row)["effect_certainty"] == "unknown"
    assert DraftOperations().read(UID, "op-1")["stage"] == "dispatch_possible"
    assert invoke(row, operation="different-request")["ok"]
    assert effects(path) == 1


def test_snapshot_change_before_append_cannot_publish(setup):
    row, path = setup

    class Changed(Mailbox):
        def inventory(self):
            result = super().inventory()
            with db.get_session() as current:
                current.query(Draft).filter_by(id=ID).one().body = "Changed"
            return result

    result = invoke(row, mailbox_factory=Changed)
    assert result["cause"] == "draft_changed"
    assert effects(path) == 0


def test_incomplete_inventory_cannot_append(setup):
    row, path = setup

    class Unavailable(Mailbox):
        def inventory(self):
            from zylch.services.exact_draft_delivery import EvidenceRefusal

            raise EvidenceRefusal("incomplete_inventory")

    assert invoke(row, mailbox_factory=Unavailable)["cause"] == "incomplete_inventory"
    assert effects(path) == 0


def test_rpc_registered_and_readonly_no_mutation(setup):
    row, path = setup
    from zylch.rpc.dispatch import dispatch_raw
    from zylch.services.request_policy import policy_scope

    params = {
        "draft_id": ID,
        "thread_id": ROOT,
        "expected_snapshot": snapshot(row),
        "operation_id": "rpc-1",
    }
    with policy_scope("read_only"):
        answer = asyncio.run(
            dispatch_raw(
                json.dumps(
                    {"jsonrpc": "2.0", "id": 1, "method": "drafts.publish_review", "params": params}
                ),
                lambda *a: None,
            )
        )
    assert "error" in answer and effects(path) == 0
    assert DraftOperations().read(UID, "rpc-1") is None
    answer = asyncio.run(
        dispatch_raw(
            json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "drafts.publish_review", "params": params}
            ),
            lambda *a: None,
        )
    )
    assert answer["result"]["ok"], answer


@pytest.mark.parametrize(
    "value",
    [
        "<a@example.test> extra",
        "<a..b@example.test>",
        "<a,b@example.test>",
        "<a@example.test> <b@example.test>",
    ],
)
def test_malformed_ids_refused(value):
    from zylch.services.exact_draft_delivery import EvidenceRefusal

    with pytest.raises(EvidenceRefusal):
        identifier(value)


SCRIPT = r"""
import asyncio, json, os, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
from test_exact_draft_publication import Mailbox, OWNER, UID, ID, ROOT
from zylch.services import exact_draft_publication as service
from zylch.storage.storage import Storage
from zylch.rpc import exact_drafts
from cs import cli, config, rpc
store=object.__new__(Storage)
Storage.get_instance=lambda: store
service.ReviewMailbox=Mailbox
settings=config.Settings(email_address=OWNER,engine_owner_uid=UID,engine_ws_url="wss://unused.example")
config.load=lambda:settings
async def no_chat(*a,**kw):
    raise AssertionError("resume generated")
rpc.chat=no_chat
def call(settings,method,params,timeout=None):
    if method=="system.capabilities":return {"exact_draft_publication":1}
    if method=="drafts.inspect":return asyncio.run(exact_drafts.drafts_inspect(params,None))
    if method=="drafts.publish_review":return asyncio.run(exact_drafts.drafts_publish_review(params,None))
    raise AssertionError(method)
rpc.call_sync=call
Path(sys.argv[3]).touch()
while not Path(sys.argv[4]).exists():time.sleep(.01)
raise SystemExit(cli.main(["draft-reply","--resume-draft",ID,"--thread-id",ROOT,"--json"]))
"""


def spawn_cli(path, index, mode=None):
    kernel = Path(os.environ["CS_KERNEL_SOURCE"])
    env = dict(
        os.environ, HOME=str(path / f"home-{index}"), PUBLICATION_MARKER=str(path / "kill-marker")
    )
    if mode:
        env["PUBLICATION_KILL_STAGE"] = mode
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            SCRIPT,
            str(kernel),
            str(Path(__file__).parent),
            str(path / f"ready-{index}"),
            str(path / "start"),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def wait_path(path, processes):
    deadline = time.monotonic() + 20
    while not path.exists():
        assert time.monotonic() < deadline, str(path)
        for process in processes:
            if process.poll() is not None:
                out, err = process.communicate()
                pytest.fail(out + err)
        time.sleep(0.01)


@pytest.mark.skipif(
    not os.environ.get("CS_KERNEL_SOURCE"),
    reason="cross-repository CLI fixture requires CS_KERNEL_SOURCE",
)
def test_two_real_cli_processes_one_append_different_local_directories(setup):
    row, path = setup
    processes = [spawn_cli(path, i) for i in range(2)]
    try:
        for i in range(2):
            wait_path(path / f"ready-{i}", processes)
        (path / "start").touch()
        for process in processes:
            out, err = process.communicate(timeout=25)
            assert process.returncode in (0, 3), out + err
            answer = json.loads(out)
            assert answer["draft_id"] == ID
        assert effects(path) == 1
        assert invoke(row)["ok"]
        assert effects(path) == 1
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


@pytest.mark.parametrize(
    "mode", ["before_dispatch", "before_append", "after_acceptance", "after_ack"]
)
@pytest.mark.skipif(
    not os.environ.get("CS_KERNEL_SOURCE"),
    reason="cross-repository CLI fixture requires CS_KERNEL_SOURCE",
)
def test_killed_cli_effect_worker_reconciles_or_holds_without_retry(setup, mode):
    row, path = setup
    process = spawn_cli(path, 0, mode)
    try:
        wait_path(path / "ready-0", [process])
        (path / "start").touch()
        wait_path(path / "kill-marker", [process])
        process.kill()
        process.wait(timeout=5)
        answer = invoke(row)
        assert answer["ok"] is (mode in {"after_acceptance", "after_ack"})
        assert effects(path) == (1 if mode in {"after_acceptance", "after_ack"} else 0)
        if mode in {"before_append", "before_dispatch"}:
            assert answer["effect_certainty"] == "unknown"
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


def test_real_imap_adapter_complete_inventory_and_append(setup, monkeypatch):
    from types import SimpleNamespace
    from zylch.email import mailboxes
    from zylch.services.exact_draft_publication_imap import ReviewMailbox

    row, path = setup

    class Connection:
        untagged_responses = {"UIDVALIDITY": [b"7"]}

        def list(self):
            return "OK", [b'(\\Drafts) "/" "Drafts"']

        def select(self, folder, readonly=False):
            assert folder == '"Drafts"' and readonly
            return "OK", []

        def uid(self, command, *args):
            with sqlite3.connect(path / "provider.db") as conn:
                rows = conn.execute("SELECT id,raw FROM copies ORDER BY id").fetchall()
            if command == "SEARCH":
                return "OK", [b" ".join(str(uid).encode() for uid, raw in rows)]
            assert args[-1] == "(UID FLAGS RFC822.SIZE BODY.PEEK[])"
            raw = next(raw for uid, raw in rows if str(uid).encode() == args[0])
            return "OK", [
                (
                    b"1 (UID "
                    + args[0]
                    + b" FLAGS (\\Draft) RFC822.SIZE "
                    + str(len(raw)).encode()
                    + b")",
                    raw,
                )
            ]

        def append(self, folder, flags, date, raw):
            assert folder == '"Drafts"' and flags == "(\\Draft)"
            Mailbox(OWNER).append(raw)
            return "OK", []

    connection = Connection()
    client = SimpleNamespace(_ensure_connected=lambda: connection, disconnect=lambda: None)
    monkeypatch.setattr(mailboxes, "primary", lambda owner: SimpleNamespace(address=owner))
    monkeypatch.setattr(mailboxes, "build_imap_client", lambda mailbox: client)
    assert invoke(row, mailbox_factory=ReviewMailbox)["ok"]
    assert invoke(row, mailbox_factory=ReviewMailbox)["ok"]
    assert effects(path) == 1
    connection.untagged_responses = {"UIDVALIDITY": [b"8"]}
    assert not invoke(row, mailbox_factory=ReviewMailbox)["ok"]


@pytest.mark.parametrize("mode", ["attachment", "bcc", "extra-part", "duplicate-header", "body"])
def test_material_edits_are_never_adopted(setup, mode):
    from email import policy
    from email.parser import BytesParser

    row, path = setup
    message = BytesParser(policy=policy.default).parsebytes(render(OWNER, UID, row, "existing"))
    if mode == "attachment":
        message.add_attachment(b"new", maintype="application", subtype="pdf", filename="new.pdf")
    if mode == "bcc":
        message["Bcc"] = "hidden@example.test"
    if mode == "extra-part":
        message.add_alternative("Extra content", subtype="html")
    if mode == "duplicate-header":
        message._headers.append(("From", "foreign@example.test"))
    if mode == "body":
        message.set_content("Edited")
    Mailbox(OWNER).append(message.as_bytes())
    answer = invoke(row)
    assert not answer["ok"] and effects(path) == 1


@pytest.mark.parametrize(
    "body,expected", [("Plain text with stale format label.", True), ("<p>Rich text</p>", False)]
)
def test_stale_html_label_preserves_plain_bytes_and_rich_html_refuses(setup, body, expected):
    row, path = setup
    with db.get_session() as current:
        draft = current.query(Draft).filter_by(id=ID).one()
        draft.body_format = "html"
        draft.body = body
    row = Storage.get_instance().get_draft(OWNER, ID)
    assert invoke(row)["ok"] is expected
    assert effects(path) == int(expected)


@pytest.mark.parametrize(
    "mode",
    [
        "filename-param",
        "duplicate-content-type",
        "duplicate-transfer-encoding",
        "defective-content-type",
    ],
)
def test_ambiguous_mime_metadata_preserved(setup, mode):
    from email import policy
    from email.parser import BytesParser

    row, path = setup
    message = BytesParser(policy=policy.default).parsebytes(render(OWNER, UID, row, "existing"))
    if mode == "filename-param":
        message.set_param("name", "human-added.txt", header="Content-Type")
    if mode == "duplicate-content-type":
        message._headers.append(("Content-Type", "text/plain"))
    if mode == "duplicate-transfer-encoding":
        message._headers.append(("Content-Transfer-Encoding", "base64"))
    if mode == "defective-content-type":
        message.replace_header("Content-Type", 'text/plain; charset="unterminated')
    Mailbox(OWNER).append(message.as_bytes())
    answer = invoke(row)
    assert not answer["ok"]
    assert effects(path) == 1


@pytest.mark.parametrize("mode", ["after-append", "reuse", "reconcile"])
def test_final_completion_atomically_refuses_changed_full_row(setup, monkeypatch, mode):
    row, path = setup
    if mode == "reuse":
        Mailbox(OWNER).append(render(OWNER, UID, row, "old"))
    if mode == "reconcile":
        monkeypatch.setenv("PUBLICATION_KILL_STAGE", "ack_lost")
        assert not invoke(row)["ok"]
        monkeypatch.delenv("PUBLICATION_KILL_STAGE")

    class ChangedAfter(Mailbox):
        def inventory(self):
            result = super().inventory()
            if self.reads == (2 if mode == "after-append" else 1):
                with db.get_session() as current:
                    current.query(Draft).filter_by(id=ID).one().body = "Changed after observation"
            return result

    answer = invoke(row, mailbox_factory=ChangedAfter)
    assert not answer["ok"] and answer["cause"] == "draft_changed"
    assert "review-visible" not in answer["achieved_stages"]
    assert answer["provider_handles"]
    assert effects(path) == 1
    operation = DraftOperations().read(UID, "op-1")
    assert operation["stage"] != "completed"
    if mode != "reuse":
        assert answer["effect_certainty"] == "unknown"
        assert operation["active"]
    assert not invoke(row)["ok"]
    assert effects(path) == 1
