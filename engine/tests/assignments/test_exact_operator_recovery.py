"""Real native claims and journal recovery through the ordinary send boundary."""

import os
import asyncio
import json
import threading
from email import policy
from email.parser import BytesParser

import pytest
from test_exact_operator_send import (
    mail as mail_fixture,
    prepared as prepared_fixture,
    send,
    OWNER,
    UID,
)
from zylch.services import exact_operator_send as service
from zylch.services import task_assignment_projection as projection
from zylch.storage.draft_operations import DraftOperations
from zylch.storage.storage import Storage
from zylch.storage import database as db
from zylch.storage.models import Draft, Email


@pytest.fixture
def mail(env, monkeypatch):
    return mail_fixture.__wrapped__(env, monkeypatch)


@pytest.fixture
def prepared(env, mail, monkeypatch):
    return prepared_fixture.__wrapped__(env, mail, monkeypatch)


def accepted_loss(transport):
    original = transport.sendmail.side_effect

    def accepted(*args):
        original(*args)
        raise ConnectionResetError("accepted with lost acknowledgment")

    transport.sendmail.side_effect = accepted


def test_setup_failure_releases_exact_executor(env, mail, prepared, monkeypatch):
    selected, transport, raws = prepared
    original = service.client_for
    monkeypatch.setattr(
        service, "client_for", lambda owner: (_ for _ in ()).throw(ValueError())
    )
    answer = send(selected)
    assert answer["effect_certainty"] == "not-dispatched"
    operation = DraftOperations().read(UID, "send-1")
    assert operation["stage"] == "not_dispatched" and not operation["active"]
    assert send(selected)["effect_certainty"] == "not-dispatched"
    monkeypatch.setattr(service, "client_for", original)
    assert send(selected, "new-explicit-operation")["ok"]
    assert transport.sendmail.call_count == 1


def test_login_failure_releases_native_claim(env, mail, prepared):
    selected, transport, raws = prepared
    transport.login.side_effect = ConnectionError("before wire")
    assert send(selected)["effect_certainty"] == "not-dispatched"
    assert (
        Storage.get_instance().get_draft(OWNER, selected["draft_id"])["status"]
        == "draft"
    )
    assert not DraftOperations().read(UID, "send-1")["active"]
    assert not transport.sendmail.called


def test_accepted_loss_reconciles_once(env, mail, prepared):
    selected, transport, raws = prepared
    accepted_loss(transport)
    assert send(selected)["state"] == "delivery-unknown"
    operation = DraftOperations().read(UID, "send-1")
    wire = BytesParser(policy=policy.default).parsebytes(raws[0])
    assert operation["binding"]["transport"]["message_id"] == str(wire["Message-ID"])
    assert operation["output_mime_digest"] == service.digest(wire)
    assert (
        Storage.get_instance().get_draft(OWNER, selected["draft_id"])["status"]
        == "sending"
    )
    assert send(selected)["ok"]
    assert send(selected)["ok"]
    assert (
        Storage.get_instance().get_draft(OWNER, selected["draft_id"])["status"]
        == "sent"
    )
    assert not DraftOperations().read(UID, "send-1")["active"]
    assert transport.sendmail.call_count == 1


@pytest.mark.parametrize(
    "changed",
    [
        "body",
        "recipient",
        "source",
        "owner",
        "duplicate",
        "provider_body",
        "provider_date",
    ],
)
def test_recovery_preserves_changed_or_ambiguous_evidence(env, mail, prepared, changed):
    selected, transport, raws = prepared
    accepted_loss(transport)
    assert send(selected)["state"] == "delivery-unknown"
    if changed in {"body", "recipient", "owner"}:
        with db.get_session() as session:
            draft = session.query(Draft).filter_by(id=selected["draft_id"]).one()
            if changed == "body":
                draft.body = "Changed"
            if changed == "recipient":
                draft.to_addresses = ["other@example.test"]
            if changed == "owner":
                draft.owner_id = "other@example.test"
    elif changed == "source":
        with db.get_session() as session:
            session.query(Email).filter_by(
                id=selected["binding"]["source"]["id"]
            ).one().from_email = "other@example.test"
    elif changed == "duplicate":
        raws.append(raws[0])
    else:
        message = BytesParser(policy=policy.default).parsebytes(raws[0])
        if changed == "provider_body":
            message.set_content("Changed")
        else:
            message.replace_header("Date", "Wed, 04 Nov 2026 12:00:00 +0000")
        raws[0] = message.as_bytes()
    assert not send(selected)["ok"]
    assert DraftOperations().read(UID, "send-1")["active"]
    assert transport.sendmail.call_count == 1


def test_crash_after_acceptance_restart_and_concurrent_reconcile(
    env, mail, prepared, tmp_path
):
    selected, transport, raws = prepared
    raw_path = tmp_path / "accepted.eml"

    def crash(*args):
        operation = DraftOperations().read(UID, "send-1")
        assert operation["stage"] == "dispatch_possible"
        assert operation["binding"]["transport"]["message_id"]
        raw_path.write_text(args[2])
        os._exit(0)

    transport.sendmail.side_effect = crash
    child = os.fork()
    if child == 0:
        send(selected)
        os._exit(9)
    _, status = os.waitpid(child, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    assert (
        Storage.get_instance().get_draft(OWNER, selected["draft_id"])["status"]
        == "sending"
    )
    raws.append(raw_path.read_bytes())
    results = []
    workers = [
        threading.Thread(target=lambda: results.append(send(selected)))
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(10)
    assert len(results) == 2 and any(result["ok"] for result in results)
    assert send(selected)["ok"] and not transport.sendmail.called
    assert DraftOperations().read(UID, "send-1")["stage"] == "completed"


@pytest.mark.parametrize(
    "later_guard", ["none", "assignment", "pause", "self", "suppression"]
)
def test_real_cli_recovers_accepted_lost_ack(
    env, mail, prepared, monkeypatch, tmp_path, capsys, later_guard
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
    accepted_loss(transport)
    monkeypatch.setenv("HOME", str(tmp_path / "kernel"))
    settings = config.Settings(email_address=OWNER, engine_owner_uid=UID)
    monkeypatch.setattr(config, "load", lambda: settings)

    calls = []

    def call(settings, method, params, timeout=None):
        calls.append(method)
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
    assert cli.main(args) == 3
    assert json.loads(capsys.readouterr().out)["effect_certainty"] == "unknown"
    if later_guard == "none":
        import time
        from cs.monitor import scan
        from cs.monitor_config import Component, MonitorConfig
        from cs.observability import store_for
        monitor = MonitorConfig(monitor_id="a" * 32, owner_uid=UID,
            state_dir=str(tmp_path / "collector"), expected_start_utc=int(time.time()),
            mode="filesystem", components=[Component(id="operator", kind="kernel",
            local_root=str(store_for(settings).root))])
        scan(monitor, now=time.time()+1)
        initial = json.loads((tmp_path / "collector" / "problems.json").read_text())
        assert initial["problems"] and all(problem["evidence"]["uncertain"] for problem in initial["problems"])
    if later_guard == "assignment":
        from test_evidence_rpc import assign

        assign(env)
    if later_guard == "pause":
        settings.state_dir.mkdir(parents=True, exist_ok=True)
        settings.pause_path.touch()
    if later_guard == "self":
        settings.self_emails = "customer@example.test"
    if later_guard == "suppression":
        from cs.state import State

        local = State(settings.db_path)
        local.conn.execute(
            "INSERT INTO do_not_contact(email,reason,added_at) VALUES ('customer@example.test','fixture','2026-11-05')"
        )
        local.conn.commit()
        local.conn.close()
    if later_guard != "none":
        calls.clear()
        fresh = [
            "new-operation" if value == "cli-operation" else value for value in args
        ]
        assert cli.main(fresh) == 3
        assert (
            json.loads(capsys.readouterr().out)["effect_certainty"] == "not-dispatched"
        )
        assert "drafts.send_operator" not in calls
    calls.clear()
    assert cli.main(args) == 5
    assert json.loads(capsys.readouterr().out)["effect_certainty"] == "verified"
    assert "tasks.assignment.project" not in calls
    from cs.observability import store_for
    diagnostic = store_for(settings).events()["events"]
    causes = {event["causal"]["cause"] for event in diagnostic if event.get("causal")}
    assert "uncertain_provider_outcome" in causes
    assert "sent_verified_cleanup_pending" in causes
    if later_guard == "none":
        for _ in range(2):
            scan(monitor, now=time.time()+1)
            final = json.loads((tmp_path / "collector" / "problems.json").read_text())
            assert final["problems"]
            assert all(not problem["evidence"]["uncertain"] for problem in final["problems"])
            assert all(problem["evidence"]["causal"]["cause"] == "sent_verified_cleanup_pending" for problem in final["problems"])
    assert transport.sendmail.call_count == 1
