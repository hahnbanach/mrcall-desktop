"""Public caller integration: one provider object, native edits and durable replay."""
import asyncio
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace
import pytest
from mail_fixture import ROOT
from test_draft_policy import mail as mail_fixture
from test_operator_mcp_prepare import Port, Verifier, SCOPES
from zylch.operator_mcp.effects import GrantedEffects
from zylch.services import operator_reply_generation as generation
from zylch.services.mailbox_draft_mime import build
from zylch.storage import database as db
from zylch.storage.models import Draft
from zylch.storage.storage import Storage
OWNER = "alice@example.test"


def parsed(raw):
    return BytesParser(policy=policy.default).parsebytes(raw)


class NativeMailbox:
    """Provider boundary with stable native IDs and editable saved RFC messages."""
    drafts, delivered, trash, creates, transmissions = {}, [], {}, 0, 0
    def __init__(self, owner):
        assert owner == OWNER
    def close(self):
        pass
    def list_drafts(self):
        return list(self.drafts.values())
    def get_draft(self, identifier):
        return self.drafts.get(identifier)
    def find_drafts(self, message_id):
        return [row for row in self.drafts.values() if str(parsed(row["raw"])["Message-ID"]) == message_id]
    def thread_for_message(self, target):
        return "native-thread"
    def create_draft(self, raw, thread_id=None):
        type(self).creates += 1
        identifier = "draft-" + str(self.creates)
        self.drafts[identifier] = {"id": identifier, "message_id": "message-" + identifier,
            "thread_id": thread_id or "native-thread", "raw": raw}
        return self.drafts[identifier]
    def update_draft(self, identifier, raw, **kwargs):
        self.drafts[identifier]["raw"] = raw
        return self.drafts[identifier]
    def send_draft(self, identifier, raw):
        assert identifier in self.drafts
        type(self).transmissions += 1
        self.delivered.append(raw)
        self.drafts.pop(identifier)
        return {"id": "sent-message"}
    def sent(self, message_id):
        return [{"message_id": "sent-message", "raw": raw, "labels": ["SENT"]}
            for raw in self.delivered if str(parsed(raw)["Message-ID"]) == message_id]
    def trash_draft(self, identifier):
        row = self.drafts.pop(identifier)
        self.trash[identifier] = row
        return {"id": row["message_id"], "labels": ["TRASH"]}


@pytest.fixture
def journey(env, monkeypatch):
    mail = mail_fixture.__wrapped__(env, monkeypatch)
    NativeMailbox.drafts, NativeMailbox.delivered, NativeMailbox.trash = {}, [], {}
    NativeMailbox.creates = NativeMailbox.transmissions = 0
    monkeypatch.setattr("zylch.email.gmail_mailbox.GmailMailbox", NativeMailbox)
    calls = []
    async def generate(context, request):
        calls.append(request)
        return "A synthetic response for review."
    monkeypatch.setattr(generation, "generate", generate)
    effects = GrantedEffects(Verifier(SCOPES, mail.box, env.space), Port(mail.box, env.space))
    return SimpleNamespace(mail=mail, calls=calls, effects=effects)


def prepare(journey):
    return asyncio.run(journey.effects.prepare("token", "mailbox-prepare-key-0001", ROOT,
        journey.mail.root_id, [], "answer kindly"))


def test_mcp_native_edit_send_replay_and_no_private_draft(journey):
    result = prepare(journey)
    draft_id = result["result"]["draft_id"]
    native = next(iter(NativeMailbox.drafts.values()))
    native["raw"] = build(OWNER, to=["edited-recipient@example.test"], subject="Edited subject",
        body="Saved by the person in Gmail.", in_reply_to=ROOT,
        references=[ROOT], message_id="<native-web-save@example.test>")
    outcome = asyncio.run(journey.effects.send("token", "mailbox-send-key-0000001", draft_id))
    assert outcome["ok"] and outcome["state"] == "sent"
    received = parsed(NativeMailbox.delivered[0])
    assert str(received["To"]) == "edited-recipient@example.test"
    assert str(received["Subject"]) == "Edited subject"
    assert received.get_content().strip() == "Saved by the person in Gmail."
    assert str(received["Message-ID"]) == outcome["message_id"]
    again = asyncio.run(journey.effects.send("token", "mailbox-send-key-0000001", draft_id))
    assert again["message_id"] == outcome["message_id"]
    assert NativeMailbox.transmissions == 1 and not NativeMailbox.drafts
    with db.get_session() as session:
        assert session.query(Draft).count() == 0
    replay = prepare(journey)
    assert replay["result"]["draft_id"] == draft_id
    assert replay["current_draft"] == {"exists": False}
    assert len(journey.calls) == 1 and NativeMailbox.creates == 1


def test_mcp_trash_then_prepare_replay_never_recreates(journey):
    result = prepare(journey)
    draft_id = result["result"]["draft_id"]
    outcome = asyncio.run(journey.effects.delete("token", "mailbox-trash-key-00001", draft_id))
    assert outcome["ok"] and NativeMailbox.trash and not NativeMailbox.drafts
    replay = prepare(journey)
    assert replay["current_draft"] == {"exists": False}
    assert NativeMailbox.creates == 1 and NativeMailbox.transmissions == 0


def test_storage_adapter_and_retired_claim_cannot_reach_private_rows(journey):
    store = Storage.get_instance()
    result = store.create_draft(OWNER, ["recipient@example.test"], "Synthetic", "One mailbox draft")
    assert store.get_draft(OWNER, result["id"])["id"] == result["id"]
    assert len(store.list_drafts(OWNER)) == 1
    assert store.claim_draft_for_send(OWNER, result["id"]) is False
    with db.get_session() as session:
        assert session.query(Draft).count() == 0


def publish_instructions(env):
    import base64
    from zylch.services import project_store
    for path, text in (("procedures.md", "Answer synthetic requests using only supplied facts."),
                       ("mail/" + OWNER + ".md", "Use a brief professional voice.")):
        project_store.write(env.space, "operator-instructions", path,
            base64.b64encode(text.encode()).decode(), 0, "fixture")


def test_scheduled_compose_send_has_no_intermediate_draft(env, journey, monkeypatch):
    from zylch.rpc.draft_actions import drafts_compose_reply
    publish_instructions(env)
    raw = next(raw for folder in journey.mail.messages.values() for raw in folder.values()
               if str(parsed(raw)["Message-ID"]) == ROOT)
    def conversation(self, target):
        return [{"message_id": "native-source", "raw": raw, "labels": ["INBOX"]}] + [
            {"message_id": "native-sent", "raw": sent, "labels": ["SENT"]} for sent in self.delivered]
    def direct(self, raw):
        type(self).transmissions += 1
        self.delivered.append(raw)
        return {"message_id": "native-sent"}
    monkeypatch.setattr(NativeMailbox, "conversation", conversation, raising=False)
    monkeypatch.setattr(NativeMailbox, "send_message", direct, raising=False)
    result = asyncio.run(drafts_compose_reply({"source_email_id": journey.mail.root_id,
        "thread_key": ROOT, "request_key": "scheduled-send-key-0001", "mode": "send",
        "operator_origin": "scheduled_operator", "operator_origin_version": 1}, lambda *args: None))
    assert result["ok"] and result["state"] == "sent", result
    assert NativeMailbox.transmissions == 1 and NativeMailbox.creates == 0
    assert not NativeMailbox.drafts and len(journey.calls) == 1
    # Ordinary Sent synchronization still recognizes the engine's own confirmed answer.
    from zylch.email.imap_client import _parse_message_bytes
    monkeypatch.setattr("zylch.storage.storage._generate_email_embedding", lambda email: None)
    synchronized = _parse_message_bytes(NativeMailbox.delivered[0])
    assert synchronized["auto_submitted"] == "auto-replied"
    synchronized.update(id=result["message_id"], message_id_header=result["message_id"],
                        thread_id=ROOT, is_auto_reply=True)
    Storage.get_instance().store_emails_batch(OWNER, [synchronized], mailbox_id=journey.mail.box)
    from zylch.storage.models import Email
    with db.get_session() as session:
        stored = session.query(Email).filter(Email.message_id_header == result["message_id"]).one()
        assert stored.is_auto_reply is False
    # The same request resumes its original send even if archive/source and rules change.
    with db.get_session() as session:
        session.query(Email).filter(Email.id == journey.mail.root_id).delete()
        assert session.query(Draft).count() == 0
    repeated = asyncio.run(drafts_compose_reply({"source_email_id": journey.mail.root_id,
        "thread_key": ROOT, "request_key": "scheduled-send-key-0001", "mode": "send", "recover_only": True,
        "operator_origin": "scheduled_operator", "operator_origin_version": 1}, lambda *args: None))
    assert repeated["state"] == "sent" and repeated["message_id"] == result["message_id"]
    assert NativeMailbox.transmissions == 1 and NativeMailbox.creates == 0 and len(journey.calls) == 1


def test_scheduled_existing_draft_precedes_generation(env, journey, monkeypatch):
    from zylch.rpc.draft_actions import drafts_compose_reply
    publish_instructions(env)
    raw = next(raw for folder in journey.mail.messages.values() for raw in folder.values()
               if str(parsed(raw)["Message-ID"]) == ROOT)
    monkeypatch.setattr(NativeMailbox, "conversation", lambda self, target:
        [{"message_id": "native-source", "raw": raw, "labels": ["INBOX"]}], raising=False)
    Storage.get_instance().create_draft(OWNER, ["recipient@example.test"], "Human draft", "Keep my edit",
        in_reply_to=ROOT, thread_id=ROOT, references=[ROOT])
    for mode in ("draft", "send"):
        result = asyncio.run(drafts_compose_reply({"source_email_id": journey.mail.root_id,
            "thread_key": ROOT, "request_key": "scheduled-existing-key-" + mode, "mode": mode,
            "operator_origin": "scheduled_operator", "operator_origin_version": 1}, lambda *args: None))
        assert result["state"] == "draft_exists", result
    assert NativeMailbox.creates == 1 and NativeMailbox.transmissions == 0 and not journey.calls


def test_missing_native_authorization_is_explicit_not_empty_inventory(env):
    import json
    from zylch.rpc.dispatch import dispatch_raw
    from zylch.services.mailbox_draft_mime import handle
    async def invoke(method, params):
        return await dispatch_raw(json.dumps({"jsonrpc": "2.0", "id": 1,
            "method": method, "params": params}), lambda *args: None)
    listing = asyncio.run(invoke("drafts.list", {}))
    assert listing["error"]["code"] == -32030
    assert "gmail_authorization_required" in listing["error"]["message"]
    reading = asyncio.run(invoke("drafts.get", {"draft_id": handle(OWNER, "native-missing")}))
    assert reading["result"]["ok"] is False
    assert reading["result"]["cause"] == "gmail_authorization_required"


def task_agent(draft_id, approval):
    from zylch.agents.task_orchestrator_agent import TaskOrchestratorAgent
    from zylch.tools.session_state import SessionState
    agent = object.__new__(TaskOrchestratorAgent)
    agent.owner_id, agent.storage, agent.approval_callback = OWNER, Storage.get_instance(), approval
    agent.session_state = SessionState(owner_id=OWNER)
    agent.session_state.set_last_action_result({"tool_used": "write_email", "result": {"draft_id": draft_id}})
    return agent


def ordinary_draft():
    return Storage.get_instance().create_draft(OWNER, ["original@example.test"], "Review", "Original saved text")


def test_actual_task_handler_sends_provider_edits_without_any_legacy_row(journey):
    draft = ordinary_draft()
    async def approve(use_id, tool, card):
        assert tool == "send_email" and card["to"] == "original@example.test"
        row = next(iter(NativeMailbox.drafts.values()))
        row["raw"] = build(OWNER, to=["latest@example.test"], subject="Gmail change", body="Latest saved text")
        return True, dict(card)
    agent = task_agent(draft["id"], approve)
    text = asyncio.run(agent._handle_send_email())
    assert "confirmed in Sent" in text, text
    assert NativeMailbox.transmissions == 1
    received = parsed(NativeMailbox.delivered[0])
    assert str(received["To"]) == "latest@example.test"
    assert received.get_content().strip() == "Latest saved text"
    with db.get_session() as session:
        assert session.query(Draft).count() == 0


def test_task_approval_decline_has_no_provider_effect(journey):
    draft = ordinary_draft()
    async def decline(*args):
        return False, None
    text = asyncio.run(task_agent(draft["id"], decline)._handle_send_email())
    assert "not approved" in text and NativeMailbox.transmissions == 0
    assert len(NativeMailbox.drafts) == 1


def test_task_unconfirmed_send_reuses_original_key_and_never_reapproves(journey, monkeypatch):
    draft = ordinary_draft()
    approvals = []
    async def approve(*args):
        approvals.append(args)
        return True, None
    native_sent = NativeMailbox.sent
    monkeypatch.setattr(NativeMailbox, "sent", lambda self, message_id: [])
    agent = task_agent(draft["id"], approve)
    first = asyncio.run(agent._handle_send_email())
    key = agent.session_state.get_last_action_result()["result"]["send_request_key"]
    assert "unconfirmed" in first and NativeMailbox.transmissions == 1
    monkeypatch.setattr(NativeMailbox, "sent", native_sent)
    replay = asyncio.run(agent._handle_send_email())
    assert "confirmed in Sent" in replay
    assert len(approvals) == 1 and NativeMailbox.transmissions == 1
    assert agent.session_state.get_last_action_result()["result"]["send_request_key"] == key


def test_failed_approval_edits_refuse_both_task_and_slash_sends(journey, monkeypatch):
    from zylch.services.approval_gate import gate_slash_command
    draft = ordinary_draft()
    def unavailable(*args, **kwargs):
        raise RuntimeError("Synthetic provider update failure")
    monkeypatch.setattr(NativeMailbox, "update_draft", unavailable)
    async def approve(use_id, tool, card):
        return True, {**card, "body": "Explicit edited text"}
    text = asyncio.run(task_agent(draft["id"], approve)._handle_send_email())
    assert "failed" in text.lower() and NativeMailbox.transmissions == 0
    refusal = asyncio.run(gate_slash_command("/email", ["send", draft["id"]], OWNER,
                                             approve, Storage.get_instance()))
    assert refusal is not None and "Nothing was sent" in refusal
    assert NativeMailbox.transmissions == 0


@pytest.mark.parametrize("explicit_edit", [False, True])
def test_actual_chat_gate_drops_unchanged_hydrated_fields(journey, monkeypatch, explicit_edit):
    from unittest.mock import MagicMock
    from zylch.assistant.core import ZylchAIAgent
    from zylch.tools.gmail_tools import SendDraftTool
    draft = ordinary_draft()
    monkeypatch.setattr("zylch.assistant.core.make_llm_client", lambda: MagicMock())
    tool = SendDraftTool(None, Storage.get_instance(), OWNER)
    agent = ZylchAIAgent(tools=[tool])
    async def approve(use_id, name, card):
        row = next(iter(NativeMailbox.drafts.values()))
        row["raw"] = build(OWNER, to=["latest@example.test"], subject="Gmail change", body="Latest saved text")
        returned = dict(card)
        if explicit_edit:
            returned["body"] = "Explicit card edit"
        return True, returned
    block = SimpleNamespace(type="tool_use", name="send_draft", input={"draft_id": draft["id"]}, id="synthetic-tool-use")
    asyncio.run(agent._execute_tools([block], approve))
    assert NativeMailbox.transmissions == 1
    received = parsed(NativeMailbox.delivered[0])
    assert str(received["To"]) == "latest@example.test"
    assert received.get_content().strip() == ("Explicit card edit" if explicit_edit else "Latest saved text")


@pytest.mark.parametrize("route", ["task", "chat", "slash"])
def test_new_explicit_attempt_recovers_after_definite_provider_refusal(journey, monkeypatch, route):
    from zylch.email.gmail_auth import GmailError
    from zylch.tools.gmail_tools import SendDraftTool
    from zylch.services.command_handlers import handle_email
    draft = ordinary_draft()
    async def approve(*args):
        return True, None
    task = task_agent(draft["id"], approve)
    tool = SendDraftTool(None, Storage.get_instance(), OWNER)
    def invoke():
        if route == "task":
            return asyncio.run(task._handle_send_email())
        if route == "chat":
            return asyncio.run(tool.execute(draft_id=draft["id"]))
        return asyncio.run(handle_email(["send", draft["id"]], None, OWNER))
    original = NativeMailbox.send_draft
    def denied(*args, **kwargs):
        error = GmailError("gmail_provider_refused", 403)
        error.non_dispatch = True
        raise error
    monkeypatch.setattr(NativeMailbox, "send_draft", denied)
    invoke()
    assert NativeMailbox.transmissions == 0 and len(NativeMailbox.drafts) == 1
    monkeypatch.setattr(NativeMailbox, "send_draft", original)
    invoke()
    assert NativeMailbox.transmissions == 1 and not NativeMailbox.drafts
    invoke()
    assert NativeMailbox.transmissions == 1


@pytest.mark.parametrize("route", ["storage", "slash"])
def test_explicit_delete_retries_definite_refusal_and_preserves_uncertain_operation(journey, monkeypatch, route):
    from zylch.email.gmail_auth import GmailError
    from zylch.services.command_handlers import handle_email
    draft = ordinary_draft()
    mutations = []
    original = NativeMailbox.trash_draft
    def invoke():
        if route == "storage":
            return Storage.get_instance().delete_draft(OWNER, draft["id"])
        return asyncio.run(handle_email(["delete", draft["id"]], None, OWNER))
    def denied(*args, **kwargs):
        error = GmailError("gmail_provider_refused", 403)
        error.non_dispatch = True
        raise error
    monkeypatch.setattr(NativeMailbox, "trash_draft", denied)
    invoke()
    assert len(NativeMailbox.drafts) == 1 and not NativeMailbox.trash
    def lost(self, identifier):
        mutations.append(identifier)
        original(self, identifier)
        raise RuntimeError("Synthetic acknowledgement loss")
    def observed(self, message_id):
        rows = list(self.trash.values())
        row = next((row for row in rows if row["message_id"] == message_id), None)
        return {**row, "labels": ["TRASH"]} if row else None
    monkeypatch.setattr(NativeMailbox, "get_message", observed, raising=False)
    monkeypatch.setattr(NativeMailbox, "trash_draft", lost)
    invoke()
    assert len(mutations) == 1 and not NativeMailbox.drafts
    invoke()
    assert len(mutations) == 1 and NativeMailbox.trash


@pytest.mark.parametrize("creator", ["emailer", "chat", "crm"])
def test_creators_present_the_existing_saved_mailbox_content(journey, creator):
    from zylch.agents.emailer_agent import EmailerAgent
    from zylch.tools.gmail_tools import CreateDraftTool
    from zylch.tools.crm_tools import ComposeEmailTool
    from zylch.tools.session_state import SessionState
    store = Storage.get_instance()
    draft = store.create_draft(OWNER, ["human@example.test"], "Human subject", "Human saved text",
                               in_reply_to=ROOT, references=[ROOT], thread_id=ROOT)
    proposed = {"to": "generated@example.test", "subject": "Regenerated subject", "body": "Unpersisted generated text"}
    if creator == "emailer":
        agent = object.__new__(EmailerAgent)
        agent.owner_id, agent.storage = OWNER, store
        source = store.get_email_by_supabase_id(OWNER, journey.mail.root_id)
        saved = agent._process_write_email(proposed, SimpleNamespace(source_emails=[source]))
        assert saved["draft_id"] == draft["id"] and saved["body"].strip() == "Human saved text"
    elif creator == "chat":
        result = asyncio.run(CreateDraftTool(store, OWNER).execute(**proposed,
            in_reply_to=ROOT, references=[ROOT], thread_id=ROOT))
        assert "Human saved text" in result.message and "Unpersisted generated text" not in result.message
    else:
        tool = ComposeEmailTool(SessionState(owner_id=OWNER))
        async def generated(**kwargs):
            return {**proposed, "recipient_email": proposed["to"],
                    "in_reply_to": ROOT, "references": [ROOT], "thread_id": ROOT}
        tool._agent = SimpleNamespace(compose=generated)
        result = asyncio.run(tool.execute("Synthetic request"))
        assert result.data["draft_id"] == draft["id"] and result.data["body"].strip() == "Human saved text"
    assert NativeMailbox.creates == 1 and NativeMailbox.transmissions == 0


def test_emailer_explicit_modification_updates_same_native_draft_and_surfaces_failure(journey, monkeypatch):
    from zylch.agents.emailer_agent import EmailerAgent
    agent = object.__new__(EmailerAgent)
    agent.owner_id, agent.storage = OWNER, Storage.get_instance()
    draft = ordinary_draft()
    changed = agent._process_write_email({"to": "edited@example.test", "subject": "Changed", "body": "Requested edit"},
        SimpleNamespace(source_emails=[]), existing_draft_id=draft["id"])
    assert changed["draft_id"] == draft["id"] and changed["body"].strip() == "Requested edit"
    assert NativeMailbox.creates == 1
    def failure(*args, **kwargs):
        raise RuntimeError("Synthetic provider failure")
    monkeypatch.setattr(NativeMailbox, "create_draft", failure)
    with pytest.raises(Exception, match="mailbox_provider_unavailable"):
        agent._process_write_email({"to": "new@example.test", "subject": "New", "body": "New body"},
                                  SimpleNamespace(source_emails=[]))
    assert NativeMailbox.creates == 1


def test_recover_only_without_engine_admission_cannot_start_reply(env, journey):
    import json
    from zylch.rpc.dispatch import dispatch_raw
    result = asyncio.run(dispatch_raw(json.dumps({"jsonrpc": "2.0", "id": 7,
        "method": "drafts.compose_reply", "params": {
            "source_email_id": journey.mail.root_id, "thread_key": ROOT,
            "request_key": "local-before-dispatch-crash", "mode": "draft", "recover_only": True,
            "operator_origin": "scheduled_operator", "operator_origin_version": 1}}), lambda *args: None))
    assert result.get("error") and "reply_operation_not_found" in result["error"]["message"], result
    assert NativeMailbox.creates == 0 and NativeMailbox.transmissions == 0 and not journey.calls


def test_interactive_compose_cannot_bypass_named_draft_send(env, journey):
    import json
    from zylch.rpc.dispatch import dispatch_raw
    response = asyncio.run(dispatch_raw(json.dumps({"jsonrpc": "2.0", "id": 8,
        "method": "drafts.compose_reply", "params": {"source_email_id": journey.mail.root_id,
            "thread_key": ROOT, "request_key": "interactive-direct-send-key", "mode": "send"}}), lambda *args: None))
    assert response.get("error") and "scheduled_direct_send_required" in response["error"]["message"], response
    assert NativeMailbox.creates == 0 and NativeMailbox.transmissions == 0 and not journey.calls
    from sqlalchemy import inspect
    with db.get_engine().connect() as conn:
        for table in ("operator_reply_operations", "mailbox_operation_receipts"):
            if inspect(conn).has_table(table):
                assert conn.exec_driver_sql("SELECT COUNT(*) FROM " + table).scalar() == 0
