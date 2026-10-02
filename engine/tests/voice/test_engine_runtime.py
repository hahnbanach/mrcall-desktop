"""Signed ingress, selected context and closure without a telephone LLM client."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests.voice.helpers import Transport, delegation, finished, incoming, config_for, Socket
from tests.voice.m2_fixture import KNOWN, NUMBER, SHARED, configuration, PUBLIC
from tests.voice.test_agent_config import save
from tests.voice.test_conversation import until
from tests.voice.test_vonage import CARRIER, signed
from zylch.services.voice import company_query, engine_runtime
from zylch.services.voice.company_notes import DetailResult, NotesView
from zylch.services.voice.conversation import Conversation, VOICE_RULES
from zylch.services.voice.caller_memory import CallerMemory
from zylch.services.voice.agent_config import snapshot_for_call
from zylch.services.voice.company_query import CompanyQuery
from zylch.services.voice.engine_runtime import PreparedCall
from zylch.services.voice.diagnostics import DiagnosticOptions
from zylch.services.voice.sessions import CallSessions
from zylch.services.voice.live_sip_smoke import create_app
from zylch.services.voice.smoke_runtime import Call
from zylch.storage.voice_smoke import SmokeLedger


class VoiceTransport(Transport):
    def __init__(self):
        super().__init__()
        self.instructions = []

    async def accept(self, session, instructions=None):
        self.instructions.append(instructions)
        return await super().accept(session)


def setup_runtime(tmp_path, monkeypatch, client=None, **changes):
    config = config_for(tmp_path, test_number=NUMBER, **CARRIER, **changes)
    ledger = SmokeLedger(
        config.profile / "voice-smoke.db",
        config.policy_id,
        config.reservation_microusd,
        config.max_calls,
        unlimited=config.unlimited,
    )
    transport = VoiceTransport()
    transport.ledger = ledger
    runtime = engine_runtime.EngineVoiceRuntime(config, ledger, transport)
    runtime.finalization_timeout = 0.01
    prepare = AsyncMock(return_value=None)
    monkeypatch.setattr(engine_runtime, "prepare_call", prepare)
    return config, ledger, transport, runtime, prepare


def enable_test_production_archive(runtime):
    profile = runtime.config.profile
    (profile / "zylch.db").touch()
    object.__setattr__(runtime.config, "company_knowledge_enabled", True)
    runtime.production = True
    runtime.sessions = CallSessions(profile, profile.name, "business-1", NUMBER)


async def admit(http, config, caller=KNOWN, carrier="carrier-1", session="session-1"):
    body = json.dumps({"to": NUMBER, "from": caller, "uuid": carrier}).encode()
    result = await http.post("/vonage/answer", data=body, headers=signed(body))
    assert result.status == 200
    ncco = await result.json()
    if not ncco:
        return None
    token = ncco[0]["endpoint"][0]["headers"]["Mrcall-Smoke-Attempt"]
    event = incoming(session, to=config.sip_to_uri)
    event["data"]["sip_headers"] += [
        {"name": "X-Mrcall-Smoke-Attempt", "value": token},
        {"name": "From", "value": "sip:+393330000002@attacker.invalid"},
    ]
    result = await http.post("/openai/live", json=event)
    assert result.status == 200
    return ncco


def test_full_lifecycle_snapshot_and_followup(fixture_db, tmp_path, monkeypatch):
    save()
    config, ledger, transport, runtime, prepare = setup_runtime(tmp_path, monkeypatch)

    async def scenario():
        async with TestClient(
            TestServer(create_app(runtime, lambda body, _: json.loads(body)))
        ) as http:
            await admit(http, config, caller=KNOWN.removeprefix("+"))
            await transport.entered.wait()
            first = runtime.call
            assert first.conversation.memory.caller_number == KNOWN
            await first.conversation.lookup
            assert first.conversation.context["recognition"] == "matched"
            assert len(first.conversation.context["facts"]) == 2
            assert transport.instructions[0].endswith(VOICE_RULES)
            assert "sole conversational assistant" in transport.instructions[0]
            assert first.evidence["delegated_engine_model"] is None
            save(configuration() | {"instructions": "NEXT CALL ONLY"})
            assert "NEXT CALL ONLY" not in transport.instructions[0]
            transport.socket.events.put_nowait(
                {"type": "session.input_transcript.delta", "delta": "filters"}
            )
            transport.socket.events.put_nowait(delegation("first"))
            await until(lambda: first.evidence["results_sent"] == 1)
            assert PUBLIC in str(transport.socket.sent)
            transport.socket.events.put_nowait({"type": "session.closed", "usage": {"seconds": 3}})
            await finished(runtime)
            assert ledger.rows()[0]["state"] == "closed"
            assert KNOWN not in str(ledger.rows())
            transport.socket, transport.entered = Socket(), asyncio.Event()
            await admit(http, config, carrier="carrier-2", session="session-2")
            await transport.entered.wait()
            assert "NEXT CALL ONLY" in transport.instructions[1]
            transport.socket.events.put_nowait({"type": "session.closed", "usage": {"seconds": 1}})
            await finished(runtime)
            assert prepare.await_count == 2
            assert await admit(http, config, carrier="carrier-3", session="session-3") is None
            assert len(ledger.rows()) == 2
        ledger.close()

    asyncio.run(scenario())


def test_production_greeting_uses_only_approved_name(fixture_db, tmp_path, monkeypatch):
    from tests.voice.m2_fixture import OWNER

    monkeypatch.setenv("VOICE_PRODUCTION_OWNER_UID", OWNER)
    monkeypatch.setenv("VOICE_PRODUCTION_BUSINESS_ID", "business-1")
    monkeypatch.setenv("VOICE_PRODUCTION_NUMBER", NUMBER)
    save(
        configuration()
        | {
            "policy": "production",
            "business_id": "business-1",
            "limits": None,
            "customers": [{"blob_id": "customer-a", "display_name": "Mario"}],
        }
    )
    _, ledger, transport, runtime, _ = setup_runtime(tmp_path, monkeypatch)
    enable_test_production_archive(runtime)
    runtime.diagnostics = DiagnosticOptions(True)
    runtime._prepare = AsyncMock(return_value=None)
    runtime._meter = AsyncMock()
    runtime._watch_binding = AsyncMock()
    view = NotesView(
        "supported",
        "Services: source-backed fixture service",
        "f" * 64,
        ("Public price unavailable",),
        (("services", 0, 15),),
    )
    monkeypatch.setattr(engine_runtime, "current_company_notes", lambda *_: view)
    monkeypatch.setattr(company_query, "current_company_notes", lambda *_: view)
    monkeypatch.setattr(
        company_query,
        "company_note_detail",
        lambda *a, **k: DetailResult(
            "supported",
            "Collection is by appointment.",
            "f" * 64,
            "process",
            "collection",
            18,
            47,
        ),
    )
    snapshot = snapshot_for_call(NUMBER)

    async def capture(_session, instructions):
        transport.instructions.append(instructions)
        return True

    transport.accept = capture

    async def scenario():
        for caller in (KNOWN, SHARED, None):
            call = Call("session-test", prepared=PreparedCall(snapshot, caller))
            assert await runtime.accept_call(call)
            assert call.trace.db is not None
            assert call.evidence["company_note_source_hash"] == "f" * 64
            assert call.evidence["company_note_included_spans"] == (("services", 0, 15),)
            assert call.evidence["company_note_omissions"] == ("Public price unavailable",)
            if caller == KNOWN:
                runtime.attached(call, transport.socket)
                await call.conversation.lookup
                runtime.event(
                    call,
                    {"type": "session.input_transcript.delta", "delta": "Come funziona il ritiro?"},
                )
                runtime.event(call, delegation("company-detail"))
                await until(lambda: call.evidence["results_sent"] == 1)
                assert any(
                    row["type"] == "session.commentary.append"
                    and "Collection is by appointment." in row["content"]
                    for row in transport.socket.sent
                )
                assert call.evidence["company_detail_evidence"][0]["start"] == 18
                await call.conversation.close()
            call.trace.close()

    asyncio.run(scenario())
    assert "Buongiorno Mario, sono l'assistente di Café 124" in transport.instructions[0]
    assert "Buongiorno, sono l'assistente di Café 124" in transport.instructions[1]
    assert "Buongiorno, sono l'assistente di Café 124" in transport.instructions[2]
    assert all("source-backed fixture service" in text for text in transport.instructions)
    assert PUBLIC not in str(transport.instructions)
    assert all("Wait silently for the backend" in text for text in transport.instructions)

    object.__setattr__(runtime.config, "company_knowledge_enabled", False)
    monkeypatch.setattr(
        engine_runtime,
        "current_company_notes",
        lambda *_: pytest.fail("disabled company path read notes"),
    )
    disabled = Call("session-company-disabled", prepared=PreparedCall(snapshot, KNOWN))
    assert asyncio.run(runtime.accept_call(disabled))
    assert "source-backed fixture service" not in transport.instructions[-1]
    assert "Verified company services are unavailable" not in transport.instructions[-1]
    assert "company_note_status" not in disabled.evidence
    disabled.trace.close()

    runtime.diagnostics = DiagnosticOptions()
    refused = Call("session-no-transcript", prepared=PreparedCall(snapshot, KNOWN))
    with pytest.raises(ValueError, match="transcript unavailable"):
        asyncio.run(runtime.accept_call(refused))
    assert len(transport.instructions) == 4
    ledger.close()


def test_production_name_is_withheld_if_binding_changes_during_lookup(
    fixture_db, tmp_path, monkeypatch
):
    from tests.voice.m2_fixture import OWNER

    monkeypatch.setenv("VOICE_PRODUCTION_OWNER_UID", OWNER)
    monkeypatch.setenv("VOICE_PRODUCTION_BUSINESS_ID", "business-1")
    monkeypatch.setenv("VOICE_PRODUCTION_NUMBER", NUMBER)
    save(
        configuration()
        | {
            "policy": "production",
            "business_id": "business-1",
            "limits": None,
            "customers": [{"blob_id": "customer-a", "display_name": "Mario"}],
        }
    )
    _, ledger, transport, runtime, _ = setup_runtime(tmp_path, monkeypatch)
    enable_test_production_archive(runtime)
    runtime._prepare = AsyncMock(side_effect=[None, ValueError("binding changed")])
    call = Call("session-test", prepared=PreparedCall(snapshot_for_call(NUMBER), KNOWN))
    with pytest.raises(ValueError, match="binding changed"):
        asyncio.run(runtime.accept_call(call))
    assert transport.instructions == []
    ledger.close()


def test_production_name_is_withheld_if_config_changes_during_lookup(
    fixture_db, tmp_path, monkeypatch
):
    from tests.voice.m2_fixture import OWNER

    monkeypatch.setenv("VOICE_PRODUCTION_OWNER_UID", OWNER)
    monkeypatch.setenv("VOICE_PRODUCTION_BUSINESS_ID", "business-1")
    monkeypatch.setenv("VOICE_PRODUCTION_NUMBER", NUMBER)
    save(
        configuration()
        | {
            "policy": "production",
            "business_id": "business-1",
            "limits": None,
            "customers": [{"blob_id": "customer-a", "display_name": "Mario"}],
        }
    )
    _, ledger, transport, runtime, _ = setup_runtime(tmp_path, monkeypatch)
    enable_test_production_archive(runtime)
    runtime._prepare = AsyncMock(return_value=None)
    snapshot = snapshot_for_call(NUMBER)
    monkeypatch.setattr(
        engine_runtime,
        "snapshot_for_call",
        lambda _: SimpleNamespace(revision=snapshot.revision + 1),
    )
    call = Call("session-test", prepared=PreparedCall(snapshot, KNOWN))
    with pytest.raises(ValueError, match="configuration changed"):
        asyncio.run(runtime.accept_call(call))
    assert transport.instructions == []
    ledger.close()


@pytest.mark.parametrize("failure", ["disabled", "binding", "budget", "count", "unprepared"])
def test_no_admission_on_failed_readiness(fixture_db, tmp_path, monkeypatch, failure):
    save()
    config, ledger, transport, runtime, prepare = setup_runtime(tmp_path, monkeypatch)
    if failure == "disabled":
        save(configuration() | {"enabled": False})
    elif failure == "binding":
        prepare.side_effect = ValueError("binding unavailable")
    elif failure == "budget":
        save(configuration() | {"limits": {"budget_microusd": 1}})
    elif failure == "count":
        save(configuration() | {"limits": {"max_calls": 1}})
        ledger.admit("earlier", allowed=True)
        ledger.finish("earlier", "closed")

    async def scenario():
        async with TestClient(
            TestServer(create_app(runtime, lambda body, _: json.loads(body)))
        ) as http:
            if failure == "unprepared":
                result = await http.post("/openai/live", json=incoming(to=config.sip_to_uri))
                assert result.status == 200
                await finished(runtime)
            else:
                assert await admit(http, config) is None
            assert not transport.accept_calls
        ledger.close()

    asyncio.run(scenario())


def test_watchdog_cancels_lookup_and_keeps_ledger(fixture_db, tmp_path, monkeypatch):
    save(configuration() | {"limits": {"duration_seconds": 1}})
    config, ledger, transport, runtime, _ = setup_runtime(tmp_path, monkeypatch)

    async def scenario():
        async with TestClient(
            TestServer(create_app(runtime, lambda body, _: json.loads(body)))
        ) as http:
            await admit(http, config)
            await transport.entered.wait()
            call = runtime.call
            await finished(runtime)
            assert call.conversation.closed
            assert ledger.rows()[0]["state"] == "stopped"
        ledger.close()

    asyncio.run(scenario())


def test_company_query_rejects_changed_converter_view(monkeypatch):
    original = NotesView("supported", source_hash="same-source", cache_key="old-converter")
    rebuilt = NotesView("supported", source_hash="same-source", cache_key="new-converter")
    monkeypatch.setattr(company_query, "current_company_notes", lambda *_: rebuilt)
    resolver = CompanyQuery(None, object(), original)
    assert not resolver.current()
    monkeypatch.setattr(company_query, "current_company_notes", lambda *_: original)
    assert resolver.current()


def test_company_query_uses_bound_detail_and_exact_missing_state(monkeypatch):
    view = NotesView("supported", "Services: Acme sells blue widgets.", "f" * 64)
    observed = []
    exact_calls = []

    def detail(profile, snapshot, query, expected_source_hash=None):
        observed.append(expected_source_hash)
        if "consegnate" in query.lower() or query == "delivery schedule":
            return DetailResult(
                "supported",
                "We deliver weekly.",
                "f" * 64,
                "process",
                "delivery schedule",
                45,
                63,
            )
        if "ambiguous" in query.lower():
            return DetailResult("ambiguous")
        if "outage" in query.lower():
            return DetailResult("unavailable")
        return DetailResult("missing")

    monkeypatch.setattr(company_query, "company_note_detail", detail)

    def exact(profile, snapshot, category, key, expected_source_hash):
        exact_calls.append((category, key, expected_source_hash))
        return DetailResult("supported", "We deliver weekly.", "f" * 64, category, key, 45, 63)

    monkeypatch.setattr(company_query, "company_note_detail_exact", exact)
    resolver = CompanyQuery(None, object(), view)
    answer, evidence, personal = resolver("Quando consegnate?")
    assert "We deliver weekly." in answer and not personal
    assert evidence["source_hash"] == "f" * 64 and evidence["key"] == "delivery schedule"
    assert "which company detail" in resolver("E per quello?")[0]
    resolver.commit(evidence)
    assert "We deliver weekly." in resolver("E per quello?")[0]
    assert exact_calls[-1] == ("process", "delivery schedule", "f" * 64)
    monkeypatch.setattr(
        company_query, "company_note_detail_exact", lambda *a, **k: DetailResult("unavailable")
    )
    assert "unavailable" in resolver("E per quello?")[0]
    assert "which company detail" in resolver("E per quello?")[0]
    monkeypatch.setattr(company_query, "company_note_detail_exact", exact)
    assert "We deliver weekly." in resolver("Quando consegnate?")[0]
    assert "public price is unavailable" in resolver("What is the price?")[0]
    assert "which company detail" in resolver("E per quello?")[0]
    invented = resolver("Offrite draghi?")[0]
    assert "Acme sells blue widgets." in invented
    assert "draghi" not in invented and "not established" in invented
    assert "Current supported company context" not in invented
    assert "not established" not in resolver("Offrite blue widgets?")[0]
    assert "variant or option details are unavailable" in resolver("Quali varianti avete?")[0]
    assert resolver.public_only("Quali varianti avete?")
    assert not resolver.public_only("Cosa mi avete scritto ieri?")
    assert resolver("Cosa mi avete scritto ieri?") is None
    assert not resolver.public_only("Do you have my data?")
    assert resolver("Do you have my data?") is None
    assert "ordering procedure is unavailable" in resolver("Come faccio un ordine?")[0]
    assert resolver.public_only("Come faccio un ordine?")
    assert resolver("Come faccio un ordine e quali servizi offrite?")[2] is False
    assert resolver("Quali servizi e le nostre email?")[2] is True
    assert resolver("Quando consegnate il mio ordine?")[2] is True
    assert "ambiguous" in resolver("ambiguous")[0]
    assert "unavailable" in resolver("outage")[0]
    assert resolver("Tell me a joke") is None
    unavailable = CompanyQuery(None, object(), NotesView("unavailable"))
    assert "unavailable" in unavailable("Quali servizi?")[0]


def test_public_company_question_does_not_wait_for_caller_lookup(fixture_db, monkeypatch):
    save()
    snapshot = snapshot_for_call(NUMBER)
    memory = CallerMemory(snapshot, KNOWN)
    original = memory.execute
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(**kwargs):
        entered.set()
        await release.wait()
        return await original(**kwargs)

    memory.execute = delayed
    monkeypatch.setattr(
        company_query, "company_note_detail", lambda *args, **kwargs: DetailResult("missing")
    )
    monkeypatch.setattr(
        company_query,
        "current_company_notes",
        lambda *args, **kwargs: NotesView("supported", "Services: Acme widgets.", "f" * 64),
    )
    sent = []

    async def send(raw):
        sent.append(json.loads(raw))

    conv = Conversation(
        snapshot,
        memory,
        send,
        {},
        company_lookup=CompanyQuery(
            None, snapshot, NotesView("supported", "Services: Acme widgets.", "f" * 64)
        ),
    )

    async def scenario():
        conv.start()
        await entered.wait()
        conv.event({"type": "session.input_transcript.delta", "delta": "Quali varianti avete?"})
        conv.event(delegation("public"))
        await until(lambda: conv.evidence["results_sent"] == 1)
        assert not conv.lookup.done()
        assert "variant or option details are unavailable" in sent[-1]["content"]
        release.set()
        await conv.close()

    asyncio.run(scenario())


def test_discarded_detail_cannot_seed_deictic_followup(fixture_db, monkeypatch):
    save()
    snapshot = snapshot_for_call(NUMBER)
    view = NotesView("supported", "Services: Acme widgets.", "f" * 64)

    def detail(profile, bound, query, expected_source_hash=None):
        if "consegnate" in query.lower():
            return DetailResult(
                "supported", "We deliver weekly.", "f" * 64, "process", "delivery schedule", 45, 63
            )
        return DetailResult("missing")

    monkeypatch.setattr(company_query, "company_note_detail", detail)
    monkeypatch.setattr(company_query, "current_company_notes", lambda *_: view)
    sent = []
    entered, release = asyncio.Event(), asyncio.Event()

    async def send(raw):
        data = json.loads(raw)
        if data["type"] == "session.commentary.append" and data["delegation_id"] == "old":
            entered.set()
            await release.wait()
        if conv.send_guard_revision is not None and conv.send_guard_revision != conv.revision:
            return False
        sent.append(data)

    conv = Conversation(
        snapshot,
        CallerMemory(snapshot, None),
        send,
        {},
        company_lookup=CompanyQuery(None, snapshot, view),
    )

    async def scenario():
        conv.start()
        await conv.lookup
        conv.event({"type": "session.input_transcript.delta", "delta": "Quando consegnate?"})
        conv.event(delegation("old"))
        await entered.wait()
        conv.event({"type": "session.input_transcript.delta", "delta": " No, quali servizi?"})
        conv.event(delegation("new"))
        release.set()
        await until(lambda: conv.evidence["results_sent"] == 1)
        conv.event({"type": "session.output_transcript.delta", "delta": "Okay."})
        conv.event({"type": "session.input_transcript.delta", "delta": "E per quello?"})
        conv.event(delegation("followup"))
        await until(lambda: conv.evidence["results_sent"] == 2)
        assert sent[-1]["delegation_id"] == "followup"
        assert "which company detail" in sent[-1]["content"]
        assert "We deliver weekly." not in str(sent)
        await conv.close()

    asyncio.run(scenario())
