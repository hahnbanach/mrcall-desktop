"""Real agent/tool/storage/budget boundaries; only the paid model wire is mocked."""

import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock

import pytest

from tests.voice.helpers import delegation
from tests.voice.m2_fixture import FOLLOWUP, INTERNAL, KNOWN, NUMBER, OTHER_FACT, PUBLIC
from tests.voice.test_agent_config import save
from zylch.assistant import core
from zylch.llm.budget import budget_snapshot
from zylch.llm.client import LLMClient
from zylch.services.voice.agent_config import snapshot_for_call
from zylch.services.voice.caller_memory import CallerMemory
from zylch.services.voice.conversation import Conversation, chunks


def response(text="Verified answer", tool=None):
    return SimpleNamespace(
        content=(
            [SimpleNamespace(type="tool_use", id="lookup", name="caller_memory", input=tool)]
            if tool is not None
            else [SimpleNamespace(type="text", text=text)]
        ),
        model="claude-haiku-4-5",
        stop_reason="tool_use" if tool is not None else "end_turn",
        usage=SimpleNamespace(input_tokens=30, output_tokens=20),
    )


def make_conversation(monkeypatch, calls):
    monkeypatch.delenv("ZYLCH_PROFILE_DIR", raising=False)
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "2")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    save()
    snap = snapshot_for_call(NUMBER)
    client = LLMClient(transport="direct", api_key="fake", model="claude-haiku-4-5")
    client._client.messages.create = Mock(side_effect=calls)
    sent = []

    async def send(raw):
        sent.append(json.loads(raw))

    memory = CallerMemory(snap, KNOWN)
    conv = Conversation(snap, memory, client, send, {"results_sent": 0})
    return conv, client, sent


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.005)


def test_followup_actual_tools_no_owner_inputs(fixture_db, monkeypatch, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    conv, client, sent = make_conversation(
        monkeypatch,
        [
            response(tool={"query": "filters"}),
            response(PUBLIC),
            response(tool={"query": "delivery"}),
            response(FOLLOWUP),
        ],
    )
    monkeypatch.setattr(core, "get_system_prompt_base", Mock(side_effect=AssertionError("owner")))
    monkeypatch.setattr(
        core, "get_personal_data_section", Mock(side_effect=AssertionError("owner"))
    )
    monkeypatch.setattr(core, "get_channel_status_block", Mock(side_effect=AssertionError("owner")))

    async def scenario():
        conv.start()
        conv.event({"type": "session.input_transcript.delta", "delta": "My earlier request?"})
        conv.event(delegation("first"))
        await until(lambda: conv.evidence["results_sent"] == 1)
        conv.event({"type": "session.output_transcript.delta", "delta": PUBLIC})
        conv.event({"type": "session.input_transcript.delta", "delta": "And delivery?"})
        conv.event(delegation("followup"))
        await until(lambda: conv.evidence["results_sent"] == 2)
        for call in client._client.messages.create.call_args_list:
            wire = str(call.kwargs)
            assert INTERNAL not in wire and OTHER_FACT not in wire and fixture_db not in wire
            assert "PRIVATE FULL BLOB" not in wire
            assert [t["name"] for t in call.kwargs["tools"]] == ["caller_memory"]
        assert FOLLOWUP in str(sent)
        assert FOLLOWUP not in caplog.text and PUBLIC not in caplog.text
        assert INTERNAL not in caplog.text and fixture_db not in caplog.text
        assert budget_snapshot("fixture-owner")["spent_usd"] > 0
        await conv.close()

    asyncio.run(scenario())


def test_delayed_lookup_and_revision_reconciliation(fixture_db, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def model(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            entered.set()
            assert release.wait(3)
            return response("OBSOLETE DRAFT")
        return response(
            "Correction: the caller now asks about delivery; stored history says Thursday."
        )

    conv, _, sent = make_conversation(monkeypatch, model)
    original = conv.memory.execute

    async def scenario():
        lookup_release = asyncio.Event()

        async def delayed(**kwargs):
            await lookup_release.wait()
            return await original(**kwargs)

        conv.memory.execute = delayed
        conv.start()
        conv.event({"type": "session.output_transcript.delta", "delta": "Hello"})
        assert not sent
        conv.event({"type": "session.input_transcript.delta", "delta": "filters"})
        conv.event(delegation("first"))
        lookup_release.set()
        await until(entered.is_set)
        conv.event({"type": "session.input_transcript.delta", "delta": " No, delivery."})
        conv.event(delegation("corrected"))
        release.set()
        await until(lambda: conv.evidence["results_sent"] == 1)
        assert len(calls) == 2
        assert "No, delivery." in str(calls[-1]["messages"])
        assert "OBSOLETE DRAFT" not in str(sent)
        assert sent[-1]["delegation_id"] == "corrected"
        assert conv.evidence["reconciliations"] == 1
        await conv.close()

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_hangup_during_dispatch_settles_without_more_tools(fixture_db, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def model(**kwargs):
        entered.set()
        assert release.wait(3)
        return response(tool={"query": "delivery"})

    conv, client, sent = make_conversation(monkeypatch, model)

    async def scenario():
        conv.start()
        conv.event({"type": "session.input_transcript.delta", "delta": "delivery?"})
        conv.event(delegation())
        await until(entered.is_set)
        await conv.close()
        before = list(sent)
        assert budget_snapshot("fixture-owner")["reserved_usd"] > 0
        release.set()
        await until(lambda: budget_snapshot("fixture-owner")["reserved_usd"] == 0)
        assert budget_snapshot("fixture-owner")["spent_usd"] > 0
        assert client._client.messages.create.call_count == 1
        assert sent == before and conv.agent.get_history() == []

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_late_read_and_next_call_have_no_history(fixture_db, monkeypatch):
    conv, _, sent = make_conversation(monkeypatch, [response()])
    original = conv.memory._lookup
    entered, release = threading.Event(), threading.Event()

    def delayed(query):
        entered.set()
        assert release.wait(3)
        return original(query)

    conv.memory._lookup = delayed

    async def scenario():
        conv.start()
        await until(entered.is_set)
        conv.event({"type": "session.input_transcript.delta", "delta": "private caller input"})
        await conv.close()
        release.set()
        await asyncio.sleep(0.05)
        assert sent == []
        new, _, _ = make_conversation(monkeypatch, [response()])
        assert new.transcript == [] and new.agent.get_history() == []
        await new.close()

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_owner_agent_unchanged_and_voice_tools_enforced(monkeypatch):
    client = SimpleNamespace(
        transport="mock",
        create_message=AsyncMock(
            return_value=SimpleNamespace(
                content=[SimpleNamespace(text="ok")], stop_reason="end_turn", usage={}
            )
        ),
    )
    monkeypatch.setattr(core, "get_system_prompt_base", lambda: "OWNER PROMPT")
    monkeypatch.setattr(core, "get_personal_data_section", lambda **kw: "OWNER PRIVATE")
    monkeypatch.setattr(core, "get_channel_status_block", lambda: "OWNER CHANNELS")
    tool = SimpleNamespace(name="owner_tool", get_schema=lambda: {"name": "owner_tool"})
    agent = core.ZylchAIAgent([tool], client=client, triggered_instructions=["OWNER TRIGGER"])
    asyncio.run(agent.process_message("hello"))
    wire = str(client.create_message.call_args.kwargs)
    for expected in (
        "OWNER PROMPT",
        "OWNER PRIVATE",
        "OWNER CHANNELS",
        "OWNER TRIGGER",
        "owner_tool",
    ):
        assert expected in wire
    with pytest.raises(ValueError):
        core.ZylchAIAgent([tool], client=client, customer_service_instructions="voice")


def test_append_limit_preserves_multibyte_content():
    text = "è漢字 hello " * 800
    parts = list(chunks(text))
    assert "".join(parts) == text
    assert all(len(part.encode()) <= 480 for part in parts)


def test_voice_answer_during_backend_is_reconciled_without_repetition(fixture_db, monkeypatch):
    """Voice may answer from quiet context while the backend is in flight."""
    entered, release = threading.Event(), threading.Event()
    requests = []

    def model(**kwargs):
        requests.append(json.dumps(kwargs["messages"]))
        if len(requests) == 1:
            entered.set()
            assert release.wait(3)
            return response("The filters are blue.")
        return response("[NO_FURTHER_RESPONSE]")

    conv, _, sent = make_conversation(monkeypatch, model)

    async def scenario():
        conv.start()
        conv.event(
            {"type": "session.input_transcript.delta", "delta": "What colour are my filters?"}
        )
        conv.event(delegation("colour"))
        await until(entered.is_set)
        conv.event(
            {
                "type": "session.output_transcript.delta",
                "delta": "The stored request is for blue replacement filters.",
            }
        )
        release.set()
        await until(lambda: conv.worker.done())
        assert len(requests) == 2, "Backend did not see voice's answer before delivery"
        assert "stored request is for blue" in requests[-1]
        assert conv.evidence["results_sent"] == 0
        assert not any(row["type"] == "session.commentary.append" for row in sent)
        assert conv.evidence["answers_already_addressed"] == 1
        await conv.close()

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_diagnostic_delay_skips_superseded_snapshot_before_paid_dispatch(fixture_db, monkeypatch):
    requests = []

    def model(**kwargs):
        requests.append(json.dumps(kwargs["messages"]))
        return response("Stored delivery is Thursday.")

    conv, _, sent = make_conversation(monkeypatch, model)
    conv.backend_delay = 0.05

    async def scenario():
        conv.start()
        conv.event({"type": "session.input_transcript.delta", "delta": "Which filters?"})
        conv.event(delegation("first"))
        await until(lambda: conv.run_number == 1)
        conv.event(
            {"type": "session.input_transcript.delta", "delta": " CORRECTION: delivery day?"}
        )
        await until(lambda: conv.evidence["results_sent"] == 1)
        assert len(requests) == 1, "Obsolete pre-delay snapshot was dispatched"
        assert "CORRECTION" in requests[0]
        assert conv.evidence["reconciliations"] == 1
        assert len([row for row in sent if row["type"] == "session.commentary.append"]) == 1
        await conv.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "spoken,latest_caller,answer",
    [
        ("One moment, I am checking.", None, "Stored delivery is Thursday."),
        (
            "The agreed delivery is Friday.",
            None,
            "Correction: the prior email agreed Thursday, not Friday.",
        ),
        (
            "The stored request is for blue filters.",
            "And the tracking number?",
            "There is no tracking number in the selected history.",
        ),
    ],
)
def test_voice_reconciliation_still_delivers_missing_or_corrected_answer(
    fixture_db, monkeypatch, spoken, latest_caller, answer
):
    entered, release = threading.Event(), threading.Event()
    requests = []

    def model(**kwargs):
        requests.append(json.dumps(kwargs["messages"]))
        if len(requests) == 1:
            entered.set()
            assert release.wait(3)
            return response("OUTDATED BACKEND DRAFT")
        return response(answer)

    conv, _, sent = make_conversation(monkeypatch, model)

    async def scenario():
        conv.start()
        conv.event(
            {
                "type": "session.input_transcript.delta",
                "delta": "Check my prior request and delivery.",
            }
        )
        conv.event(delegation("request"))
        await until(entered.is_set)
        conv.event({"type": "session.output_transcript.delta", "delta": spoken})
        if latest_caller:
            conv.event({"type": "session.input_transcript.delta", "delta": latest_caller})
            conv.event(delegation("followup"))
        release.set()
        await until(lambda: conv.worker.done())
        assert len(requests) == 2 and spoken in requests[-1]
        if latest_caller:
            assert latest_caller in requests[-1]
        delivered = [row for row in sent if row["type"] == "session.commentary.append"]
        assert len(delivered) == 1 and delivered[0]["content"] == answer
        assert "OUTDATED" not in str(sent)
        assert conv.evidence.get("answers_already_addressed", 0) == 0
        await conv.close()

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_greeting_requested_once_before_delayed_lookup(fixture_db, monkeypatch):
    conv, _, sent = make_conversation(monkeypatch, [])

    async def scenario():
        conv.memory.diagnostic_delay = 60
        conv.start()
        conv.event({"type": "session.started"})
        conv.event({"type": "session.started"})
        await until(lambda: bool(sent))
        assert [s["type"] for s in sent] == ["session.instructions.append"]
        assert sent[0]["delegation_id"] is None
        assert conv.context["missing"] == ["Caller lookup pending"]
        await conv.close()
        assert len(sent) == 1

    asyncio.run(scenario())


def test_correction_abandons_stale_tool_loop_before_extra_dispatch(fixture_db, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def model(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            entered.set()
            assert release.wait(3)
            return response(tool={"query": "tracking"})
        return response("The corrected request is blue filters for Thursday.")

    conv, _, sent = make_conversation(monkeypatch, model)
    lookup = AsyncMock(wraps=conv.memory.execute)
    conv.memory.execute = lookup

    async def scenario():
        conv.event({"type": "session.input_transcript.delta", "delta": "Tracking?"})
        conv.event(delegation("old"))
        await until(entered.is_set)
        conv.event({"type": "session.input_transcript.delta", "delta": "No, filters and day?"})
        conv.event(delegation("corrected"))
        release.set()
        await until(lambda: conv.evidence["results_sent"] == 1)
        assert len(calls) == 2
        assert lookup.await_count == 0  # stale tool request never executes
        assert "filters and day?" in str(calls[1]["messages"])
        assert not any("tool_result" in str(m) for m in calls[1]["messages"])
        assert sent[-1]["delegation_id"] == "corrected"
        assert conv.evidence["reconciliations"] == 1
        await conv.close()

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_correction_during_tool_preserves_prior_turn_and_skips_remaining_tools(
    fixture_db, monkeypatch
):
    two_tools = response(tool={})
    two_tools.content.append(
        SimpleNamespace(type="tool_use", id="second", name="caller_memory", input={})
    )
    conv, client, sent = make_conversation(
        monkeypatch, [response("PRIOR COMPLETED TURN"), two_tools, response("Corrected Thursday.")]
    )

    async def scenario():
        await conv.agent.process_message("Prior request")
        entered, release = asyncio.Event(), asyncio.Event()
        original = conv.memory.execute
        tool_calls = []

        async def delayed(**kwargs):
            tool_calls.append(kwargs)
            entered.set()
            await release.wait()
            return await original(**kwargs)

        conv.memory.execute = delayed
        conv.event({"type": "session.input_transcript.delta", "delta": "Tracking?"})
        conv.event(delegation("old"))
        await entered.wait()
        conv.event({"type": "session.input_transcript.delta", "delta": "No, delivery day?"})
        conv.event(delegation("corrected"))
        release.set()
        await conv.worker
        assert len(tool_calls) == 1
        assert conv.evidence["results_sent"] == 1
        assert conv.evidence["reconciliations"] == 1
        latest = str(client._client.messages.create.call_args.kwargs["messages"])
        assert "PRIOR COMPLETED TURN" in latest and "delivery day?" in latest
        assert "tool_result" not in latest and "tool_use" not in latest
        assert sent[-1]["delegation_id"] == "corrected"
        await conv.close()

    asyncio.run(scenario())
