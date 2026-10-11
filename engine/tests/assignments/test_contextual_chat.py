"""Real generic dispatch, tools and SMTP preserve restrictive original source."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from test_draft_policy import mail, payload, count
from test_email_effect import smtp
from test_evidence_rpc import assign
from mail_fixture import ROOT
from zylch.services import contextual_email_policy as policy
from zylch.services.task_assignment_types import AssignmentError
from zylch.storage.storage import Storage

OWNER = "alice@example.test"


@pytest.fixture
def generic(monkeypatch):
    from zylch.services.chat_service import ChatService
    from zylch.tools.factory import ToolFactory

    monkeypatch.setattr(ToolFactory, "_session_state", None)
    monkeypatch.setattr(ChatService, "_check_auto_sync", lambda self, owner, banner: banner)
    monkeypatch.setattr(ChatService, "_match_semantic_command", lambda *args: None)
    def install(action):
        class Agent:
            tools = []
            last_truncations = []
            def clear_history(self):
                pass
            async def process_message(self, **kwargs):
                return await action(kwargs)
        async def initialize(self, owner_id=None):
            self.agent = Agent()
        monkeypatch.setattr(ChatService, "_initialize_agent", initialize)
    return install


async def dispatch(message="Reply", *, email_context=None, context=None, approve=False):
    from zylch.rpc.dispatch import dispatch_raw
    from zylch.rpc import methods

    notifications = []
    def notify(method, params):
        notifications.append((method, params))
        if method == "chat.pending_approval":
            asyncio.create_task(methods.chat_approve({"tool_use_id": params["tool_use_id"],
                                                     "mode": "once" if approve else "deny"}, lambda *args: None))
    params = {"message": message, "conversation_id": "contextual-fixture"}
    if email_context is not None:
        params.update(email_context=email_context, contextual_email_policy_version=1)
    if context is not None:
        params["context"] = context
    result = await dispatch_raw(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "chat.send", "params": params}), notify)
    assert "error" not in result, result
    return result, notifications


@pytest.mark.parametrize("held,stripped", [(False, False), (False, True), (True, False), (True, True)])
def test_generic_dispatch_actual_create_tool_with_omitted_old_scope(env, mail, generic, held, stripped):
    from zylch.assistant.core import ZylchAIAgent
    from zylch.tools.gmail_tools import CreateDraftTool
    from zylch.tools.base import ToolStatus

    if held:
        assign(env)
    real = object.__new__(ZylchAIAgent)
    real.tool_map = {"create_draft": CreateDraftTool(Storage.get_instance(), OWNER)}
    results = []
    async def action(kwargs):
        assert policy.current().root == ROOT
        arguments = {k: v for k, v in payload().items() if k != "owner_id"}
        if stripped:
            for key in ("thread_id", "in_reply_to", "references"):
                arguments.pop(key)
        results.append(await real._call_tool("create_draft", arguments))
        return "checked"
    generic(action)
    asyncio.run(dispatch(email_context={"thread_key": ROOT, "source_email_id": mail.root_id}))
    success = not held and not stripped
    assert results[0].status == (ToolStatus.SUCCESS if success else ToolStatus.ERROR)
    assert count() == int(success) and policy.current() is None


@pytest.mark.parametrize("held,standalone", [(False, False), (True, False), (False, True)])
def test_generic_dispatch_actual_send_approval_does_not_override_hold(env, mail, smtp, generic, held, standalone):
    from zylch.assistant.core import ZylchAIAgent
    from zylch.tools.gmail_tools import SendDraftTool
    from zylch.email.imap_client import IMAPClient
    from zylch.tools.base import ToolStatus

    storage = Storage.get_instance()
    arguments = payload()
    if standalone:
        for key in ("thread_id", "in_reply_to", "references"):
            arguments.pop(key)
    row = storage.create_draft(**arguments)
    if held:
        assign(env)
    real = object.__new__(ZylchAIAgent)
    real.tool_map = {"send_draft": SendDraftTool(IMAPClient(OWNER, "fixture"), storage, OWNER)}
    results = []
    async def action(kwargs):
        approved, edits = await kwargs["approval_callback"]("send-fixture", "send_draft", {"draft_id": row["id"]})
        assert approved is True
        results.append(await real._call_tool("send_draft", {"draft_id": row["id"]}))
        return "checked"
    generic(action)
    _, notifications = asyncio.run(dispatch(email_context={"draft_id": row["id"]}, approve=True))
    assert any(method == "chat.pending_approval" for method, _ in notifications)
    assert results[0].status == (ToolStatus.ERROR if held else ToolStatus.SUCCESS)
    assert smtp.sendmail.call_count == int(not held)
    assert storage.get_draft(OWNER, row["id"])["status"] == ("draft" if held else "sent")


def test_generic_contextual_slash_send_retains_binding(env, mail, smtp, generic, monkeypatch):
    from zylch.api import token_storage

    storage = Storage.get_instance()
    row = storage.create_draft(**payload())
    assign(env)
    monkeypatch.setattr(token_storage, "get_provider", lambda owner: "imap")
    monkeypatch.setattr(token_storage, "get_email", lambda owner: OWNER)
    monkeypatch.setenv("EMAIL_PASSWORD", "fixture")
    answer, notifications = asyncio.run(dispatch("/email send " + row["id"],
                                                  email_context={"draft_id": row["id"]}, approve=True))
    assert smtp.sendmail.call_count == 0
    assert storage.get_draft(OWNER, row["id"])["status"] == "draft"
    assert "holds" in json.dumps(answer).lower()


def task(storage):
    storage.store_task_item(owner_id=OWNER, item={
        "event_type": "email", "event_id": ROOT, "contact_email": "customer@example.test",
        "title": "Reply", "action_required": True, "sources": {"emails": [ROOT]},
    })
    return storage.get_task_by_event(OWNER, "email", ROOT)


@pytest.mark.parametrize("route", ["create", "update", "deferred"])
def test_task_context_cannot_strip_headers_across_generic_routing(env, mail, generic, route):
    storage = Storage.get_instance()
    row = task(storage)
    independent = storage.create_draft(owner_id=OWNER, to="customer@example.test", subject="New", body="body")
    seen = []
    async def action(kwargs):
        assert policy.current().root == ROOT
        def effect():
            seen.append(policy.current().root)
            with pytest.raises(AssignmentError, match="cannot become standalone"):
                if route == "update":
                    storage.update_draft(OWNER, independent["id"], {"body": "reply without headers"})
                else:
                    storage.create_draft(owner_id=OWNER, to="customer@example.test", subject="reply", body="stripped")
        if route == "deferred":
            await asyncio.create_task(asyncio.to_thread(effect))
        else:
            await asyncio.to_thread(effect)
        return "checked"
    generic(action)
    asyncio.run(dispatch(context={"task_id": row["id"]}))
    assert seen == [ROOT] and count() == 1
    assert storage.get_draft(OWNER, independent["id"])["body"] == "body"


@pytest.mark.parametrize("stripped", [True, False])
def test_task_executor_worker_keeps_context_when_send_arguments_strip_source(env, mail, smtp, stripped):
    from zylch.services.task_executor import TaskExecutor

    storage = Storage.get_instance()
    row = task(storage)
    seen = []
    class Client:
        def create_message_sync(self, **kwargs):
            seen.append(policy.current().root)
            if len(seen) == 1:
                return SimpleNamespace(content=[SimpleNamespace(type="tool_use", id="send", name="send_email",
                    input={"to": "customer@example.test", "subject": "Reply", "body": "reply",
                           **({} if stripped else {"in_reply_to": ROOT})})], stop_reason="tool_use")
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="done")], stop_reason="end_turn")
    async def run():
        executor = TaskExecutor(Client(), "fixture", [], storage, OWNER, [], email_task=row)
        events = []
        async for event in executor.run():
            events.append(event)
            if event["type"] == "tool_call_pending":
                await executor.approve(event["tool_use_id"], True)
        return events
    events = asyncio.run(run())
    assert seen == [ROOT, ROOT]
    assert smtp.sendmail.call_count == int(not stripped)
    assert any(("cannot become standalone" if stripped else "Email sent") in str(event) for event in events)
    assert policy.current() is None


def test_all_explicit_source_identities_must_agree(env, mail):
    other = mail.add("<other@example.test>", "other@example.test", OWNER)
    for context in ({"thread_key": "<other@example.test>", "source_email_id": mail.root_id},
                    {"draft_id": "missing"}, {"target_message_id": "<missing@example.test>"},
                    {"source_email_id": mail.root_id, "target_message_id": "<other@example.test>"}):
        with pytest.raises(AssignmentError):
            policy.source_binding(OWNER, context)
    with pytest.raises(AssignmentError):
        policy.source_binding("bob@example.test", {"source_email_id": mail.root_id})


@pytest.mark.parametrize("conflicting", [False, True])
def test_multi_message_task_restricts_to_actual_sources_without_losing_normal_thread(env, mail, conflicting):
    other = "<second-source@example.test>"
    unrelated = "<unrelated-current@example.test>"
    mail.add(other, "customer@example.test", OWNER, reply=None if conflicting else ROOT)
    mail.add(unrelated, "customer@example.test", OWNER, reply=ROOT)
    row = {"event_type": "email", "event_id": ROOT, "sources": {"emails": [ROOT, other]}}
    binding = policy.from_task(OWNER, row)
    storage = Storage.get_instance()
    if conflicting:
        assert binding.unavailable
        with policy.scope(binding), pytest.raises(AssignmentError):
            storage.create_draft(**payload())
        return
    assert not binding.unavailable and binding.root == ROOT and len(binding.sources) == 2
    with policy.scope(binding):
        assert storage.create_draft(**payload())["created"]
        assert storage.create_draft(**{**payload(), "in_reply_to": other})["created"]
        with pytest.raises(AssignmentError, match="original task source"):
            storage.create_draft(**{**payload(), "in_reply_to": unrelated})
        with pytest.raises(AssignmentError, match="cannot become standalone"):
            storage.create_draft(owner_id=OWNER, to="customer@example.test", subject="reply", body="stripped")
    exact = policy.source_binding(OWNER, {"target_message_id": other})
    with policy.scope(binding), policy.scope(exact):
        assert policy.current().target == other
        with pytest.raises(AssignmentError):
            storage.create_draft(**payload())


def test_bound_turn_cannot_erase_context_dictionary_or_cross_into_other_original(env, mail, generic):
    storage = Storage.get_instance()
    async def action(kwargs):
        kwargs["context"].clear()
        with pytest.raises(AssignmentError, match="cannot become standalone"):
            await asyncio.to_thread(storage.create_draft, owner_id=OWNER, to="customer@example.test", subject="new", body="stripped")
        return "checked"
    generic(action)
    asyncio.run(dispatch(context={"email_id": mail.root_id}))
    assert count() == 0


def test_exact_standalone_draft_cannot_be_combined_with_reply_source(env, mail):
    row = Storage.get_instance().create_draft(owner_id=OWNER, to="customer@example.test", subject="new", body="body")
    with pytest.raises(AssignmentError, match="Standalone draft disagrees"):
        policy.source_binding(OWNER, {"draft_id": row["id"], "target_message_id": ROOT})


def test_task_executor_early_break_does_not_leave_source_in_caller_context(env, mail):
    from zylch.services.task_executor import TaskExecutor
    storage = Storage.get_instance()
    row = task(storage)
    class Client:
        def create_message_sync(self, **kwargs):
            assert policy.current().root == ROOT
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="done")], stop_reason="end_turn")
    async def run():
        executor = TaskExecutor(Client(), "fixture", [], storage, OWNER, [], email_task=row)
        stream = executor.run()
        async for event in stream:
            assert policy.current() is None
            break
        assert policy.current() is None
        await stream.aclose()
        assert policy.current() is None
    asyncio.run(run())
