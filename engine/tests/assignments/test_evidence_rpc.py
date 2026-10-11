"""Public dispatcher with real stores and live-protocol fixture acceptance."""

import asyncio
import json
import pytest
from zylch.services import task_assignment_evidence as evidence
from mail_fixture import MailFixture, ROOT


def rpc(method, **params):
    from zylch.rpc.dispatch import dispatch_raw

    return asyncio.run(
        dispatch_raw(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tasks.assignment." + method,
                    "params": params,
                }
            ),
            lambda *a: None,
        )
    )


def result(method, **params):
    response = rpc(method, **params)
    assert "error" not in response, response
    return response["result"]


@pytest.fixture
def mail(env, monkeypatch):
    return MailFixture(monkeypatch)


def assign(env, **kwargs):
    intent = result(
        "preview",
        operation="assign",
        thread_key=ROOT,
        expected_revision=0,
        assignee_uid="bob",
        **kwargs,
    )
    grant = env.sign(intent)
    return intent, grant, result("commit", intent=intent, grant=grant)


def test_sent_candidate_supervised_grant(env, mail):
    source = result("reply_evidence", source_id=mail.reply_id, thread_key=ROOT)
    assert source["complete"] and source["judgement"] == "NONAUTOMATIC_MEMBER_REPLY_CANDIDATE"
    assert source["actor_uid"] == "alice" and source["source"]["provider"]["folder"] == '"Sent"'
    assert "body" not in json.dumps(source)
    projected = result("project", thread_key=ROOT)
    assert projected["state"] == "needs-assignment" and projected["hold_auto_reply"]
    intent, grant, receipt = assign(env, source_id=mail.reply_id)
    assert receipt["basis"] == "supervised_reply" and receipt["acknowledged"]
    assert result("commit", intent=intent, grant=grant) == receipt
    projected = result("project", thread_key=ROOT)
    assert projected["state"] == "assigned" and projected["complete"]
    assert projected["task"]["assignee_uid"] == "bob" and mail.closed >= 4
    assert all(call[2][1].startswith("(UID BODY.PEEK") for call in mail.calls if call[0] == "FETCH")


@pytest.mark.parametrize(
    "change,judgement",
    [
        ({"headers": {"Auto-Submitted": "auto-replied"}}, "AUTOMATIC"),
        ({"body": "Auto-replay message\ntext"}, "AUTOMATIC"),
        ({"body": "Ciao MrCaller!\ntext"}, "AUTOMATIC"),
        ({"recipient": "third@example.test"}, "UNKNOWN"),
        ({"reply": None}, "UNKNOWN"),
        ({"date": None}, "UNKNOWN"),
    ],
)
def test_actual_mail_semantics(env, mail, change, judgement):
    mail.replace_reply(**change)
    source = result("reply_evidence", source_id=mail.reply_id, thread_key=ROOT)
    assert source["judgement"] == judgement
    assert source["complete"] == (judgement == "AUTOMATIC")
    assert "error" in rpc(
        "preview",
        operation="assign",
        thread_key=ROOT,
        expected_revision=0,
        assignee_uid="bob",
        source_id=mail.reply_id,
    )
    assert result("list")["items"] == []


@pytest.mark.parametrize("failure", ["fail_search", "fail_fetch"])
def test_partial_provider_holds(env, mail, failure):
    setattr(mail, failure, True)
    source = result("reply_evidence", source_id=mail.reply_id, thread_key=ROOT)
    assert source["judgement"] == "UNKNOWN" and not source["complete"]
    projected = result("project", thread_key=ROOT)
    assert (
        projected["state"] == "unknown"
        and projected["hold_auto_reply"]
        and not projected["complete"]
    )


def test_local_sent_mirror_alone_refused(env, mail):
    mail.messages['"Sent"'].clear()
    assert (
        result("reply_evidence", source_id=mail.reply_id, thread_key=ROOT)["judgement"] == "UNKNOWN"
    )


def test_close_ack_and_new_identity_regardless_date(env, mail):
    _, _, assigned = assign(env)
    close = result(
        "preview",
        operation="close",
        thread_key=ROOT,
        expected_revision=1,
        task_id=assigned["task_id"],
        reason="Handled personally",
        handled_ref="handled-fixture",
    )
    assert close["covered_inbound"] and close["source_snapshot"]["digest"]
    grant = env.sign(close)
    receipt = result("commit", intent=close, grant=grant)
    assert receipt["acknowledged"] and receipt["state"] == "closed" and receipt["revision"] == 2
    assert result("commit", intent=close, grant=grant) == receipt
    assert result("project", thread_key=ROOT)["state"] == "closed"
    mail.add(
        "<later-same-second@example.test>",
        "customer@example.test",
        "alice@example.test",
        reply=ROOT,
    )
    projected = result("project", thread_key=ROOT)
    assert projected["state"] == "later-inbound" and not projected["hold_auto_reply"]
    assert "<later-same-second@example.test>" in projected["current_message_ids"]
    assert "<later-same-second@example.test>" not in projected["covered_message_ids"]
    assert projected["task"]["state"] == "closed"
    mail.add(
        "<later-old-date@example.test>",
        "customer@example.test",
        "alice@example.test",
        reply=ROOT,
        date="Wed, 07 Oct 2026 10:00:00 +0000",
    )
    assert result("project", thread_key=ROOT)["state"] == "later-inbound"
    assert len(result("get", thread_key=ROOT)["events"]) == 2


def test_unsynced_provider_inbound_holds(env, mail):
    assign(env)
    mail.add(
        "<unsynced@example.test>",
        "customer@example.test",
        "alice@example.test",
        reply=ROOT,
        store=False,
    )
    assert result("project", thread_key=ROOT)["state"] == "unknown"
    assert "error" in rpc(
        "preview",
        operation="close",
        thread_key=ROOT,
        expected_revision=1,
        reason="done",
        handled_ref="pending",
    )


def test_locked_db_recheck_refuses_intervening_inbound(env, mail, monkeypatch):
    assign(env)
    intent = result(
        "preview",
        operation="close",
        thread_key=ROOT,
        expected_revision=1,
        reason="done",
        handled_ref="pending",
    )
    grant = env.sign(intent)
    original = evidence.LiveEvidence.prepare

    def intervening(self, operation):
        value = original(self, operation)
        mail.add(
            "<intervening@example.test>", "customer@example.test", "alice@example.test", reply=ROOT
        )
        return value

    monkeypatch.setattr(evidence.LiveEvidence, "prepare", intervening)
    assert rpc("commit", intent=intent, grant=grant)["error"]["code"] == -32061
    assert result("get", thread_key=ROOT)["task"]["state"] == "assigned"
    assert len(result("get", thread_key=ROOT)["events"]) == 1


def test_uidvalidity_change_refuses_close(env, mail):
    assign(env)
    intent = result(
        "preview",
        operation="close",
        thread_key=ROOT,
        expected_revision=1,
        reason="done",
        handled_ref="pending",
    )
    mail.uidvalidity += 1
    assert "error" in rpc("commit", intent=intent, grant=env.sign(intent))
    assert result("get", thread_key=ROOT)["task"]["state"] == "assigned"


def test_source_changed_after_supervised_preview(env, mail):
    intent = result(
        "preview",
        operation="assign",
        thread_key=ROOT,
        expected_revision=0,
        assignee_uid="bob",
        source_id=mail.reply_id,
    )
    mail.replace_reply(body="Auto-reply notification")
    assert "error" in rpc("commit", intent=intent, grant=env.sign(intent))
    assert result("list")["items"] == []


def test_forgery_read_only_and_untrusted_actor_refuse(env, mail):
    intent = result(
        "preview", operation="assign", thread_key=ROOT, expected_revision=0, assignee_uid="bob"
    )
    assert "error" in rpc("commit", intent=intent, grant={"approved": True})
    grant = env.sign(intent)
    from zylch.services.request_policy import policy_scope, READ_ONLY_POLICY

    with policy_scope(READ_ONLY_POLICY):
        assert "error" in rpc("commit", intent=intent, grant=grant)
    for extra in ({"actor_uid": "bob"}, {"source_confirmation": {"approved": True}}):
        assert (
            rpc(
                "preview",
                operation="assign",
                thread_key=ROOT,
                expected_revision=0,
                assignee_uid="bob",
                **extra,
            )["error"]["code"]
            == -32602
        )
    assert result("list")["items"] == []
    env.select("outsider")
    assert "error" in rpc("list")


def test_private_source_id_owner_scoped(env, mail):
    env.select("bob")
    source = result("reply_evidence", source_id=mail.reply_id, thread_key=ROOT)
    assert (
        source["judgement"] == "UNKNOWN" and not source["complete"] and source["actor_uid"] == "bob"
    )


def test_peer_empty_snapshot_cannot_close_source_owner_assignment(env, mail):
    assign(env)
    env.select("bob")
    response = rpc(
        "preview",
        operation="close",
        thread_key=ROOT,
        expected_revision=1,
        reason="Handled",
        handled_ref="peer-empty",
    )
    assert response["error"]["code"] == -32060
    assert "source-owner" in response["error"]["message"]
    assert result("get", thread_key=ROOT)["task"]["state"] == "assigned"
    env.select("alice")
    intent = result(
        "preview",
        operation="close",
        thread_key=ROOT,
        expected_revision=1,
        reason="Handled",
        handled_ref="source-owner",
    )
    assert result("commit", intent=intent, grant=env.sign(intent))["state"] == "closed"
    env.select("bob")
    projection = result("project", thread_key=ROOT)
    assert projection["state"] == "unknown" and projection["hold_auto_reply"]
    assert (
        projection["source_owner_uid"] == "alice"
        and projection["reason"] == "SOURCE_OWNER_REQUIRED"
    )


def test_manual_assignment_empty_creator_scope_cannot_close(env, mail):
    env.select("bob")
    from zylch.email import mailboxes

    mailboxes.ensure_primary_mailbox()
    mail.messages = {"INBOX": {}, '"Archive"': {}, '"Sent"': {}}
    intent = result(
        "preview", operation="assign", thread_key=ROOT, expected_revision=0, assignee_uid="alice"
    )
    assert result("commit", intent=intent, grant=env.sign(intent))["acknowledged"]
    reply = rpc(
        "preview",
        operation="close",
        thread_key=ROOT,
        expected_revision=1,
        reason="Done",
        handled_ref="empty-scope",
    )
    assert reply["error"]["code"] == -32060
    assert "inbound source coverage" in reply["error"]["message"]
    assert result("get", thread_key=ROOT)["task"]["state"] == "assigned"


def test_uidvalidity_changes_during_actual_fetch_are_unknown(env, mail, monkeypatch):
    from zylch.email.imap_client import IMAPClient

    original = IMAPClient.fetch_messages_by_uid

    def changed(client, folder, uids):
        value = original(client, folder, uids)
        mail.uidvalidity += 1
        return value

    monkeypatch.setattr(IMAPClient, "fetch_messages_by_uid", changed)
    source = result("reply_evidence", source_id=mail.reply_id, thread_key=ROOT)
    assert source["judgement"] == "UNKNOWN" and not source["complete"]
    assert mail.closed == 1


@pytest.mark.parametrize(
    "message_id", [None, "<unrelated@example.test>", "<one@example.test> <two@example.test>"]
)
def test_claimed_thread_without_exact_rfc_identity_is_unknown(env, mail, message_id):
    from zylch.storage import database as db
    from zylch.storage.models import Email

    with db.get_session() as session:
        session.query(Email).filter(Email.id == mail.reply_id).delete()
        row = session.query(Email).filter(Email.id == mail.root_id).one()
        row.message_id_header = message_id
        row.in_reply_to = None
        row.references = None
        row.thread_id = ROOT
    mail.messages = {"INBOX": {}, '"Archive"': {}, '"Sent"': {}}
    projected = result("project", thread_key=ROOT)
    assert projected["state"] == "unknown" and not projected["complete"]
    assert projected["hold_auto_reply"] and projected["reason"] == "SOURCE_UNAVAILABLE"
    assert result("get", thread_key=ROOT)["task"] is None
