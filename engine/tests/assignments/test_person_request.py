"""A person's explicit request writes and sends on the exact named source, held by nothing."""

import asyncio
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from test_draft_policy import mail as mail_fixture, payload
from test_evidence_rpc import assign
from mail_fixture import ROOT, REPLY
from zylch.services import exact_operator_send as send_service
from zylch.services import exact_operator_send_admission as admission
from zylch.services import operator_reply_origin
from zylch.services import person_request
from zylch.services import task_assignment_draft_policy as policy
from zylch.services import task_assignment_projection as projection
from zylch.services.exact_draft_publication_mime import observation
from zylch.services.task_assignment_types import AssignmentError
from zylch.storage import database as db
from zylch.storage.models import Draft, Email
from zylch.storage.storage import Storage

OWNER, UID = "alice@example.test", "alice"
OTHER_ROOT = "<other-root@example.test>"


@pytest.fixture
def mail(env, monkeypatch):
    return mail_fixture.__wrapped__(env, monkeypatch)


def source_row(source_id):
    with db.get_session() as session:
        row = session.query(Email).filter(Email.owner_id == OWNER, Email.id == source_id).one()
        return row.to_dict()


def request_for(mail):
    return person_request.from_row(OWNER, source_row(mail.root_id))


def count():
    with db.get_session() as session:
        return session.query(Draft).count()


def member_reply(mail):
    """A member's own reply in Sent: the thread is held for people."""
    mail.add(REPLY, OWNER, "customer@example.test", folder='"Sent"', reply=ROOT)


def ancestry_conflict(mail):
    """A stored reply whose References join two stored roots: the RFC conflict projection."""
    mail.add(OTHER_ROOT, "someone@example.test", OWNER)
    mail.add(
        "<crossed@example.test>",
        "customer@example.test",
        OWNER,
        reply=ROOT,
        headers=None,
    )
    with db.get_session() as session:
        row = session.query(Email).filter(Email.message_id_header == "<crossed@example.test>").one()
        row.references = f"{OTHER_ROOT} {ROOT}"


@pytest.fixture
def transport(env, mail, monkeypatch):
    """SMTP and the Sent mailbox stand-ins the exact send verifies against."""
    smtp = MagicMock()
    smtp.__enter__.return_value = smtp
    raws = []
    smtp.sendmail.side_effect = (
        lambda *args: raws.append(args[2].encode() if isinstance(args[2], str) else args[2]) or {}
    )
    monkeypatch.setattr("zylch.email.imap_client.smtplib.SMTP", lambda *a, **kw: smtp)

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

    monkeypatch.setattr(send_service, "RetirementMailbox", SentMailbox)
    return smtp, raws


def send_selected(selected, operation="person-send-1"):
    """One exact send of an inspected draft; a retry replays the same snapshot and binding."""
    return asyncio.run(
        send_service.send(
            OWNER,
            UID,
            selected["draft_id"],
            selected["expected_snapshot"],
            operation,
            selected["binding"],
            lambda: (OWNER, UID),
        )
    )


def exact_send(draft_id, operation="person-send-1"):
    return send_selected(send_service.inspect(OWNER, UID, draft_id), operation)


def write_draft(mail, **changes):
    with policy.scope(ROOT):
        return Storage.get_instance().create_draft(**{**payload(), **changes})


def test_marker_identity_comes_from_the_stored_row(env, mail):
    request = request_for(mail)
    assert request.root == ROOT and request.target == ROOT and request.source_id == mail.root_id
    assert request.known_identifiers() == {ROOT}
    wrapped = dict(source_row(mail.root_id), original_message_id="<wrapped@example.test>")
    with pytest.raises(AssignmentError):
        person_request.from_row(OWNER, wrapped)
    assert person_request.active() is None
    with person_request.scope(request):
        assert person_request.active() == request
        with pytest.raises(AssignmentError):
            with person_request.scope(request):
                pass
    assert person_request.active() is None


def test_marker_refused_under_scheduled_origin(env, mail):
    request = request_for(mail)

    async def callback(*args):
        raise AssertionError("scheduled admission reached")

    with operator_reply_origin.scope(callback):
        with pytest.raises(AssignmentError, match="not_interactive"):
            with person_request.scope(request):
                pass


def test_guard_without_marker_refuses_assigned_thread(env, mail):
    assign(env)
    assert projection.project(ROOT)["state"] == "assigned"
    with pytest.raises(AssignmentError):
        write_draft(mail)
    assert count() == 0


@pytest.mark.parametrize("state", ["needs-assignment", "assigned", "conflict", "unknown"])
def test_marker_writes_the_draft_on_every_assignment_state(env, mail, state):
    if state == "needs-assignment":
        member_reply(mail)
    elif state == "assigned":
        assign(env)
    elif state == "conflict":
        ancestry_conflict(mail)
    else:
        mail.fail_search = True
    projected = projection.project(ROOT)
    assert projected["state"] == state and projected["hold_auto_reply"], projected
    with pytest.raises(AssignmentError):
        write_draft(mail)
    assert count() == 0
    with person_request.scope(request_for(mail)):
        draft = write_draft(mail)
    assert draft["created"] and count() == 1
    assert draft["thread_id"] == ROOT and draft["in_reply_to"] == ROOT


@pytest.mark.parametrize("state", ["needs-assignment", "assigned", "conflict", "unknown"])
def test_marker_sends_on_every_assignment_state(env, mail, transport, state):
    smtp, raws = transport
    with person_request.scope(request_for(mail)):
        draft = write_draft(mail)
    if state == "needs-assignment":
        member_reply(mail)
    elif state == "assigned":
        assign(env)
    elif state == "conflict":
        ancestry_conflict(mail)
    else:
        mail.fail_search = True
    if state != "unknown":
        assert projection.project(ROOT)["state"] == state
    if state != "needs-assignment":
        # Without the marker the exact send refuses or raises on these states;
        # the member-reply hold alone is admitted today through manual_hold.
        try:
            refused = exact_send(draft["id"], operation="without-marker")
        except AssignmentError:
            refused = {"ok": False}
        assert not refused["ok"] and smtp.sendmail.call_count == 0, refused
    with person_request.scope(request_for(mail)):
        selected = send_service.inspect(OWNER, UID, draft["id"])
        answer = send_selected(selected)
    assert answer["ok"] and answer["cause"] == "exact_sent_verified", answer
    assert smtp.sendmail.call_count == 1
    assert Storage.get_instance().get_draft(OWNER, draft["id"])["status"] == "sent"
    with person_request.scope(request_for(mail)):
        again = send_selected(selected)
    assert again["ok"] and again["cause"] == "exact_sent_verified", again
    assert smtp.sendmail.call_count == 1


@pytest.mark.parametrize(
    "change",
    ["owner", "thread", "target", "references", "source_removed"],
)
def test_marker_keeps_the_exact_binding(env, mail, change):
    request = request_for(mail)
    values = {}
    if change == "owner":
        values["owner_id"] = "other@example.test"
    elif change == "thread":
        values["thread_id"] = OTHER_ROOT
    elif change == "target":
        mail.add("<later@example.test>", "customer@example.test", OWNER, reply=ROOT)
        values["in_reply_to"] = "<later@example.test>"
    elif change == "references":
        values["references"] = [ROOT, "<foreign@example.test>"]
    else:
        with db.get_session() as session:
            session.query(Email).filter(Email.id == mail.root_id).delete()
    with person_request.scope(request), pytest.raises(AssignmentError):
        with policy.scope(values.get("thread_id", ROOT)):
            Storage.get_instance().create_draft(**{**payload(), **values})
    assert count() == 0


def test_resolve_takes_the_stored_anchor_of_an_in_reply_to_only_source(env, mail, transport):
    smtp, raws = transport
    parent, child = "<parent@example.test>", "<child@example.test>"
    mail.add(parent, "customer@example.test", OWNER)
    source_id = str(uuid.uuid4())
    with db.get_session() as session:
        session.add(
            Email(
                id=source_id,
                owner_id=OWNER,
                mailbox_id=mail.box,
                gmail_id=child,
                thread_id=parent,
                message_id_header=child,
                from_email="customer@example.test",
                to_email=OWNER,
                references=None,
                in_reply_to=parent,
                date=datetime(2026, 10, 9, 10),
                body_plain="Second question",
            )
        )
    draft = Storage.get_instance().create_draft(
        **{**payload(parent), "in_reply_to": child, "references": [parent, child]}
    )
    bound = admission.resolve(OWNER, draft)
    assert bound["root"] == parent and bound["target"] == child
    assert exact_send(draft["id"])["ok"]
    assert smtp.sendmail.call_count == 1


def test_resolve_keeps_the_refusal_of_a_wrapped_source(env, mail):
    parent, child = "<parent@example.test>", "<child@example.test>"
    with db.get_session() as session:
        session.add(
            Email(
                id=str(uuid.uuid4()),
                owner_id=OWNER,
                mailbox_id=mail.box,
                gmail_id=child,
                thread_id=parent,
                message_id_header=child,
                from_email="customer@example.test",
                to_email=OWNER,
                references=None,
                in_reply_to=parent,
                original_message_id="<original@example.test>",
                date=datetime(2026, 10, 9, 10),
                body_plain="Wrapped original",
            )
        )
    draft = Storage.get_instance().create_draft(
        **{**payload(parent), "in_reply_to": child, "references": [parent, child]}
    )
    with pytest.raises(AssignmentError, match="exact_source_conflict"):
        admission.resolve(OWNER, draft)
