"""Actual draft/SMTP writes are serialized with company assignment authority."""

import asyncio
import sqlite3
import threading
from unittest.mock import MagicMock

import pytest
from sqlalchemy import update
from test_draft_policy import mail, payload, count
from test_evidence_rpc import assign
from mail_fixture import ROOT
from zylch.email.imap_client import IMAPClient
from zylch.services import project_store
from zylch.services import task_assignment_email_effect as policy
from zylch.services import task_assignment_enrollment as enrollment
from zylch.services.task_assignment_types import AssignmentError
from zylch.storage.storage import Storage
from zylch.storage.assigned_task_models import AssignmentEnrollment


def make_unmanaged(env):
    # Fixture construction only: a company genuinely never enabled authority.
    env.trust_file.unlink()
    with env.memory.begin() as conn:
        conn.execute(update(AssignmentEnrollment).values(
            state="never-enabled", provenance=[{"kind": "fresh-company-fixture"}],
        ))


@pytest.fixture
def smtp(monkeypatch):
    transport = MagicMock()
    transport.__enter__.return_value = transport
    monkeypatch.setattr("zylch.email.imap_client.smtplib.SMTP", lambda *a, **k: transport)
    return transport


def send(client=None, **values):
    values = {**payload(), **values}
    values.pop("owner_id")
    values.pop("thread_id")
    values["references"] = " ".join(values["references"])
    return (client or IMAPClient("alice@example.test", "fixture")).send_message(**values)


def test_actual_smtp_normal_and_unscoped_assigned_refusal(env, mail, smtp):
    assert send()["status"] == "sent"
    assert smtp.sendmail.call_count == 1
    assign(env)
    with pytest.raises(AssignmentError):
        send()
    assert smtp.sendmail.call_count == 1


def test_pre_assignment_draft_cannot_send_or_edit_after_assignment(env, mail):
    from zylch.tools.gmail_tools import SendDraftTool
    from zylch.tools.base import ToolStatus

    storage = Storage.get_instance()
    draft = storage.create_draft(**payload())
    assign(env)
    with pytest.raises(AssignmentError):
        storage.update_draft("alice@example.test", draft["id"], {"body": "Changed"})
    with pytest.raises(AssignmentError):
        storage.update_draft("alice@example.test", draft["id"], {"in_reply_to": None})
    transport = MagicMock()
    answer = asyncio.run(SendDraftTool(transport, storage, "alice@example.test").execute(draft_id=draft["id"]))
    assert answer.status == ToolStatus.ERROR
    transport.send_message.assert_not_called()
    stored = storage.get_draft("alice@example.test", draft["id"])
    assert stored["body"] == draft["body"] and stored["status"] == "draft"


def test_never_enabled_local_reply_create_update_send_without_host_trust(env, mail, smtp):
    make_unmanaged(env)
    storage = Storage.get_instance()
    draft = storage.create_draft(**payload())
    assert storage.update_draft("alice@example.test", draft["id"], {"body": "Changed"})["body"] == "Changed"
    assert send()["status"] == "sent"
    assert smtp.sendmail.call_count == 1


def test_managed_empty_missing_trust_and_unknown_source_hold_all_effects(env, mail, smtp):
    env.trust_file.unlink()
    storage = Storage.get_instance()
    for action in (lambda: storage.create_draft(**payload()), send):
        with pytest.raises((AssignmentError, FileNotFoundError)):
            action()
    assert count() == 0 and smtp.sendmail.call_count == 0


def test_known_source_conflict_and_foreign_owner_refuse(env, mail, smtp):
    for overrides in ({"references": ["<wrong@example.test>"]},
                      {"references": [ROOT, "<foreign-tail@example.test>"]},
                      {"in_reply_to": "<missing@example.test>"},
                      {"thread_id": "<wrong@example.test>"}):
        with pytest.raises(AssignmentError):
            Storage.get_instance().create_draft(**{**payload(), **overrides})
    with pytest.raises(AssignmentError):
        policy.send(lambda **kw: pytest.fail("transport reached"), owner_id="bob@example.test", **payload_without_owner())
    assert count() == 0


def payload_without_owner():
    return {k: v for k, v in payload().items() if k != "owner_id"}


def test_standalone_and_other_exact_thread_remain_independent(env, mail, smtp):
    assign(env)
    standalone = dict(owner_id="alice@example.test", to="customer@example.test", subject="New", body="Standalone")
    assert Storage.get_instance().create_draft(**standalone)["created"]
    second = "<independent@example.test>"
    mail.add(second, "customer@example.test", "alice@example.test")
    assert Storage.get_instance().create_draft(**{**payload(second), "in_reply_to": second, "references": [second]})["created"]
    assert IMAPClient("alice@example.test", "fixture").send_message(to="customer@example.test", subject="New", body="Standalone")["status"] == "sent"


def test_source_binding_cannot_be_stripped_by_nested_transport(env, mail):
    with policy.effect("alice@example.test", payload()):
        with pytest.raises(AssignmentError):
            policy.send(lambda **kw: pytest.fail("wire reached"), owner_id="alice@example.test", to="customer@example.test", body="body")


@pytest.mark.parametrize("managed", [True, False])
def test_actual_smtp_handoff_holds_company_lock_against_assignment_or_enrollment(env, mail, smtp, managed):
    if not managed:
        make_unmanaged(env)
    outcomes = []

    def wire(*args):
        def competing_authority():
            conn = sqlite3.connect(env.memory.url.database, timeout=0.05)
            try:
                conn.execute("UPDATE assignment_enrollment SET state='managed' WHERE id=1")
                conn.commit()
                outcomes.append("unexpected authority change")
            except sqlite3.OperationalError as error:
                outcomes.append(str(error))
            finally:
                conn.close()
        worker = threading.Thread(target=competing_authority)
        worker.start()
        worker.join(2)
        assert not worker.is_alive()
        assert outcomes == ["database is locked"]

    smtp.sendmail.side_effect = wire
    assert send()["status"] == "sent"
    with env.memory.begin() as conn:
        enrollment.enroll_locked(conn, env.space)
    assert outcomes == ["database is locked"]


def test_enrollment_wins_before_final_admission(env, mail, smtp, monkeypatch):
    make_unmanaged(env)
    original_connection = project_store.connection
    from contextlib import contextmanager

    @contextmanager
    def activate_before_lock(expected_space=None, write=False):
        if write:
            with env.memory.begin() as conn:
                enrollment.enroll_locked(conn, env.space)
        with original_connection(expected_space, write) as value:
            yield value

    monkeypatch.setattr(project_store, "connection", activate_before_lock)
    with pytest.raises(AssignmentError):
        send()
    smtp.sendmail.assert_not_called()


def test_slash_and_solve_actual_transport_routes_hold_assigned_reply(env, mail, smtp, monkeypatch):
    from zylch.api import token_storage
    from zylch.services.command_handlers import handle_email
    from zylch.services.solve_tools import _send_email

    storage = Storage.get_instance()
    draft = storage.create_draft(**payload())
    assign(env)
    monkeypatch.setattr(token_storage, "get_provider", lambda owner: "imap")
    monkeypatch.setattr(token_storage, "get_email", lambda owner: "alice@example.test")
    monkeypatch.setenv("EMAIL_PASSWORD", "fixture-only")
    slash = asyncio.run(handle_email(["send", draft["id"]], MagicMock(), "alice@example.test"))
    solve = _send_email({"to": "customer@example.test", "subject": "Reply", "body": "body", "in_reply_to": ROOT}, storage, "alice@example.test")
    assert "holds" in slash and "holds" in solve
    assert storage.get_draft("alice@example.test", draft["id"])["status"] == "draft"
    smtp.sendmail.assert_not_called()


def test_real_async_tool_to_smtp_handoff_serializes_assignment_and_keeps_sent_claim(env, mail, smtp):
    from zylch.tools.gmail_tools import SendDraftTool
    from zylch.tools.base import ToolStatus

    storage = Storage.get_instance()
    draft = storage.create_draft(**payload())
    observations = []

    def wire(*args):
        observations.append(storage.get_draft("alice@example.test", draft["id"])["status"])
        def assignment():
            connection = sqlite3.connect(env.memory.url.database, timeout=0.05)
            try:
                connection.execute("UPDATE project_space SET space_id=space_id WHERE id=1")
                connection.commit()
                observations.append("unexpected competing commit")
            except sqlite3.OperationalError as error:
                observations.append(str(error))
            finally:
                connection.close()
        competing = threading.Thread(target=assignment)
        competing.start()
        competing.join(2)
        assert not competing.is_alive()

    smtp.sendmail.side_effect = wire
    client = IMAPClient("alice@example.test", "fixture-only")
    answer = asyncio.run(SendDraftTool(client, storage, "alice@example.test").execute(draft_id=draft["id"]))
    assert answer.status == ToolStatus.SUCCESS
    assert observations == ["sending", "database is locked"]
    assert storage.get_draft("alice@example.test", draft["id"])["status"] == "sent"
    again = asyncio.run(SendDraftTool(client, storage, "alice@example.test").execute(draft_id=draft["id"]))
    assert again.status == ToolStatus.ERROR and smtp.sendmail.call_count == 1


@pytest.mark.parametrize("uncertain", [False, True])
def test_contextual_transport_failures_preserve_correct_claim_and_managed_latch(env, mail, smtp, uncertain):
    import smtplib
    from zylch.tools.gmail_tools import SendDraftTool
    from zylch.tools.base import ToolStatus

    storage = Storage.get_instance()
    draft = storage.create_draft(**payload())
    smtp.sendmail.side_effect = smtplib.SMTPServerDisconnected("unknown delivery") if uncertain else smtplib.SMTPRecipientsRefused({"customer@example.test": (550, b"refused")})
    answer = asyncio.run(SendDraftTool(IMAPClient("alice@example.test", "fixture"), storage, "alice@example.test").execute(draft_id=draft["id"]))
    assert answer.status == ToolStatus.ERROR
    assert storage.get_draft("alice@example.test", draft["id"])["status"] == ("sending" if uncertain else "draft")
    with env.memory.connect() as conn:
        assert enrollment.read(conn, env.space)["state"] == "managed"


def test_closed_coverage_cannot_reply_old_target_after_new_inbound(env, mail, smtp):
    from test_evidence_rpc import result

    _, _, assigned = assign(env)
    intent = result("preview", operation="close", thread_key=ROOT, expected_revision=1,
                    task_id=assigned["task_id"], reason="Handled", handled_ref="handled")
    result("commit", intent=intent, grant=env.sign(intent))
    later = "<later-inbound@example.test>"
    mail.add(later, "customer@example.test", "alice@example.test", reply=ROOT)
    with pytest.raises(AssignmentError):
        send()
    assert send(in_reply_to=later)["status"] == "sent"
    assert smtp.sendmail.call_count == 1


def test_candidate_and_incomplete_provider_refuse_unscoped_actual_draft(env, mail, smtp):
    from zylch.storage import database as db
    from zylch.storage.models import Email
    from mail_fixture import REPLY

    mail.add(REPLY, "alice@example.test", "customer@example.test", folder='"Sent"', reply=ROOT)
    with pytest.raises(AssignmentError):
        Storage.get_instance().create_draft(**payload())
    mail.fail_search = True
    with pytest.raises(AssignmentError):
        send()
    assert count() == 0 and smtp.sendmail.call_count == 0


def test_persisted_draft_source_binding_refuses_replaced_original_row(env, mail):
    from zylch.storage import database as db
    from zylch.storage.models import Email

    storage = Storage.get_instance()
    draft = storage.create_draft(**payload())
    assert draft["reply_binding"]["source"]["id"] == mail.root_id
    with db.get_session() as session:
        source = session.query(Email).filter_by(id=mail.root_id).one()
        source.id = "replacement-original-source"
    with pytest.raises(AssignmentError, match="Persisted original"):
        policy.send(lambda **kw: pytest.fail("provider reached"), owner_id="alice@example.test", draft=draft, to="customer@example.test", body="body", in_reply_to=ROOT)


def test_standalone_draft_bound_by_update_persists_original_source(env, mail):
    storage = Storage.get_instance()
    draft = storage.create_draft(owner_id="alice@example.test", to="customer@example.test", subject="New", body="body")
    updated = storage.update_draft("alice@example.test", draft["id"], {
        "thread_id": ROOT, "in_reply_to": ROOT, "references": [ROOT],
    })
    assert updated["reply_binding"]["source"]["id"] == mail.root_id
    with pytest.raises(AssignmentError):
        storage.update_draft("alice@example.test", draft["id"], {"reply_binding": None})
