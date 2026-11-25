"""Scheduled reply decisions across the guarded SDK, SQLite and a synthetic mailbox."""

import asyncio
import json
from importlib import import_module
from threading import Event
from types import SimpleNamespace

import anthropic
import pytest
from jsonschema import Draft202012Validator

from mail_fixture import ROOT
from test_mailbox_caller_journey import NativeMailbox, journey, parsed, publish_instructions
from zylch.llm.client import LLMClient
from zylch.rpc.draft_actions import drafts_compose_reply
from zylch.services import operator_reply_generation as generation
from zylch.services.mailbox_drafts import MailboxDrafts
from zylch.services.operator_reply_generation import generate
from zylch.services.operator_reply_operations import ReplyRefusal
from zylch.storage import database as db
from zylch.storage.models import LlmReservation
from zylch.storage.storage import Storage


DRAFT = {"reply": {"decision": "draft", "body": "The requested answer."}}
REVIEW = {"reply": {"decision": "needs_review", "reason": "Price requires confirmation.", "missing_facts": ["Price"]}}


def text_block(value):
    return {"type": "text", "text": json.dumps(value)}


@pytest.fixture
def scheduled(env, journey, monkeypatch):
    Storage.get_instance()
    publish_instructions(env)
    source = next(raw for folder in journey.mail.messages.values() for raw in folder.values()
                  if str(parsed(raw)["Message-ID"]) == ROOT)
    monkeypatch.setattr(NativeMailbox, "conversation", lambda self, target: [
        {"message_id": "native-source", "raw": source, "labels": ["INBOX"]}], raising=False)

    def send(self, raw):
        type(self).transmissions += 1
        self.delivered.append(raw)

    monkeypatch.setattr(NativeMailbox, "send_message", send, raising=False)
    payload = {"id": "msg_fixture", "type": "message", "role": "assistant", "model": "claude-sonnet-4-5",
               "content": [text_block(DRAFT)], "stop_reason": "end_turn", "stop_sequence": None,
               "usage": {"input_tokens": 32, "output_tokens": 12, "cache_read_input_tokens": 0,
                         "cache_creation_input_tokens": 0}}
    fixture = SimpleNamespace(calls=[], status=200, payload=payload, params={
        "thread_key": ROOT, "source_email_id": journey.mail.root_id, "request_key": "generated-reply-fixture-01",
        "mode": "send", "operator_origin": "scheduled_operator", "operator_origin_version": 1,
        "request_text": "Address the exact question in the selected message."})

    sdk_http = import_module(anthropic.DefaultHttpxClient.__base__.__module__)

    def respond(request):
        assert request.url.path == "/v1/messages"
        fixture.calls.append(json.loads(request.content))
        if fixture.status != 200:
            return sdk_http.Response(fixture.status, json={"type": "error", "error": {
                "type": "api_error", "message": "Provider diagnostic that must stay private."}})
        return sdk_http.Response(200, json=fixture.payload)

    client = LLMClient("direct", api_key="fixture", model=payload["model"])
    client._client.close()
    with anthropic.Anthropic(api_key="fixture", max_retries=0, http_client=anthropic.DefaultHttpxClient(
            transport=sdk_http.MockTransport(respond))) as sdk:
        client._client = sdk
        monkeypatch.setattr("zylch.llm.make_llm_client", lambda: client)
        monkeypatch.setattr(generation, "generate", generate)
        yield fixture


def invoke(scheduled, **overrides):
    return drafts_compose_reply({**scheduled.params, **overrides}, lambda *args: None)


def paid_attempts():
    with db.get_session() as session:
        return [(row.id, row.settled_at is not None) for row in session.query(LlmReservation).all()]


def test_request_with_stale_instructions_refuses_before_model_or_mailbox_dispatch(scheduled):
    with pytest.raises(ReplyRefusal, match="current_instruction_versions_required"):
        asyncio.run(invoke(scheduled, instruction_versions=[]))
    assert not scheduled.calls and not paid_attempts()
    assert NativeMailbox.transmissions == NativeMailbox.creates == 0


@pytest.mark.parametrize("decision", [DRAFT, REVIEW], ids=["send", "review"])
def test_scheduled_decision_uses_exact_context_and_one_native_schema(env, scheduled, decision):
    scheduled.payload["content"] = [text_block(decision)]
    result = asyncio.run(invoke(scheduled))
    assert result["ok"], result
    assert len(scheduled.calls) == 1
    wire = scheduled.calls[0]
    assert wire["model"] == "claude-sonnet-4-5"
    assert "tools" not in wire and "tool_choice" not in wire
    form = wire["output_config"]["format"]
    assert form["type"] == "json_schema"
    validator = Draft202012Validator(form["schema"])
    for expected in (DRAFT, REVIEW):
        validator.validate(expected)
    for invalid in ({"reply": {"decision": "draft"}}, {"reply": {**DRAFT["reply"], "reason": "extra"}},
                    {"reply": {**REVIEW["reply"], "body": "must not send"}}, {**DRAFT, "extra": True}):
        assert not validator.is_valid(invalid)
    request = json.loads(wire["messages"][0]["content"])
    assert request["request"] == scheduled.params["request_text"]
    assert request["context"]["source"]["id"] == scheduled.params["source_email_id"]
    assert {d["path"] for d in request["context"]["instructions"]} == {"procedures.md", "mail/alice@example.test.md"}
    assert request["context"]["correspondence"]["emails"]
    assert paid_attempts() == [(result["reservation_ids"][0], True)]
    env.select("alice")
    again = asyncio.run(invoke(scheduled, recover_only=True))
    assert again["operation_id"] == result["operation_id"] and again["state"] == result["state"]
    assert len(scheduled.calls) == 1 and NativeMailbox.creates == 0
    if decision == DRAFT:
        assert result["state"] == "sent" and result["effect_certainty"] == "verified"
        assert NativeMailbox.transmissions == 1
        assert parsed(NativeMailbox.delivered[0]).get_content().strip() == DRAFT["reply"]["body"]
    else:
        assert result["state"] == "needs_review" and result["review"]["missing_facts"] == ["Price"]
        assert NativeMailbox.transmissions == 0


@pytest.mark.parametrize("content,stop,status,cause", [
    ([{"type": "text", "text": "Private malformed output."}], "end_turn", 200, "structured_draft_required"),
    ([{"type": "text", "text": '{"reply":{"decision":"needs_review","decision":"draft","body":"fixture"}}'}],
     "end_turn", 200, "structured_draft_required"),
    ([], "end_turn", 200, "structured_draft_required"),
    ([text_block(DRAFT)], "max_tokens", 200, "incomplete_or_tool_generation_refused"),
    ([text_block(DRAFT), {"type": "thinking", "thinking": "Private thought", "signature": "fixture"}],
     "end_turn", 200, "incomplete_or_tool_generation_refused"),
    ([text_block({"reply": {**DRAFT["reply"], "extra": "private"}})], "end_turn", 200, "structured_reply_decision_required"),
    ([text_block({"reply": {**REVIEW["reply"], "missing_facts": []}})], "end_turn", 200, "bounded_internal_review_required"),
    ([text_block({"reply": {**DRAFT["reply"], "body": "  "}})], "end_turn", 200, "bounded_plain_draft_body_required"),
    ([], "end_turn", 500, "reply_generation_provider_error"),
], ids=["malformed", "duplicate-field", "empty", "truncated", "nontext", "extra-field", "empty-review", "blank-body", "provider-error"])
def test_reopen_preserves_body_free_generation_failure_and_original_paid_attempt(
        env, scheduled, monkeypatch, content, stop, status, cause):
    scheduled.payload.update(content=content, stop_reason=stop)
    scheduled.status = status
    first = asyncio.run(invoke(scheduled))
    assert first["ok"] is False and first["state"] == "failed_before_dispatch", first
    assert first["effect_certainty"] == "not-dispatched" and first["cause"] == cause
    with db.get_engine().connect() as conn:
        row = conn.exec_driver_sql("SELECT id, result FROM operator_reply_operations").one()
        assert row.id == first["operation_id"]
        assert json.loads(row.result) == {"stage": "generation", "cause": cause, "effect_certainty": "not-dispatched"}
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM mailbox_operation_receipts").scalar_one() == 0
    monkeypatch.setattr(NativeMailbox, "__init__", lambda *args: pytest.fail("recovery opened provider"))
    env.select("alice")
    assert asyncio.run(invoke(scheduled)) == first
    assert asyncio.run(invoke(scheduled, recover_only=True)) == first
    assert len(scheduled.calls) == 1 and paid_attempts() == [(first["reservation_ids"][0], status == 200)]
    assert NativeMailbox.transmissions == NativeMailbox.creates == 0


def test_old_paid_operation_without_mailbox_receipt_stays_uncertain(env, scheduled, monkeypatch):
    scheduled.payload["content"] = []
    first = asyncio.run(invoke(scheduled))
    with db.get_engine().begin() as conn:
        conn.exec_driver_sql("UPDATE operator_reply_operations SET state='uncertain',result=NULL WHERE id=?",
                             (first["operation_id"],))
    env.select("alice")
    monkeypatch.setattr(NativeMailbox, "__init__", lambda *args: pytest.fail("legacy recovery opened provider"))
    recovered = asyncio.run(invoke(scheduled))
    assert not recovered["ok"] and recovered["state"] == "uncertain"
    assert recovered["operation_id"] == first["operation_id"]
    assert recovered["cause"] == "reply_operation_without_mailbox_receipt" and recovered["effect_certainty"] == "unknown"
    assert paid_attempts() == [(first["reservation_ids"][0], True)] and len(scheduled.calls) == 1
    with db.get_engine().connect() as conn:
        assert conn.exec_driver_sql("SELECT state, result FROM operator_reply_operations").one() == ("uncertain", None)
    assert NativeMailbox.transmissions == NativeMailbox.creates == 0


@pytest.mark.parametrize("reserved", [False, True], ids=["before-receipt", "after-reservation"])
def test_cancelled_writer_reconciles_only_original_send(env, scheduled, monkeypatch, reserved):
    entered, release = Event(), Event()
    sent = NativeMailbox.sent

    def pause_writer():
        entered.set()
        assert release.wait(10)

    if reserved:
        reserve = MailboxDrafts._reserve
        def after_reserve(*args, **kwargs):
            receipt = reserve(*args, **kwargs)
            pause_writer()
            return receipt
        monkeypatch.setattr(MailboxDrafts, "_reserve", after_reserve)
    else:
        persist = generation.persist
        def before_receipt(*args, **kwargs):
            pause_writer()
            return persist(*args, **kwargs)
        monkeypatch.setattr(generation, "persist", before_receipt)
    monkeypatch.setattr(NativeMailbox, "sent", lambda self, message: [])

    async def cancel():
        task = asyncio.create_task(invoke(scheduled))
        try:
            assert await asyncio.to_thread(entered.wait, 10)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            result = await invoke(scheduled, recover_only=True)
            assert result["state"] == "uncertain" and result["effect_certainty"] == "unknown", result
            assert result["cause"] == ("mailbox_operation_reserved" if reserved else "reply_operation_without_mailbox_receipt")
            assert NativeMailbox.transmissions == 0
            return result["operation_id"]
        finally:
            release.set()

    operation = asyncio.run(cancel())
    env.select("alice")
    pending = asyncio.run(invoke(scheduled))
    assert not pending["ok"] and pending["state"] == "uncertain" and pending["operation_id"] == operation
    assert pending["cause"] == "sent_not_yet_confirmed" and pending["effect_certainty"] == "unconfirmed"
    monkeypatch.setattr(NativeMailbox, "sent", sent)
    async def concurrent_recovery():
        return await asyncio.gather(invoke(scheduled, recover_only=True), invoke(scheduled, recover_only=True))

    confirmed, again = asyncio.run(concurrent_recovery())
    assert confirmed["ok"] and confirmed["state"] == "sent" and confirmed["message_id"] == pending["message_id"]
    assert confirmed["generation_operation_id"] == operation
    assert confirmed["operation_id"] == pending["mailbox_operation_id"]
    assert again["ok"] and again["message_id"] == confirmed["message_id"]
    assert len(scheduled.calls) == NativeMailbox.transmissions == 1 and NativeMailbox.creates == 0
    assert paid_attempts() == [(pending["reservation_ids"][0], True)]


@pytest.mark.parametrize("incident,state,cause", [
    ("human_draft", "draft_exists", "scheduled_draft_exists"),
    ("changed_rules", "failed_before_dispatch", "instructions_changed_before_private_commit"),
    ("two_senders", "failed_before_dispatch", "one_external_source_sender_required"),
])
def test_admitted_pre_writer_outcome_survives_reopen_with_its_paid_identity(
        scheduled, env, monkeypatch, incident, state, cause):
    from base64 import b64encode
    from zylch.services import project_store
    from zylch.services.mailbox_draft_mime import build
    from zylch.services.operator_reply_operations import ReplyOperations
    from zylch.storage.models import Email

    if incident == "human_draft":
        async def person_saves_a_draft(context, request):
            decision = await generate(context, request)
            raw = build("alice@example.test", to=["customer@example.test"], subject="Review",
                        body="Human mailbox draft", message_id="<edit@example.test>",
                        in_reply_to=ROOT, references=[ROOT], thread_id=ROOT)
            NativeMailbox("alice@example.test").create_draft(raw, thread_id="native-thread")
            return decision
        monkeypatch.setattr(generation, "generate", person_saves_a_draft)
    elif incident == "changed_rules":
        scheduled.payload["content"] = [text_block(REVIEW)]
        finish = ReplyOperations._finish_review
        def publish_then_commit(*args):
            revision = b64encode(b"New published instructions.").decode()
            project_store.write(env.space, "operator-instructions", "procedures.md", revision, 1, "fixture")
            return finish(*args)
        monkeypatch.setattr(ReplyOperations, "_finish_review", publish_then_commit)
    else:
        with db.get_session() as session:
            source = session.get(Email, scheduled.params["source_email_id"])
            source.from_email = "first@example.test, second@example.test"

    first = asyncio.run(invoke(scheduled))
    assert first["state"] == state and first["cause"] == cause
    assert first["ok"] is (incident == "human_draft") and first["effect_certainty"] == "not-dispatched"
    assert first["operation_id"] == first["generation_operation_id"]
    assert len(first["reservation_ids"]) == 1 and paid_attempts() == [(first["reservation_ids"][0], True)]
    env.select("alice")
    monkeypatch.setattr(NativeMailbox, "__init__", lambda *args: pytest.fail("pre-writer recovery opened provider"))
    assert asyncio.run(invoke(scheduled)) == first
    assert asyncio.run(invoke(scheduled, recover_only=True)) == first
    with db.get_engine().connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM mailbox_operation_receipts").scalar_one() == 0
    assert len(scheduled.calls) == 1 and NativeMailbox.transmissions == 0
    assert NativeMailbox.creates == int(incident == "human_draft")
