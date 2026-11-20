"""Exact operator requests use real assignment authority, SQLite claims and normal SMTP tooling."""

import asyncio
from datetime import datetime, timedelta
import json
import threading
from unittest.mock import MagicMock

import pytest
from test_draft_policy import mail as mail_fixture, payload
from test_evidence_rpc import assign
from mail_fixture import ROOT, REPLY
from zylch.services import exact_operator_send as service
from zylch.services import task_assignment_projection as projection
from zylch.services import operator_reply_origin
from zylch.services.exact_draft_publication_mime import observation
from zylch.storage import database as db
from zylch.storage.models import Draft
from zylch.storage.storage import Storage
from zylch.storage.draft_operations import DraftOperations

OWNER, UID = "alice@example.test", "alice"


@pytest.fixture
def mail(env, monkeypatch):
    return mail_fixture.__wrapped__(env, monkeypatch)


@pytest.fixture
def prepared(env, mail, monkeypatch):
    storage = Storage.get_instance()
    row = storage.create_draft(**payload())
    mail.add(REPLY, OWNER, "customer@example.test", folder='"Sent"', reply=ROOT)
    transport = MagicMock()
    transport.__enter__.return_value = transport
    raws = []
    transport.sendmail.side_effect = (
        lambda *args: raws.append(args[2].encode() if isinstance(args[2], str) else args[2]) or {}
    )
    monkeypatch.setattr("zylch.email.imap_client.smtplib.SMTP", lambda *a, **kw: transport)

    class SentMailbox:
        def __init__(self, owner):
            pass

        def inventory(self, *args, **kw):
            return [observation(raw, str(i + 1), []) for i, raw in enumerate(raws)], {
                "folder": "Sent",
                "uidvalidity": "1",
                "complete": True,
                "digest": str(len(raws)),
            }

        def close(self):
            pass

    monkeypatch.setattr(service, "RetirementMailbox", SentMailbox)
    selected = service.inspect(OWNER, UID, row["id"])
    return selected, transport, raws


def send(selected, operation="send-1", **overrides):
    values = dict(
        owner=OWNER,
        uid=UID,
        draft_id=selected["draft_id"],
        expected=selected["expected_snapshot"],
        operation_id=operation,
        bound=selected["binding"],
        recheck=lambda: (OWNER, UID),
    )
    return asyncio.run(service.send(**dict(values, **overrides)))


def test_manual_hold_bypassed_only_for_exact_request_once(env, mail, prepared):
    selected, transport, raws = prepared
    before = projection.project(ROOT)
    assert before["hold_auto_reply"] and before["state"] == "needs-assignment"
    answer = send(selected)
    assert answer["ok"], answer
    assert answer["state"] == "sent-with-cleanup-pending"
    assert projection.project(ROOT)["hold_auto_reply"]
    assert send(selected)["ok"]
    assert transport.sendmail.call_count == 1
    assert b"Auto-Submitted:" not in raws[0]
    assert DraftOperations().read(UID, "send-1")["stage"] == "completed"


def test_normal_tool_keeps_manual_hold(env, mail, prepared):
    from zylch.tools.gmail_tools import SendDraftTool

    selected, transport, raws = prepared
    result = asyncio.run(
        SendDraftTool(service.client_for(OWNER), Storage.get_instance(), OWNER).execute(
            draft_id=selected["draft_id"]
        )
    )
    assert result.status.value == "error"
    assert transport.sendmail.call_count == 0


@pytest.mark.parametrize("change", ["root", "source", "recipients", "snapshot", "owner"])
def test_request_binding_negatives(env, mail, prepared, change):
    from copy import deepcopy

    selected, transport, raws = prepared
    overrides = {}
    bound = deepcopy(selected["binding"])
    if change == "root":
        bound["root"] = "<other@example.test>"
    if change == "source":
        bound["source"]["id"] = "different"
    if change == "recipients":
        bound["recipients"] = ["foreign@example.test"]
    if change == "snapshot":
        overrides["expected"] = "0" * 64
    if change == "owner":
        overrides["owner"] = "other@example.test"
    answer = send(selected, bound=bound, **overrides)
    assert not answer["ok"] and transport.sendmail.call_count == 0


def test_other_assignee_and_incomplete_evidence_hold(env, mail, prepared):
    selected, transport, raws = prepared
    mail.fail_search = True
    assert not send(selected)["ok"]
    mail.fail_search = False
    assign(env)
    assert not send(selected)["ok"]
    assert transport.sendmail.call_count == 0


def test_scheduled_and_readonly_refused_before_effect(env, mail, prepared):
    from zylch.services.request_policy import policy_scope, ReadOnlyViolation

    selected, transport, raws = prepared

    async def callback(*args):
        raise AssertionError("scheduled admission reached")

    with operator_reply_origin.scope(callback):
        assert send(selected)["cause"] == "operator_request_not_interactive"
    with policy_scope("read_only"), pytest.raises(ReadOnlyViolation):
        send(selected)
    assert transport.sendmail.call_count == 0


def test_uncertain_send_survives_expired_claim_without_retry(env, mail, prepared):
    selected, transport, raws = prepared
    transport.sendmail.side_effect = ConnectionResetError("unknown")
    assert send(selected)["state"] == "delivery-unknown"
    operation = DraftOperations().read(UID, "send-1")
    assert operation["stage"] == "dispatch_possible" and operation["active"]
    with db.get_session() as current:
        current.query(Draft).filter_by(id=selected["draft_id"]).one().updated_at = (
            datetime.utcnow() - timedelta(days=10)
        )
    assert not Storage.get_instance().claim_draft_for_send(OWNER, selected["draft_id"])
    import subprocess
    import sys

    process = subprocess.run(
        [
            sys.executable,
            "-c",
            "from zylch.storage.storage import Storage; import sys; print(object.__new__(Storage).claim_draft_for_send(sys.argv[1],sys.argv[2]))",
            OWNER,
            selected["draft_id"],
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert process.returncode == 0 and process.stdout.strip() == "False", process.stderr
    assert not send(selected)["ok"]
    assert transport.sendmail.call_count == 1


def test_concurrent_exact_operations_one_real_claim(env, mail, prepared):
    selected, transport, raws = prepared
    entered, release = threading.Event(), threading.Event()
    original = transport.sendmail.side_effect

    def wire(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)

    transport.sendmail.side_effect = wire
    answers = []
    worker = threading.Thread(target=lambda: answers.append(send(selected)))
    worker.start()
    try:
        assert entered.wait(10)
        second = send(selected)
        assert not second["ok"]
    finally:
        release.set()
        worker.join(10)
    assert answers[0]["ok"] and transport.sendmail.call_count == 1


def test_rpc_parameter_contracts_are_closed():
    from zylch.rpc.dispatch import dispatch_raw
    from zylch.rpc import param_spec

    for method in (
        "drafts.retire_sent_mirror",
        "drafts.send_operator",
        "drafts.operator_send_inspect",
    ):
        assert method not in param_spec.OPEN_METHODS
        answer = asyncio.run(
            dispatch_raw(
                json.dumps(
                    {"jsonrpc": "2.0", "id": 1, "method": method, "params": {"unknown": True}}
                ),
                lambda *a: None,
            )
        )
        assert answer["error"]["code"] == -32602


def test_real_cli_exact_request_and_repeat_no_generation(
    env, mail, prepared, monkeypatch, tmp_path, capsys
):
    import sys
    import os

    kernel = os.environ.get("CS_KERNEL_SOURCE")
    if not kernel:
        pytest.skip("cross-repository CLI fixture requires CS_KERNEL_SOURCE")
    sys.path.insert(0, kernel)
    from cs import cli, config, rpc
    from zylch.rpc import exact_drafts

    selected, transport, raws = prepared
    monkeypatch.setenv("HOME", str(tmp_path / "kernel"))
    settings = config.Settings(email_address=OWNER, engine_owner_uid=UID)
    monkeypatch.setattr(config, "load", lambda: settings)

    def call(settings, method, params, timeout=None):
        if method == "system.capabilities":
            return {"interactive_exact_send": 1}
        if method == "tasks.assignment.project":
            return projection.project(params["thread_key"])
        return asyncio.run(exact_drafts.METHODS[method](params, None))

    monkeypatch.setattr(rpc, "call_sync", call)

    async def no_chat(*args, **kwargs):
        raise AssertionError("generation forbidden")

    monkeypatch.setattr(rpc, "chat", no_chat)
    args = [
        "draft-send",
        selected["draft_id"],
        "--operator-request",
        "--operation-id",
        "cli-operation",
        "--json",
    ]
    assert cli.main(args) == 5
    assert json.loads(capsys.readouterr().out)["effect_certainty"] == "verified"
    assert cli.main(args) == 5
    assert transport.sendmail.call_count == 1


@pytest.mark.parametrize(
    "method,params",
    [
        (
            "drafts.send_operator",
            {
                "draft_id": "draft",
                "expected_snapshot": "snapshot",
                "operation_id": "operation",
                "binding": {},
                "reason": "explicit_operator_request",
                "version": True,
            },
        ),
        (
            "drafts.retire_sent_mirror",
            {
                "draft_id": "draft",
                "expected_snapshot": "snapshot",
                "thread_id": ROOT,
                "operation_id": "operation",
                "target": [],
                "commit": False,
            },
        ),
        (
            "drafts.retire_sent_mirror",
            {
                "draft_id": "draft",
                "expected_snapshot": "snapshot",
                "thread_id": ROOT,
                "operation_id": "operation",
                "target": {},
                "commit": 1,
            },
        ),
    ],
)
def test_rpc_exact_types_reject_before_effect(method, params):
    from zylch.rpc.dispatch import dispatch_raw

    answer = asyncio.run(
        dispatch_raw(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}),
            lambda *a: None,
        )
    )
    assert answer["error"]["code"] == -32602
