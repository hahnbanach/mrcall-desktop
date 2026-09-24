"""Coalesce corrected caller fragments without delaying initial delegation."""

import asyncio
import json
import threading

import pytest

from tests.voice.helpers import delegation
from tests.voice.test_conversation import make_conversation, response, until
from zylch.services.voice import conversation


@pytest.mark.parametrize("stale_tool", [False, True])
def test_partial_correction_waits_for_complete_delegation(fixture_db, monkeypatch, stale_tool):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def model(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            entered.set()
            assert release.wait(3)
            return response("Old answer", tool={} if stale_tool else None)
        return response("Corrected request: Rome.")

    conv, _, sent = make_conversation(monkeypatch, model)

    async def scenario():
        conv.event({"type": "session.input_transcript.delta", "delta": "New York?"})
        conv.event(delegation("old"))
        await until(entered.is_set)
        conv.event({"type": "session.input_transcript.delta", "delta": " No, I want"})
        release.set()
        await until(lambda: conv.evidence.get("reconciliations") == 1)
        await asyncio.sleep(0.02)
        assert len(calls) == 1
        conv.event({"type": "session.input_transcript.delta", "delta": " Rome."})
        conv.event(delegation("corrected"))
        await conv.worker
        assert len(calls) == 2 and "No, I want Rome." in str(calls[-1]["messages"])
        assert sent[-1]["delegation_id"] == "corrected"
        assert "Old answer" not in str(sent)
        await conv.close()

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_interrupted_append_coalesces_before_replacing_answer(fixture_db, monkeypatch):
    conv, client, sent = make_conversation(monkeypatch, [response("x" * 1400), response("Rome.")])

    async def send(raw):
        sent.append(json.loads(raw))
        if len(sent) == 1:
            conv.event({"type": "session.input_transcript.delta", "delta": " No, I want"})

    conv.send = send

    async def scenario():
        conv.event({"type": "session.input_transcript.delta", "delta": "New York?"})
        conv.event(delegation("old"))
        await until(lambda: bool(sent))
        await asyncio.sleep(0.02)
        assert client._client.messages.create.call_count == 1 and len(sent) == 1
        conv.event({"type": "session.input_transcript.delta", "delta": " Rome."})
        conv.event(delegation("new"))
        await conv.worker
        assert client._client.messages.create.call_count == 2
        assert len(sent) == 2 and sent[-1]["content"] == "Rome."
        assert sent[-1]["delegation_id"] == "new"
        await conv.close()

    asyncio.run(scenario())


def test_quiet_fallback_resets_only_for_caller_and_needs_no_delegation(fixture_db, monkeypatch):
    monkeypatch.setattr(conversation, "CORRECTION_QUIET_SECONDS", 0.15)
    conv, _, _ = make_conversation(monkeypatch, [])

    async def scenario():
        conv.event({"type": "session.input_transcript.delta", "delta": "No,"})
        wait = asyncio.create_task(conv._settle_correction())
        await asyncio.sleep(0.09)
        conv.event({"type": "session.input_transcript.delta", "delta": " Rome."})
        await asyncio.sleep(0.09)
        assert not wait.done(), "Further caller input must reset the quiet interval"
        conv.event({"type": "session.output_transcript.delta", "delta": "Okay."})
        await asyncio.wait_for(wait, 0.1)
        assert conv.delegated_revision == -1  # no new delegation was required
        await conv.close()

    asyncio.run(scenario())


def test_hangup_cancels_wait_without_another_model_dispatch(fixture_db, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def model(**kwargs):
        entered.set()
        assert release.wait(3)
        return response("Old answer")

    conv, client, sent = make_conversation(monkeypatch, model)

    async def scenario():
        conv.event({"type": "session.input_transcript.delta", "delta": "New York?"})
        conv.event(delegation("old"))
        await until(entered.is_set)
        conv.event({"type": "session.input_transcript.delta", "delta": "No,"})
        release.set()
        await until(lambda: conv.evidence.get("reconciliations") == 1)
        await conv.close()
        assert conv.worker.done() and client._client.messages.create.call_count == 1
        assert sent == []

    try:
        asyncio.run(scenario())
    finally:
        release.set()
