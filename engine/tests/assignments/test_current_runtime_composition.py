"""Effective component authority composes with the M10 effect transaction."""

import asyncio
import sqlite3
from email import message_from_bytes
from contextlib import contextmanager

import pytest

from test_scheduled_reply_origin import (
    sent_journey as _sent_journey,
    _scripted_chat,
    _chat_call,
    _origin_params,
    OWNER,
    R5_ROOT,
)
from zylch.email.imap_client import IMAPClient
from zylch.services import contextual_email_policy as contextual
from zylch.services import project_store
from zylch.services import task_assignment_trust as trust
from zylch.services.task_assignment_types import AssignmentError
from zylch.storage import database as db
from zylch.storage.models import Email

ALIAS = "<component-alias@example.test>"


@pytest.fixture
def sent_journey(env, monkeypatch, tmp_path):
    return _sent_journey.__wrapped__(env, monkeypatch, tmp_path)


def alias_source(journey):
    source = journey.mail.add(ALIAS, "customer@example.test", OWNER, reply=R5_ROOT)
    with db.get_session() as session:
        row = session.query(Email).filter_by(id=source).one()
        row.references = R5_ROOT
        row.thread_id = R5_ROOT
    folder = journey.mail.messages['"Archive"']
    uid = max(folder)
    message = message_from_bytes(folder[uid])
    message.replace_header("References", R5_ROOT)
    folder[uid] = message.as_bytes()
    return source


def alias_draft(journey):
    return journey.store.create_draft(
        owner_id=OWNER,
        to="customer@example.test",
        subject="Alias reply",
        body="Answer",
        thread_id=ALIAS,
        in_reply_to=ALIAS,
        references=[R5_ROOT, ALIAS],
    )


@pytest.mark.parametrize("scheduled", [False, True])
def test_rpc_approval_alias_to_actual_smtp_retains_exact_reply_target(
    env, sent_journey, monkeypatch, scheduled
):
    alias_source(sent_journey)
    draft = alias_draft(sent_journey)
    _scripted_chat(monkeypatch, sent_journey, draft)
    params = _origin_params() if scheduled else {"message": "manual", "conversation_id": "manual"}
    result = asyncio.run(_chat_call(params, dispatch=True))
    assert result["status"] == "success", result
    message = sent_journey.captured[0]
    assert str(message["In-Reply-To"]) == ALIAS
    assert str(message["References"]) == R5_ROOT + " " + ALIAS
    assert message["Auto-Submitted"] == ("auto-replied" if scheduled else None)
    assert sent_journey.store.get_draft(OWNER, draft["id"])["status"] == "sent"


def test_explicit_context_alias_and_foreign_component(env, sent_journey):
    source = alias_source(sent_journey)
    binding = contextual.source_binding(OWNER, {"thread_key": ALIAS, "source_email_id": source})
    assert binding.root == R5_ROOT and binding.target == ALIAS
    with contextual.scope(binding):
        assert alias_draft(sent_journey)["created"]
    with pytest.raises(AssignmentError):
        contextual.source_binding(
            OWNER, {"thread_key": "<foreign@example.test>", "source_email_id": source}
        )
    with pytest.raises(AssignmentError):
        contextual.source_binding(
            "bob@example.test", {"thread_key": ALIAS, "target_message_id": ALIAS}
        )


@pytest.mark.parametrize("drift", ["component", "routes", "task", "source", "mailbox"])
def test_final_company_to_private_reservation_rejects_authority_drift(
    env, sent_journey, monkeypatch, drift
):
    alias_source(sent_journey)
    draft = alias_draft(sent_journey)
    original = project_store.connection
    changed = []

    @contextmanager
    def intervene(expected_space=None, write=False):
        if write and not changed:
            changed.append(drift)
            if drift == "routes":
                monkeypatch.setattr(trust, "delivery_routes_digest", lambda space: "f" * 64)
            elif drift == "task":
                from test_evidence_rpc import result

                intent = result(
                    "preview",
                    operation="assign",
                    thread_key=ALIAS,
                    expected_revision=0,
                    assignee_uid="bob",
                )
                result("commit", intent=intent, grant=env.sign(intent))
            else:
                from zylch.storage.models import Mailbox

                with db.get_session() as session:
                    if drift == "mailbox":
                        session.query(Mailbox).filter_by(
                            id=sent_journey.mail.box
                        ).one().imap_port = 994
                    else:
                        row = session.query(Email).filter_by(id=sent_journey.mail.root_id).one()
                        if drift == "component":
                            row.cc_email = "other@example.test"
                        else:
                            session.query(Email).filter_by(
                                message_id_header=ALIAS
                            ).one().from_email = "changed@example.test"
        with original(expected_space, write) as value:
            yield value

    monkeypatch.setattr(project_store, "connection", intervene)
    with pytest.raises(AssignmentError):
        sent_journey.store.update_draft(OWNER, draft["id"], {"body": "Changed"})
    assert sent_journey.store.get_draft(OWNER, draft["id"])["body"] == "Answer"
    assert not sent_journey.captured


def test_actual_smtp_retains_single_private_writer_and_company_fence(
    env, sent_journey, monkeypatch
):
    alias_source(sent_journey)
    draft = alias_draft(sent_journey)
    _scripted_chat(monkeypatch, sent_journey, draft)
    checks = []
    original = sent_journey.SMTP.sendmail

    def wire(self, *args):
        for path, statement in [
            (env.memory.url.database, "UPDATE project_space SET space_id=space_id"),
            (db.get_engine().url.database, "UPDATE emails SET id=id WHERE 0"),
        ]:
            with sqlite3.connect(path, timeout=0.02) as contender:
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    contender.execute(statement)
            checks.append("writer held")
        return original(self, *args)

    monkeypatch.setattr(sent_journey.SMTP, "sendmail", wire)
    assert asyncio.run(_chat_call(_origin_params(), dispatch=True))["status"] == "success"
    assert checks == ["writer held", "writer held"] and len(sent_journey.captured) == 1


@pytest.mark.parametrize("method", ["send", "send_message"])
def test_both_real_imap_entrypoints_retain_automatic_provenance(
    env, sent_journey, monkeypatch, method
):
    from zylch.services import operator_reply_origin as origin
    from zylch.rpc.methods import _admit_operator_reply

    alias_source(sent_journey)
    draft = alias_draft(sent_journey)
    with origin.scope(lambda owner, value: _admit_operator_reply(owner, value, lambda *a: None)):
        admission = asyncio.run(origin.admit(OWNER, draft))
        with origin.handoff(admission, OWNER, draft):
            getattr(IMAPClient(OWNER, "fixture"), method)(
                to="customer@example.test",
                subject="Reply",
                body="Answer",
                in_reply_to=ALIAS,
                references=R5_ROOT + " " + ALIAS,
            )
    assert sent_journey.captured[0]["Auto-Submitted"] == "auto-replied"
    assert origin._request.get() is None and origin._send.get() is None
