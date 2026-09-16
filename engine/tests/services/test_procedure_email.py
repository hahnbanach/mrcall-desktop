"""Actual ChatService/core -> scoped reads -> SQLite draft, no provider traffic.

Only the external LLM messages endpoint and provider customer reader are fixtures.
The real LLM budget reservation/settlement and existing draft tool remain in path.
"""

import asyncio
import hashlib
import json
import threading
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.assistant.procedure_fixture import artifact_bytes
from zylch.assistant.procedure import ProcedureArtifact
from zylch.llm.client import LLMClient
from zylch.services.capability_contract import ApprovedSentence, CapabilityBinding, ContactGrant
from zylch.services.procedure_email import EmailSelection, PilotEmailRoute, source_revision
from zylch.services.scoped_capabilities import ScopedCapabilities
from zylch.storage import database
from zylch.storage.models import Blob, BlobSentence, Draft, Email
from zylch.storage.storage import Storage

OWNER = "procedure-owner"
KEY = "A" * 22
RECIPIENT = "customer@example.com"
FACT = "The customer's preferred language is Italian."


def tool(name, arguments, call_id="call-1"):
    return SimpleNamespace(type="tool_use", name=name, input=arguments, id=call_id)


def reply(*blocks):
    return SimpleNamespace(
        content=list(blocks),
        model="claude-haiku-4-5",
        stop_reason="tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn",
        usage=SimpleNamespace(input_tokens=20, output_tokens=3),
    )


def read(op="order.exists", call_id="read"):
    return reply(tool("capability_read", {"operation": op}, call_id))


def finish(status="order_exists", include=False, call_id="finish"):
    return reply(tool("procedure_finish", {"status": status, "include_memory": include}, call_id))


@pytest.fixture
def setup(tmp_path, monkeypatch):
    raw = artifact_bytes()
    artifact = ProcedureArtifact.parse(raw, hashlib.sha256(raw).hexdigest())
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "profile.db"))
    monkeypatch.setenv("MEMORY_DB_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("MEMORY_KEY", KEY)
    monkeypatch.setenv("MEMORY_KEY_SOURCE", "mint")
    monkeypatch.setenv("OWNER_ID", OWNER)
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "5")
    monkeypatch.delenv("ZYLCH_PROFILE_DIR", raising=False)
    database.dispose_engine()
    database.init_db()
    storage = Storage()
    with database.get_session() as session:
        session.add(
            Email(
                id="source",
                owner_id=OWNER,
                gmail_id="source",
                thread_id="thread",
                from_email=RECIPIENT,
                to_email="owner@example.com",
                subject="My order",
                body_plain="Is there an order for me?",
                date=datetime.now(UTC),
                message_id_header="<source@example.com>",
                references="<prior@example.com>",
            )
        )
        session.add(
            Blob(
                id="blob",
                owner_id=OWNER,
                company_key=KEY,
                namespace=f"user:{KEY}",
                content="PRIVATE OWNER NOTES: there is an old order.",
            )
        )
        session.add(
            BlobSentence(
                id="fact",
                blob_id="blob",
                owner_id=OWNER,
                company_key=KEY,
                sentence_text=FACT,
                embedding=b"",
            )
        )
        session.commit()
    binding = CapabilityBinding(
        "business",
        OWNER,
        "service",
        KEY,
        artifact.revision,
        (
            ContactGrant(
                "customer",
                RECIPIENT,
                (ApprovedSentence("fact", hashlib.sha256(FACT.encode()).hexdigest()),),
            ),
        ),
    )
    provider = Mock(
        return_value={
            "data": {
                "customers": {
                    "edges": [
                        {"node": {"id": "customer", "email": RECIPIENT, "numberOfOrders": "1"}}
                    ]
                }
            }
        }
    )
    service = ScopedCapabilities(binding, provider, database.get_session)
    source = storage.get_email_by_supabase_id(OWNER, "source")
    selection = EmailSelection("source", source_revision(source), RECIPIENT, "customer")
    route = PilotEmailRoute(artifact, service, selection)
    client = LLMClient(transport="direct", api_key="fixture-not-a-secret", model="claude-haiku-4-5")
    messages = Mock()
    client._client.messages.create = messages
    from zylch.assistant import core

    monkeypatch.setattr(core, "make_llm_client", lambda: client)
    monkeypatch.setattr(
        core, "get_personal_data_section", Mock(side_effect=AssertionError("private notes"))
    )
    monkeypatch.setattr(
        core, "get_channel_status_block", Mock(side_effect=AssertionError("owner channels"))
    )
    from zylch.services.chat_service import ChatService

    chat = ChatService(pilot_email_route=route)
    chat.storage = storage
    # A selected pilot request must intercept even command-looking chat input.
    monkeypatch.setattr(chat, "_initialize_agent", Mock(side_effect=AssertionError("owner tools")))
    monkeypatch.setattr(chat, "_check_auto_sync", Mock(side_effect=AssertionError("sync")))
    state = SimpleNamespace(
        raw=raw,
        artifact=artifact,
        route=route,
        service=service,
        selection=selection,
        storage=storage,
        client=client,
        messages=messages,
        chat=chat,
        provider=provider,
    )
    yield state
    route.close()
    database.dispose_engine()


def run(state, *, owner=OWNER, context=None):
    return asyncio.run(
        state.chat.process_message(
            "/sync",
            owner,
            conversation_history=[{"role": "user", "content": "PRIVATE HISTORY"}],
            context={"email_id": "source"} if context is None else context,
        )
    )


def drafts():
    with database.get_session() as session:
        return [row.to_dict() for row in session.query(Draft).all()]


def test_real_core_reads_and_persists_only_controlled_draft(setup):
    setup.messages.side_effect = [read(), finish()]
    result = run(setup)
    assert result["metadata"]["procedure_revision"] == setup.artifact.revision
    assert result["metadata"]["draft_id"] == drafts()[0]["id"]
    assert drafts()[0]["body"] == setup.artifact.message("order_exists")
    assert drafts()[0]["to_addresses"] == [RECIPIENT]
    assert drafts()[0]["in_reply_to"] == "<source@example.com>"
    assert drafts()[0]["references"] == ["<prior@example.com>", "<source@example.com>"]
    assert drafts()[0]["status"] == "draft"
    from zylch.llm.budget import budget_snapshot

    assert budget_snapshot(OWNER)["spent_usd"] > 0
    assert setup.provider.call_count == 1
    payloads = repr(setup.messages.call_args_list)
    assert "PRIVATE" not in payloads
    assert setup.artifact.prompt in setup.messages.call_args_list[0].kwargs["system"][0]["text"]
    assert all(c.kwargs["max_tokens"] == 1024 for c in setup.messages.call_args_list)


@pytest.mark.parametrize(
    "first",
    [
        finish(),
        reply(tool("create_draft", {"to": "attacker@example.com", "body": "order confirmed"})),
        reply(tool("send_draft", {"draft_id": "foreign"})),
        reply(
            tool(
                "procedure_finish",
                {"status": "order_exists", "include_memory": False, "body": "fabricated"},
            )
        ),
    ],
)
def test_tool_bypass_and_fabricated_evidence_cannot_create_order_reply(setup, first):
    setup.messages.side_effect = [first, finish("unavailable", call_id="safe")]
    run(setup)
    assert drafts()[0]["body"] == setup.artifact.message("unavailable")
    assert setup.provider.call_count == 0


def test_wrong_outcome_cannot_override_receipt(setup):
    setup.messages.side_effect = [read(), finish("no_order"), finish(call_id="correct")]
    run(setup)
    assert drafts()[0]["body"] == setup.artifact.message("order_exists")


def test_memory_does_not_prove_order_and_failed_refresh_retires_old_success(setup):
    setup.provider.side_effect = [setup.provider.return_value, TimeoutError("SECRET URL")]
    setup.messages.side_effect = [
        read(),
        read(call_id="refresh"),
        finish(),
        finish("unavailable", call_id="safe"),
    ]
    run(setup)
    assert drafts()[0]["body"] == setup.artifact.message("unavailable")


def test_memory_and_order_can_be_chosen_in_either_order(setup):
    setup.messages.side_effect = [
        read("memory.recall"),
        read(call_id="order"),
        finish(include=True),
    ]
    run(setup)
    assert drafts()[0]["body"] == setup.artifact.message("order_exists") + "\n\n" + FACT


def test_plain_model_prose_never_becomes_draft(setup):
    setup.messages.return_value = reply(
        SimpleNamespace(type="text", text="Your order ships today.")
    )
    run(setup)
    assert drafts()[0]["body"] == setup.artifact.message("unavailable")


def test_finish_stops_following_tools_in_same_response(setup):
    setup.messages.return_value = reply(
        tool("procedure_finish", {"status": "need_identification", "include_memory": False}),
        tool("capability_read", {"operation": "order.exists"}, "late"),
    )
    run(setup)
    assert len(drafts()) == 1
    assert setup.provider.call_count == 0
    assert setup.messages.call_count == 1


@pytest.mark.parametrize("change", ["owner", "source", "context", "scope"])
def test_invalid_selection_never_falls_through_or_dispatches_model(setup, monkeypatch, change):
    owner, context = OWNER, {"email_id": "source"}
    if change == "owner":
        owner = "foreign"
    elif change == "context":
        context = {"email_id": "foreign"}
    elif change == "scope":
        monkeypatch.setenv("MEMORY_KEY", "B" * 22)
    else:
        with database.get_session() as session:
            session.query(Email).filter_by(id="source").update({"body_plain": "Changed source"})
            session.commit()
    assert "error" in run(setup, owner=owner, context=context)["metadata"]
    assert not drafts()
    setup.messages.assert_not_called()


def test_release_rechecks_source_after_model(setup):
    def provider(**kwargs):
        with database.get_session() as session:
            session.query(Email).filter_by(id="source").update(
                {"from_email": "attacker@example.com"}
            )
            session.commit()
        return finish("unavailable")

    setup.messages.side_effect = provider
    assert "error" in run(setup)["metadata"]
    assert not drafts()


def test_model_budget_exhaustion_cannot_write_draft(setup):
    setup.messages.side_effect = [read(call_id=str(i)) for i in range(5)]
    assert "error" in run(setup)["metadata"]
    assert setup.messages.call_count == 4
    assert not drafts()


def test_zero_paid_budget_refuses_before_provider_and_draft(setup, monkeypatch):
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "0")
    assert "error" in run(setup)["metadata"]
    setup.messages.assert_not_called()
    assert not drafts()


def test_unexpected_sdk_error_is_not_exposed_or_retried(setup):
    class ProviderFailure(Exception):
        pass

    setup.messages.side_effect = ProviderFailure("PRIVATE provider URL and response")
    result = run(setup)
    assert result["response"] == setup.artifact.message("unavailable")
    assert "PRIVATE" not in repr(result)
    assert setup.messages.call_count == 1
    assert not drafts()


def test_scope_change_during_read_prevents_draft(setup, monkeypatch):
    def changed(email):
        monkeypatch.setenv("MEMORY_KEY", "B" * 22)
        return setup.provider.return_value

    setup.provider.side_effect = changed
    setup.messages.side_effect = [read(), finish()]
    assert "error" in run(setup)["metadata"]
    assert setup.messages.call_count == 1
    assert not drafts()


def test_binding_replacement_during_model_cannot_redirect_read(setup):
    def changed(**kwargs):
        setup.service.binding = replace(setup.service.binding, business_id="other")
        return read()

    setup.messages.side_effect = changed
    assert "error" in run(setup)["metadata"]
    setup.provider.assert_not_called()
    assert not drafts()


def test_current_provider_failure_not_stale_memory_proves_order(setup):
    setup.provider.side_effect = TimeoutError("private provider details")
    setup.messages.side_effect = [
        read("memory.recall"),
        read(call_id="order"),
        finish(),
        finish("unavailable", call_id="safe"),
    ]
    run(setup)
    assert drafts()[0]["body"] == setup.artifact.message("unavailable")


def test_no_order_is_distinct_from_provider_failure(setup):
    setup.provider.return_value["data"]["customers"]["edges"][0]["node"]["numberOfOrders"] = "0"
    setup.messages.side_effect = [read(), finish("no_order")]
    run(setup)
    assert drafts()[0]["body"] == setup.artifact.message("no_order")


def test_cancellation_of_pending_model_cannot_write_late_draft(setup):
    entered, release = threading.Event(), threading.Event()

    def blocked(**kwargs):
        entered.set()
        release.wait(5)
        return finish("unavailable")

    setup.messages.side_effect = blocked

    async def exercise():
        task = asyncio.create_task(
            setup.chat.process_message("reply", OWNER, context={"email_id": "source"})
        )
        while not entered.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        await asyncio.sleep(0.05)

    try:
        asyncio.run(exercise())
        assert not drafts()
    finally:
        release.set()


def test_unidentified_contact_can_only_clarify(setup):
    route = PilotEmailRoute(
        setup.artifact, setup.service, replace(setup.selection, contact_ref=None)
    )
    setup.chat._pilot_email_route = route
    setup.messages.side_effect = [read(), finish("need_identification")]
    try:
        run(setup)
        assert setup.provider.call_count == 0
        assert [t["name"] for t in setup.messages.call_args_list[0].kwargs["tools"]] == [
            "procedure_finish"
        ]
        assert drafts()[0]["body"] == setup.artifact.message("need_identification")
    finally:
        route.close()


def test_revision_and_memory_only_procedure_reuse_existing_loop(setup):
    document = json.loads(setup.raw)
    document.update(
        id="memory-example",
        operations=["memory.recall"],
        completion="memory",
        instructions="Recall approved company information and finish with memory_found.",
    )
    raw = json.dumps(document).encode()
    artifact = ProcedureArtifact.parse(raw, hashlib.sha256(raw).hexdigest())
    setup.service.binding = replace(setup.service.binding, procedure_revision=artifact.revision)
    route = PilotEmailRoute(artifact, setup.service, setup.selection)
    setup.chat._pilot_email_route = route
    setup.messages.side_effect = [read("memory.recall"), finish("memory_found", include=True)]
    try:
        result = run(setup)
        assert result["metadata"]["procedure_revision"] == artifact.revision
        assert drafts()[0]["body"] == artifact.message("memory_found") + "\n\n" + FACT
        assert artifact.prompt in setup.messages.call_args_list[0].kwargs["system"][0]["text"]
        setup.provider.assert_not_called()
    finally:
        route.close()
