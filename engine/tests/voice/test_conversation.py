"""Selected context and deterministic Live delegations at the real memory boundary."""

import asyncio
import json

from tests.voice.helpers import delegation
from tests.voice.m2_fixture import KNOWN, NUMBER, PUBLIC, FOLLOWUP, INTERNAL, OTHER_FACT
from tests.voice.test_agent_config import save
from zylch.services.voice.agent_config import snapshot_for_call
from zylch.services.voice.caller_memory import CallerMemory
from zylch.services.voice.conversation import Conversation, VOICE_RULES, chunks


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.005)


def make_conversation(monkeypatch=None, unused=None, *, caller=KNOWN, trace=None):
    save()
    snapshot = snapshot_for_call(NUMBER)
    sent = []

    async def send(raw):
        sent.append(json.loads(raw))

    conv = Conversation(
        snapshot, CallerMemory(snapshot, caller), send, {"results_sent": 0}, trace=trace
    )
    return conv, None, sent


def test_quiet_selected_context_before_question(fixture_db, monkeypatch):
    conv, _, sent = make_conversation(monkeypatch)

    async def scenario():
        conv.start()
        conv.event({"type": "session.started"})
        await conv.lookup
        await until(lambda: any(row["type"] == "session.instructions.append" for row in sent))
        assert any(
            row["type"] == "session.thinking.append" and row["delegation_id"] is None
            for row in sent
        )
        assert PUBLIC in str(sent) and FOLLOWUP in str(sent)
        assert INTERNAL not in str(sent) and OTHER_FACT not in str(sent)
        assert "Delegate every substantive" not in VOICE_RULES
        assert not any(row["type"] == "session.commentary.append" for row in sent)
        await conv.close()

    asyncio.run(scenario())


def test_early_question_joins_lookup_and_binds_commentary(fixture_db, monkeypatch):
    conv, _, sent = make_conversation(monkeypatch)
    original = conv.memory.execute
    gate = asyncio.Event()
    calls = 0

    async def delayed(**kwargs):
        nonlocal calls
        calls += 1
        await gate.wait()
        return await original(**kwargs)

    conv.memory.execute = delayed

    async def scenario():
        conv.start()
        conv.event({"type": "session.started"})
        conv.event(
            {"type": "session.input_transcript.delta", "delta": "Quali filtri e quando arriva?"}
        )
        conv.event(delegation("early"))
        await until(lambda: calls == 1)
        assert not any(row["type"] == "session.commentary.append" for row in sent)
        gate.set()
        await until(lambda: conv.evidence["results_sent"] == 1)
        assert calls == 1
        assert [r["type"] for r in sent if r["type"] != "session.instructions.append"] == [
            "session.thinking.append",
            "session.commentary.append",
        ]
        answer = sent[-1]
        assert answer["delegation_id"] == "early"
        assert PUBLIC in answer["content"] and FOLLOWUP in answer["content"]
        await conv.close()

    asyncio.run(scenario())


def test_correction_during_clock_and_hangup_suppress_stale(fixture_db, monkeypatch):
    from tests.voice.m2_fixture import configuration
    from zylch.services.voice.current_time import CurrentTime

    conv, _, sent = make_conversation(monkeypatch)
    save(configuration() | {"tools": ["caller_memory", "get_current_time"]})
    conv.snapshot = snapshot_for_call(NUMBER)
    entered, release = asyncio.Event(), asyncio.Event()
    original = CurrentTime.execute

    async def delayed(self, **kwargs):
        entered.set()
        await release.wait()
        return await original(self, **kwargs)

    monkeypatch.setattr(CurrentTime, "execute", delayed)

    async def scenario():
        conv.start()
        await conv.lookup
        conv.event({"type": "session.input_transcript.delta", "delta": "Che ore sono a Roma?"})
        conv.event(delegation("old"))
        await entered.wait()
        conv.event({"type": "session.input_transcript.delta", "delta": " No, quali filtri?"})
        conv.event(delegation("new"))
        release.set()
        await until(lambda: conv.evidence["results_sent"] == 1)
        assert sent[-1]["delegation_id"] == "new"
        assert PUBLIC in sent[-1]["content"]
        assert not any("Current system-clock" in row["content"] for row in sent)
        await conv.close()
        before = list(sent)
        conv.event(delegation("late"))
        assert sent == before

    asyncio.run(scenario())


def test_unknown_caller_and_tracking_unavailable(fixture_db, monkeypatch):
    conv, _, sent = make_conversation(monkeypatch, caller="+399999999999")

    async def scenario():
        conv.start()
        await conv.lookup
        conv.event({"type": "session.input_transcript.delta", "delta": "Dov'è il tracking?"})
        conv.event(delegation("unknown"))
        await until(lambda: conv.evidence["results_sent"] == 1)
        assert PUBLIC not in str(sent) and FOLLOWUP not in str(sent)
        assert PUBLIC not in VOICE_RULES and FOLLOWUP not in VOICE_RULES
        assert "blue" not in VOICE_RULES.lower() and "thursday" not in VOICE_RULES.lower()
        assert "No live shipment or tracking lookup" in sent[-1]["content"]
        await conv.close()

    asyncio.run(scenario())


def test_append_preserves_multibyte_content():
    value = "è漢字 hello " * 800
    parts = list(chunks(value))
    assert "".join(parts) == value
    assert all(len(part.encode()) <= 480 for part in parts)


def test_fresh_clock_does_not_wait_for_caller_lookup(fixture_db, monkeypatch):
    from tests.voice.m2_fixture import configuration

    conv, _, sent = make_conversation(monkeypatch)
    save(configuration() | {"tools": ["caller_memory", "get_current_time"]})
    conv.snapshot = snapshot_for_call(NUMBER)
    gate = asyncio.Event()
    entered = asyncio.Event()
    original = conv.memory.execute

    async def delayed(**kwargs):
        entered.set()
        await gate.wait()
        return await original(**kwargs)

    conv.memory.execute = delayed

    async def scenario():
        conv.start()
        await entered.wait()
        conv.event({"type": "session.input_transcript.delta", "delta": "Che ore sono a Roma?"})
        conv.event(delegation("clock-before-memory"))
        await until(lambda: conv.evidence["results_sent"] == 1)
        assert not conv.lookup.done()
        assert "Europe/Rome" in sent[-1]["content"]
        await conv.close()

    asyncio.run(scenario())


def test_correction_during_send_preserves_new_delegation(fixture_db, monkeypatch):
    conv, _, sent = make_conversation(monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()

    async def paused_send(raw):
        data = json.loads(raw)
        if data["type"] == "session.commentary.append" and data["delegation_id"] == "old":
            entered.set()
            await release.wait()
        if conv.send_guard_revision is not None and conv.send_guard_revision != conv.revision:
            return False
        sent.append(data)

    conv.send = paused_send

    async def scenario():
        conv.start()
        await conv.lookup
        conv.event({"type": "session.input_transcript.delta", "delta": "Quali filtri?"})
        conv.event(delegation("old"))
        await entered.wait()
        conv.event({"type": "session.input_transcript.delta", "delta": " No, tracking?"})
        conv.event(delegation("new"))
        release.set()
        await until(lambda: conv.evidence["results_sent"] == 1)
        assert not any(r["delegation_id"] == "old" for r in sent)
        assert sent[-1]["delegation_id"] == "new"
        assert "No live shipment or tracking lookup" in sent[-1]["content"]
        assert conv.pending == []
        await conv.close()

    asyncio.run(scenario())
