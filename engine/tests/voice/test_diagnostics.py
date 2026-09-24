"""Private diagnostic evidence at the real conversation/tool boundary."""

import asyncio
import json
import sqlite3

import pytest

from tests.voice.helpers import delegation
from tests.voice.m2_fixture import PUBLIC, FOLLOWUP, INTERNAL, OTHER_FACT
from tests.voice.test_conversation import make_conversation, response, until
from zylch.services.voice.diagnostics import CallTrace, DiagnosticOptions


def records(root):
    path = next((root / "voice-diagnostics").glob("*.db"))
    with sqlite3.connect(path) as db:
        return [
            (kind, json.loads(data))
            for kind, data in db.execute("select kind,data from events order by seq")
        ]


def test_default_off_and_explicit_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_DIAGNOSTICS", "1")
    assert not DiagnosticOptions.load(tmp_path).enabled
    CallTrace(tmp_path, "call", 1, {}, DiagnosticOptions()).record("ignored", text="private")
    assert not (tmp_path / "voice-diagnostics").exists()
    (tmp_path / ".env").write_text("VOICE_DIAGNOSTICS=1\n")
    with pytest.raises(ValueError, match="isolated"):
        DiagnosticOptions.load(tmp_path)
    (tmp_path / ".env").write_text(
        "VOICE_DIAGNOSTICS=1\n"
        + "\n".join(
            f"{k}={tmp_path.name}"
            for k in ("OWNER_ID", "VOICE_SMOKE_TEST_PROFILE", "VOICE_ENGINE_ISOLATED_PROFILE")
        )
    )
    assert DiagnosticOptions.load(tmp_path).enabled
    (tmp_path / ".git").write_text("gitdir: elsewhere")
    with pytest.raises(ValueError, match="outside Git"):
        DiagnosticOptions.load(tmp_path)


def test_private_sink_redacts_and_refuses_symlinks(tmp_path):
    evidence = {}
    secret = "private-company-capability"
    trace = CallTrace(tmp_path, "call", 2, evidence, DiagnosticOptions(True, secrets=(secret,)))
    trace.record("safe", text=f"{secret} sk-test-secret eyJtest.signature.value")
    trace.close()
    assert evidence["diagnostics"] == "complete"
    directory = tmp_path / "voice-diagnostics"
    assert directory.stat().st_mode & 0o777 == 0o700
    assert next(directory.glob("*.db")).stat().st_mode & 0o777 == 0o600
    assert all(
        s not in str(records(tmp_path))
        for s in (secret, "sk-test-secret", "eyJtest.signature.value")
    )
    other = tmp_path / "other"
    other.mkdir()
    (other / "voice-diagnostics").symlink_to(directory, target_is_directory=True)
    failed = {}
    CallTrace(other, "call", 2, failed, DiagnosticOptions(True))
    assert failed["diagnostics"] == "incomplete"


def test_correlated_boundary_no_audio_or_unselected_facts(fixture_db, monkeypatch, tmp_path):
    conv, _, sent = make_conversation(monkeypatch, [response(tool={}), response(PUBLIC)])
    trace = CallTrace(
        tmp_path, "live-call", 1, conv.evidence, DiagnosticOptions(True, secrets=(fixture_db,))
    )
    conv.trace = conv.memory.trace = trace

    async def scenario():
        conv.start()
        conv.event(
            {
                "type": "session.output_transcript.delta",
                "delta": "Buongiorno",
                "start_ms": 0,
                "end_ms": 300,
            }
        )
        conv.event(
            {
                "type": "session.input_transcript.delta",
                "delta": "La richiesta precedente?",
                "start_ms": 100,
                "end_ms": 600,
            }
        )
        conv.event(delegation("d1"))
        await until(lambda: conv.evidence["results_sent"] == 1)
        append = sent[-1]
        conv.event(
            {
                "type": "session.commentary.appended",
                "client_event_id": append["event_id"],
                "start_ms": 800,
                "end_ms": 800,
                "secret": "must-not-persist",
            }
        )
        conv.event(
            {
                "type": "session.output_audio.delta",
                "delta": "RAW_AUDIO_MUST_NOT_PERSIST",
                "start_ms": 800,
                "end_ms": 900,
            }
        )
        conv.event(
            {
                "type": "session.output_transcript.delta",
                "delta": "Filtri blu",
                "start_ms": 810,
                "end_ms": 890,
            }
        )
        await conv.close()
        trace.close()

    asyncio.run(scenario())
    rows = records(tmp_path)
    content = str(rows)
    for forbidden in (
        INTERNAL,
        OTHER_FACT,
        fixture_db,
        "RAW_AUDIO_MUST_NOT_PERSIST",
        "must-not-persist",
    ):
        assert forbidden not in content
    assert PUBLIC in content and FOLLOWUP in content and "Filtri blu" in content
    tool = [d for k, d in rows if k == "memory_result" and d["run"]]
    assert tool and tool[0]["run"]["delegation_ids"] == ["d1"]
    assert all(d["call_id"] == "live-call" and d["config_revision"] == 1 for _, d in rows)
    ack = next(d for k, d in rows if k == "session.commentary.appended")
    assert any(k == "append_sent" and d["event_id"] == ack["client_event_id"] for k, d in rows)
    assert conv.evidence["diagnostics"] == "complete"


def test_capture_failure_preserves_conversation_cleanup(fixture_db, monkeypatch, tmp_path):
    conv, _, _ = make_conversation(monkeypatch, [response(PUBLIC)])
    trace = CallTrace(tmp_path, "call", 1, conv.evidence, DiagnosticOptions(True))
    trace.db.close()
    conv.trace = conv.memory.trace = trace

    async def scenario():
        conv.start()
        conv.event({"type": "session.input_transcript.delta", "delta": "filters"})
        conv.event(delegation("d1"))
        await until(lambda: conv.evidence["results_sent"] == 1)
        await conv.close()
        trace.close()

    asyncio.run(scenario())
    assert conv.closed and conv.evidence["diagnostics"] == "incomplete"


def test_delayed_memory_cancelled_without_late_result(fixture_db, monkeypatch, tmp_path):
    conv, client, sent = make_conversation(monkeypatch, [response(PUBLIC)])
    trace = CallTrace(tmp_path, "call", 1, conv.evidence, DiagnosticOptions(True))
    conv.trace = conv.memory.trace = trace
    conv.memory.diagnostic_delay = 5

    async def scenario():
        conv.start()
        conv.event(delegation("pending"))
        await asyncio.sleep(0)
        await conv.close()
        trace.close()

    asyncio.run(scenario())
    assert not sent and not client._client.messages.create.called
    kinds = [k for k, _ in records(tmp_path)]
    assert "memory_cancelled" in kinds and "memory_result" not in kinds


def test_injected_lookup_failure_has_no_facts(fixture_db, monkeypatch, tmp_path):
    conv, _, sent = make_conversation(monkeypatch, [response("Non posso verificare lo storico.")])
    trace = CallTrace(tmp_path, "call", 1, conv.evidence, DiagnosticOptions(True, fail_lookup=True))
    conv.trace = conv.memory.trace = trace
    conv.memory.diagnostic_failure = True

    async def scenario():
        conv.start()
        conv.event({"type": "session.input_transcript.delta", "delta": "Quali filtri?"})
        conv.event(delegation("failed-lookup"))
        await until(lambda: conv.evidence["results_sent"] == 1)
        assert conv.context["facts"] == []
        assert "unavailable" in str(conv.context)
        await conv.close()
        trace.close()

    asyncio.run(scenario())
    content = str(records(tmp_path))
    assert PUBLIC not in content and FOLLOWUP not in content
    assert "unavailable" in content
    assert "Non posso verificare" in str(sent)


def test_diagnostic_close_failure_preserves_final_ledger(fixture_db, monkeypatch, tmp_path):
    from unittest.mock import Mock
    from aiohttp.test_utils import TestClient, TestServer
    from tests.voice.helpers import finished
    from tests.voice.test_engine_runtime import setup_runtime, admit
    from zylch.services.voice.live_sip_smoke import create_app

    _, client, _ = make_conversation(monkeypatch, [response(PUBLIC)])
    config, ledger, transport, runtime, _ = setup_runtime(tmp_path, monkeypatch, client)

    async def scenario():
        async with TestClient(
            TestServer(create_app(runtime, lambda body, _: json.loads(body)))
        ) as http:
            await admit(http, config)
            await transport.entered.wait()
            call = runtime.call
            call.trace = Mock()
            call.trace.close.side_effect = OSError("private error")
            transport.socket.events.put_nowait({"type": "session.closed", "usage": {"seconds": 3}})
            await finished(runtime)
            assert runtime.call is None
            row = ledger.rows()[0]
            assert row["state"] == "closed" and row["reserved_microusd"] > 0
            assert json.loads(row["evidence"])["diagnostics"] == "incomplete"
            assert json.loads(row["evidence"])["voice_seconds"] == 3
        ledger.close()

    asyncio.run(scenario())
