"""Voice acknowledgements must not starve the delegated task."""

import asyncio
import threading
import json
from unittest.mock import AsyncMock

from tests.voice.helpers import delegation
from tests.voice.test_conversation import make_conversation, response, until
from tests.voice.m2_fixture import PUBLIC, FOLLOWUP


def test_voice_progress_does_not_restart_the_tool_round(fixture_db, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def model(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            entered.set()
            assert release.wait(3)
            return response(tool={})
        return response("The historical delivery agreement was Thursday.")

    conv, _, sent = make_conversation(monkeypatch, model)
    lookup = AsyncMock(wraps=conv.memory.execute)
    conv.memory.execute = lookup

    async def scenario():
        conv.event({"type": "session.input_transcript.delta", "delta": "What day was agreed?"})
        conv.event(delegation("day"))
        await until(entered.is_set)
        conv.event({"type": "session.output_transcript.delta", "delta": "I am checking."})
        release.set()
        await conv.worker
        assert lookup.await_count == 1, "Voice filler discarded the required lookup"
        assert conv.evidence["results_sent"] == 1
        assert len(calls) == 2  # tool request and result, no voice-only rerun
        assert "tool_result" in str(calls[-1]["messages"])
        assert conv.evidence.get("reconciliations", 0) == 0
        assert sent[-1]["content"] == "The historical delivery agreement was Thursday."
        await conv.close()

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_preload_goes_to_backend_without_quiet_voice_facts(fixture_db, monkeypatch):
    conv, client, sent = make_conversation(monkeypatch, [response("No tracking code is stored.")])
    lookup = AsyncMock(wraps=conv.memory.execute)
    conv.memory.execute = lookup

    async def scenario():
        conv.start()
        conv.event({"type": "session.input_transcript.delta", "delta": "Tracking?"})
        conv.event(delegation("tracking"))
        await conv.worker
        request = str(client._client.messages.create.call_args.kwargs["messages"])
        assert PUBLIC in request and FOLLOWUP in request
        assert lookup.await_count == 1  # preload only; model needed no further tool
        assert not any(row["type"] == "session.thinking.append" for row in sent)
        assert conv.evidence["results_sent"] == 1
        await conv.close()

    asyncio.run(scenario())


def test_chunk_delivery_survives_voice_but_stops_on_caller(fixture_db, monkeypatch):
    conv, _, sent = make_conversation(monkeypatch, [])

    async def send(raw):
        sent.append(json.loads(raw))
        role = "output" if len(sent) == 1 else "input"
        conv.event({"type": f"session.{role}_transcript.delta", "delta": "speech"})

    conv.send = send

    async def scenario():
        delivered = await conv._append("session.commentary.append", "x" * 1400, "d", 0)
        assert not delivered and len(sent) == 2
        assert conv.voice_revision == conv.revision == 1
        await conv.close()

    asyncio.run(scenario())


def test_lookup_failure_still_reaches_backend(fixture_db, monkeypatch):
    conv, client, sent = make_conversation(monkeypatch, [response("Memory is unavailable.")])
    conv.memory.diagnostic_failure = True

    async def scenario():
        conv.start()
        conv.event({"type": "session.input_transcript.delta", "delta": "My order?"})
        conv.event(delegation("failure"))
        await conv.worker
        request = str(client._client.messages.create.call_args.kwargs["messages"])
        assert "Caller memory unavailable" in request and PUBLIC not in request
        assert conv.evidence["results_sent"] == 1
        await conv.close()

    asyncio.run(scenario())
