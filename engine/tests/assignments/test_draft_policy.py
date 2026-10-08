"""Scoped chat cannot write a draft for another or newly assigned thread."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from mail_fixture import MailFixture, ROOT
from test_evidence_rpc import assign
from zylch.services import task_assignment_draft_policy as policy
from zylch.services.task_assignment_types import AssignmentError
from zylch.storage import database as db
from zylch.storage.models import Draft
from zylch.storage.storage import Storage


@pytest.fixture
def mail(env, monkeypatch):
    value = MailFixture(monkeypatch)
    with db.get_session() as session:
        from zylch.storage.models import Email

        session.query(Email).filter(Email.id == value.reply_id).delete()
    value.messages['"Sent"'].clear()
    return value


def payload(root=ROOT):
    return dict(
        owner_id="alice@example.test",
        to="customer@example.test",
        subject="Reply",
        body="Draft body",
        thread_id=root,
        in_reply_to=root,
        references=[root],
    )


def count():
    with db.get_session() as session:
        return session.query(Draft).count()


def test_write_boundary_exact_thread_and_assignment(env, mail):
    storage = Storage.get_instance()
    with policy.scope(ROOT):
        with pytest.raises(AssignmentError):
            storage.create_draft(**payload("<other@example.test>"))
        assert count() == 0
        draft = storage.create_draft(**payload())
        assert draft["created"] and count() == 1
    assign(env)
    with policy.scope(ROOT), pytest.raises(AssignmentError):
        storage.create_draft(**{**payload(), "body": "Another draft"})
    assert count() == 1
    assert storage.create_draft(**{**payload(), "body": "Ordinary desktop draft"})["created"]
    assert count() == 2


def test_scoped_tools_refuse_send_and_run_python_before_execution(env, mail):
    from zylch.assistant.core import ZylchAIAgent
    from zylch.tools.base import ToolStatus

    agent = object.__new__(ZylchAIAgent)

    async def forbidden(**kwargs):
        raise AssertionError("write effect reached")

    agent.tool_map = {
        name: SimpleNamespace(execute=forbidden)
        for name in ("send_draft", "send_email", "run_python", "update_draft", "compose_email")
    }
    with policy.scope(ROOT):
        for name in agent.tool_map:
            answer = asyncio.run(agent._call_tool(name, {}))
            assert answer.status == ToolStatus.ERROR and "guarded draft" in answer.error
    assert count() == 0


def test_context_propagates_rpc_chat_to_actual_tool_worker(env, mail, monkeypatch):
    from zylch.services.chat_service import ChatService
    from zylch.assistant.core import ZylchAIAgent
    from zylch.tools.gmail_tools import CreateDraftTool
    from zylch.tools.base import ToolStatus

    storage = Storage.get_instance()
    real_agent = object.__new__(ZylchAIAgent)
    real_agent.tool_map = {"create_draft": CreateDraftTool(storage, "alice@example.test")}
    seen = []

    class Agent:
        def clear_history(self):
            pass

        async def process_message(self, **kwargs):
            seen.append(policy.current())
            result = await real_agent._call_tool(
                "create_draft",
                {
                    key: value
                    for key, value in payload("<wrong-model-thread@example.test>").items()
                    if key != "owner_id"
                },
            )
            assert result.status == ToolStatus.ERROR
            return "Draft refused"

    async def initialize(self, owner_id=None):
        self.agent = Agent()

    monkeypatch.setattr(ChatService, "_initialize_agent", initialize)
    monkeypatch.setattr(
        ChatService, "_check_auto_sync", lambda *a: pytest.fail("scoped auto-sync reached")
    )
    monkeypatch.setattr(
        ChatService,
        "_match_semantic_command",
        lambda *a: pytest.fail("scoped command routing reached"),
    )
    from zylch.rpc.dispatch import dispatch_raw

    answer = asyncio.run(
        dispatch_raw(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "chat.send",
                    "params": {
                        "message": "Draft a reply",
                        "assignment_thread_key": ROOT,
                        "assignment_policy_version": 1,
                    },
                }
            ),
            lambda *a: None,
        )
    )
    assert "error" not in answer, answer
    assert seen == [ROOT] and count() == 0 and policy.current() is None


def test_read_only_direct_guard_refuses_and_unknown_scope_holds(env, mail):
    from zylch.services.request_policy import policy_scope, READ_ONLY_POLICY, ReadOnlyViolation

    storage = Storage.get_instance()
    with policy.scope(ROOT), policy_scope(READ_ONLY_POLICY), pytest.raises(ReadOnlyViolation):
        storage.create_draft(**payload())
    mail.fail_search = True
    with policy.scope(ROOT), pytest.raises(AssignmentError):
        storage.create_draft(**payload())
    assert count() == 0


def test_company_writer_lock_covers_actual_private_draft_insert(env, mail, monkeypatch):
    import sqlite3
    import threading
    from sqlalchemy import event

    attempts = []

    def before_insert(conn, cursor, statement, parameters, context, executemany):
        if not statement.startswith("INSERT INTO drafts"):
            return

        def competing_assignment():
            connection = sqlite3.connect(env.memory.url.database, timeout=0.05)
            try:
                connection.execute("UPDATE project_space SET space_id=space_id WHERE id=1")
                connection.commit()
                attempts.append("unexpected assignment write")
            except sqlite3.OperationalError as error:
                attempts.append(str(error))
            finally:
                connection.close()

        worker = threading.Thread(target=competing_assignment)
        worker.start()
        worker.join(2)
        assert not worker.is_alive() and attempts == ["database is locked"]

    private = db.get_engine()
    event.listen(private, "before_cursor_execute", before_insert)
    try:
        with policy.scope(ROOT):
            assert Storage.get_instance().create_draft(**payload())["created"]
    finally:
        event.remove(private, "before_cursor_execute", before_insert)
    assert count() == 1
    with sqlite3.connect(env.memory.url.database, timeout=0.05) as connection:
        connection.execute("UPDATE project_space SET space_id=space_id WHERE id=1")
