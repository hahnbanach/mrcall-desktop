"""Reviewer-proven interleavings now refuse at authoritative private CAS."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from test_draft_policy import mail
from test_evidence_rpc import assign
from mail_fixture import ROOT
from zylch.storage.storage import Storage
from zylch.services import task_assignment_email_effect as effects
from zylch.services.task_assignment_types import AssignmentError
from zylch.email.imap_client import IMAPClient

OWNER = "alice@example.test"


def draft(storage):
    return storage.create_draft(owner_id=OWNER, to="customer@example.test", subject="New", body="body")


def bind_and_assign(storage, draft_id, env):
    storage.update_draft(OWNER, draft_id, {"thread_id": ROOT, "in_reply_to": ROOT, "references": [ROOT]})
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(copy_context().run, assign, env).result()


@pytest.fixture
def smtp(monkeypatch):
    value = MagicMock()
    value.__enter__.return_value = value
    monkeypatch.setattr("zylch.email.imap_client.smtplib.SMTP", lambda *a, **k: value)
    return value


@pytest.mark.parametrize("updates", [{"thread_id": None, "in_reply_to": None, "references": [], "reply_binding": None, "body": "changed while assigned"}, {"reply_binding": None}, {"error_message": "stale metadata"}])
def test_stale_unbound_update_cannot_clear_concurrently_bound_assigned_reply(env, mail, monkeypatch, updates):
    storage = Storage.get_instance()
    row = draft(storage)
    original = storage.get_draft
    interleavings = []

    def interleave(owner_id, draft_id):
        snapshot = original(owner_id, draft_id)
        if not interleavings:
            interleavings.append("bind-then-assign")
            bind_and_assign(storage, draft_id, env)
        return snapshot

    monkeypatch.setattr(storage, "get_draft", interleave)
    with pytest.raises(AssignmentError, match="draft changed"):
        storage.update_draft(OWNER, row["id"], updates)
    authoritative = original(OWNER, row["id"])
    assert authoritative["reply_binding"] is not None and authoritative["in_reply_to"] == ROOT
    assert authoritative["body"] == "body"
    calls = []
    with pytest.raises(AssignmentError):
        effects.send(lambda **kw: calls.append(kw), owner_id=OWNER, draft=authoritative,
                     to="customer@example.test", body=authoritative["body"])
    assert calls == []


@pytest.mark.parametrize("route", ["tool", "slash", "legacy-orchestrator"])
def test_stale_unbound_snapshot_cannot_send_after_concurrent_binding_before_claim(env, mail, smtp, monkeypatch, route):
    from zylch.api import token_storage
    from zylch.tools.gmail_tools import SendDraftTool
    from zylch.tools.base import ToolStatus

    storage = Storage.get_instance()
    row = draft(storage)
    original_claim = Storage.claim_draft_for_send

    def claim_after_binding(self, owner_id, draft_id, provider=None):
        bind_and_assign(storage, draft_id, env)
        return original_claim(self, owner_id, draft_id, provider)

    monkeypatch.setattr(Storage, "claim_draft_for_send", claim_after_binding)
    monkeypatch.setattr(token_storage, "get_provider", lambda owner: "imap")
    monkeypatch.setattr(token_storage, "get_email", lambda owner: OWNER)
    monkeypatch.setenv("EMAIL_PASSWORD", "fixture-only")
    if route == "tool":
        answer = asyncio.run(SendDraftTool(IMAPClient(OWNER, "fixture"), storage, OWNER).execute(draft_id=row["id"]))
        assert answer.status == ToolStatus.ERROR and "draft changed" in answer.error
    elif route == "slash":
        from zylch.services.command_handlers import handle_email
        answer = asyncio.run(handle_email(["send", row["id"]], MagicMock(), OWNER))
        assert "draft changed" in answer
    else:
        import sys
        from types import ModuleType
        from zylch.agents import task_orchestrator_agent as module
        from zylch.services.approval_gate import APPROVED

        monkeypatch.setattr(token_storage, "get_provider", lambda owner: "google")
        adapter = ModuleType("zylch.tools.gmail")
        adapter.GmailClient = lambda **kw: IMAPClient(OWNER, "fixture")
        monkeypatch.setitem(sys.modules, "zylch.tools.gmail", adapter)
        async def approved(*args):
            return APPROVED, {}
        monkeypatch.setattr(module, "request_approval", approved)
        agent = object.__new__(module.TaskOrchestratorAgent)
        agent.owner_id, agent.storage, agent.approval_callback = OWNER, storage, None
        agent.session_state = SimpleNamespace(get_last_action_result=lambda: {
            "tool_used": "write_email", "result": {"draft_id": row["id"]},
        })
        answer = asyncio.run(agent._handle_send_email())
        assert "draft changed" in answer
    authoritative = storage.get_draft(OWNER, row["id"])
    assert authoritative["reply_binding"] is not None and authoritative["status"] == "draft"
    smtp.sendmail.assert_not_called()


def test_claimed_standalone_cannot_convert_during_actual_smtp_handoff(env, mail, smtp):
    from zylch.tools.gmail_tools import SendDraftTool
    from zylch.tools.base import ToolStatus

    storage = Storage.get_instance()
    row = draft(storage)
    attempts = []
    def wire(*args):
        def convert():
            with pytest.raises(AssignmentError, match="Claimed"):
                storage.update_draft(OWNER, row["id"], {"thread_id": ROOT, "in_reply_to": ROOT, "references": [ROOT]})
            attempts.append("conversion refused")
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(copy_context().run, convert).result()
    smtp.sendmail.side_effect = wire
    answer = asyncio.run(SendDraftTool(IMAPClient(OWNER, "fixture"), storage, OWNER).execute(draft_id=row["id"]))
    assert answer.status == ToolStatus.SUCCESS and attempts == ["conversion refused"]
    authoritative = storage.get_draft(OWNER, row["id"])
    assert authoritative["status"] == "sent" and authoritative["reply_binding"] is None
    assert smtp.sendmail.call_count == 1


def test_standalone_transport_retains_private_writer_until_acceptance(env, mail, smtp):
    from sqlalchemy import update
    from sqlalchemy.exc import OperationalError
    from zylch.storage import database
    from zylch.storage.models import Draft
    from zylch.tools.gmail_tools import SendDraftTool
    from zylch.tools.base import ToolStatus

    storage = Storage.get_instance()
    row = draft(storage)
    def wire(*args):
        with database.get_engine().connect() as contender:
            contender.exec_driver_sql("PRAGMA busy_timeout=20")
            contender.commit()
            with pytest.raises(OperationalError, match="locked"):
                contender.execute(update(Draft).where(Draft.id == row["id"]).values(body="concurrent replacement"))
            contender.rollback()
    smtp.sendmail.side_effect = wire
    answer = asyncio.run(SendDraftTool(IMAPClient(OWNER, "fixture"), storage, OWNER).execute(draft_id=row["id"]))
    assert answer.status == ToolStatus.SUCCESS
    assert storage.get_draft(OWNER, row["id"])["body"] == "body"
    smtp.sendmail.assert_called_once()


def test_create_reuse_reserves_private_writer_before_candidate_read(env, mail):
    from sqlalchemy import event, update
    from sqlalchemy.exc import OperationalError
    from zylch.storage import database
    from zylch.storage.models import Draft

    storage = Storage.get_instance()
    row = draft(storage)
    engine = database.get_engine()
    attempts = []
    def before_read(conn, cursor, statement, parameters, context, executemany):
        if "FROM drafts" not in statement or attempts:
            return
        attempts.append("candidate read")
        with engine.connect() as contender:
            contender.exec_driver_sql("PRAGMA busy_timeout=20")
            contender.commit()
            with pytest.raises(OperationalError, match="locked"):
                contender.execute(update(Draft).where(Draft.id == row["id"]).values(in_reply_to=ROOT))
            contender.rollback()
    event.listen(engine, "before_cursor_execute", before_read)
    try:
        reused = draft(storage)
    finally:
        event.remove(engine, "before_cursor_execute", before_read)
    assert attempts == ["candidate read"]
    assert reused["id"] == row["id"] and reused["created"] is False
    assert reused["in_reply_to"] is None and reused["reply_binding"] is None
