"""Voice acknowledgements must not starve the delegated task."""

import asyncio
import threading
from unittest.mock import AsyncMock

from tests.voice.helpers import delegation
from tests.voice.test_conversation import make_conversation, response, until


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
        assert len(calls) == 3  # tool request, tool result, voice-aware final reconciliation
        assert "tool_result" in str(calls[-1]["messages"])
        assert "I am checking." in str(calls[-1]["messages"])
        assert sent[-1]["content"] == "The historical delivery agreement was Thursday."
        await conv.close()

    try:
        asyncio.run(scenario())
    finally:
        release.set()
