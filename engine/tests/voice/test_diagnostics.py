"""Private diagnostic evidence at the real conversation/tool boundary."""

import asyncio
import json
import sqlite3

import pytest

from tests.voice.helpers import delegation
from tests.voice.m2_fixture import PUBLIC, FOLLOWUP, INTERNAL, OTHER_FACT
from tests.voice.test_conversation import make_conversation, until
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


def test_spoken_transcript_is_private_product_record_not_debug_event(tmp_path):
    secret = "sk-live-spoken-test-key"
    evidence = {"finalization": "confirmed"}
    trace = CallTrace(tmp_path, "live-call", 6, evidence, DiagnosticOptions(True, secrets=(secret,)))
    trace.record("session.input_transcript.delta", characters=12)
    trace.record_transcript("caller", f"Il mio codice è {secret}", start_ms=10, end_ms=60)
    trace.record_transcript("voice", "Posso aiutarti.", start_ms=70, end_ms=100)
    trace.close()

    path = next((tmp_path / "voice-diagnostics").glob("*.db"))
    assert path.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(path) as db:
        rows = db.execute(
            "select role,delta,start_ms,end_ms from transcript_deltas order by seq"
        ).fetchall()
        events = db.execute("select data from events").fetchall()
    assert rows == [
        ("caller", f"Il mio codice è {secret}", 10, 60),
        ("voice", "Posso aiutarti.", 70, 100),
    ]
    assert secret not in str(events)
    assert evidence["diagnostics"] == "complete"
    assert evidence["transcript_capture"] == "deltas_observed"


def test_transcript_status_marks_partial_and_missing_provider_text(tmp_path):
    partial = {"finalization": "confirmed"}
    trace = CallTrace(tmp_path, "partial", 1, partial, DiagnosticOptions(True))
    trace.record("session.output_audio.delta")
    assert trace.record_transcript("caller", "Ciao")
    trace.close()
    assert partial["transcript_capture"] == "possible_gap"

    empty = {"finalization": "confirmed"}
    trace = CallTrace(tmp_path, "empty", 1, empty, DiagnosticOptions(True))
    trace.close()
    assert empty["transcript_capture"] == "no_provider_text"


def test_correlated_boundary_no_audio_or_unselected_facts(fixture_db, monkeypatch, tmp_path):
    conv, _, sent = make_conversation(monkeypatch)
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
    assert any(k == "delegated_work_started" and d["delegation_id"] == "d1" for k, d in rows)
    assert all(d["call_id"] == "live-call" and d["config_revision"] == 1 for _, d in rows)
    ack = next(d for k, d in rows if k == "session.commentary.appended")
    assert any(k == "append_sent" and d["event_id"] == ack["client_event_id"] for k, d in rows)
    assert conv.evidence["diagnostics"] == "complete"


def test_capture_failure_preserves_conversation_cleanup(fixture_db, monkeypatch, tmp_path):
    conv, _, _ = make_conversation(monkeypatch)
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
    conv, _, sent = make_conversation(monkeypatch)
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
    assert not sent
    kinds = [k for k, _ in records(tmp_path)]
    assert "memory_cancelled" in kinds and "memory_result" not in kinds


def test_injected_lookup_failure_has_no_facts(fixture_db, monkeypatch, tmp_path):
    conv, _, sent = make_conversation(monkeypatch)
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
    assert "No authorized customer facts" in str(sent)


def test_diagnostic_close_failure_preserves_final_ledger(fixture_db, monkeypatch, tmp_path):
    from unittest.mock import Mock
    from aiohttp.test_utils import TestClient, TestServer
    from tests.voice.helpers import finished
    from tests.voice.test_engine_runtime import setup_runtime, admit
    from zylch.services.voice.live_sip_smoke import create_app

    from tests.voice.test_agent_config import save

    save()
    config, ledger, transport, runtime, _ = setup_runtime(tmp_path, monkeypatch)

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
