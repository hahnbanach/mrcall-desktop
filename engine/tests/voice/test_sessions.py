"""Durable production transcript archive, with the private delta file as source."""

import json
import sqlite3

import pytest

from zylch.services.voice.diagnostics import CallTrace, DiagnosticOptions
from zylch.services.voice.sessions import CallSessions


def archive(tmp_path):
    profile = tmp_path / "owner-uid"
    profile.mkdir()
    (profile / "zylch.db").touch()
    return profile, CallSessions(profile, profile.name, "exact-business", "+390250552776")


def read(archive, session_id):
    row = archive.db.execute(
        "SELECT owner,business_id,data FROM sessions WHERE id=?", (session_id,)
    ).fetchone()
    return row[:2], json.loads(row[2])


def test_deltas_are_ordered_private_and_replayable(tmp_path):
    profile, sessions = archive(tmp_path)
    sessions.begin("call-1", started=100, caller="+390212345678")
    evidence = {"finalization": "confirmed"}
    trace = CallTrace(profile, "call-1", 6, evidence, DiagnosticOptions(True), sessions)
    for role, text in (("caller", "Buon"), ("caller", "giorno"),
                       ("voice", "Salve"), ("caller", "Grazie")):
        assert trace.record_transcript(role, text)
    trace.close()
    identity, data = read(sessions, "call-1")
    assert identity == ("owner-uid", "exact-business")
    assert data["conversation_transcription"] == [
        {"role": "user", "content": "Buongiorno"},
        {"role": "assistant", "content": "Salve"},
        {"role": "user", "content": "Grazie"},
    ]
    assert data["possible_pre_attach_gap"] is True
    assert sessions.path.stat().st_mode & 0o777 == 0o600
    assert not list(profile.glob("sessions.db-*"))
    sessions.close()
    replay = CallSessions(profile, "owner-uid", "exact-business", "+390250552776")
    rows = [{"session_id": "call-1", "reserved_microusd": 10_000_000,
             "started_at": 100, "state": "closed",
             "evidence": json.dumps({"transcript_capture": "deltas_observed"})}]
    replay.recover(rows)
    replay.recover(rows)
    assert replay.db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1
    assert read(replay, "call-1")[1]["conversation_transcription"] == data["conversation_transcription"]
    replay.close()


def test_legacy_empty_partial_and_binding(tmp_path):
    profile, sessions = archive(tmp_path)
    old_trace_dir = profile / "voice-diagnostics"
    old_trace_dir.mkdir(mode=0o700)
    old_trace = old_trace_dir / ("call-" + "a" * 32 + ".db")
    with sqlite3.connect(old_trace) as db:
        db.execute("CREATE TABLE events (seq INTEGER PRIMARY KEY, kind TEXT, data TEXT)")
        db.execute("INSERT INTO events (kind,data) VALUES (?,?)", (
            "call_attached", json.dumps({"call_id": "old-call"}),
        ))
    old_trace.chmod(0o600)
    sessions.recover([{"session_id": "old-call", "reserved_microusd": 10_000_000,
                       "started_at": 100, "state": "closed", "evidence": "{}"}])
    assert read(sessions, "old-call")[1]["capture_status"] == "legacy_no_text"
    assert read(sessions, "old-call")[1]["conversation_transcription"] == []
    sessions.begin("empty-call")
    trace = CallTrace(profile, "empty-call", 6, {}, DiagnosticOptions(True), sessions)
    trace.close()
    assert read(sessions, "empty-call")[1]["capture_status"] == "no_provider_text"
    sessions.begin("partial-call")
    trace = CallTrace(profile, "partial-call", 6, {}, DiagnosticOptions(True), sessions)
    trace.record_transcript("voice", "Frammento")
    sessions.close()
    replay = CallSessions(profile, "owner-uid", "exact-business", "+390250552776")
    replay.recover([{"session_id": "partial-call", "reserved_microusd": 10_000_000,
                     "started_at": 101, "state": "uncertain", "evidence": "{}"}])
    assert read(replay, "partial-call")[1]["capture_status"] == "incomplete"
    assert read(replay, "partial-call")[1]["conversation_transcription"] == [
        {"role": "assistant", "content": "Frammento"}
    ]
    replay.close()
    with pytest.raises(ValueError, match="binding"):
        CallSessions(profile, "other-owner", "exact-business", "+390250552776")
    with pytest.raises(ValueError, match="binding"):
        CallSessions(profile, "owner-uid", "different-business", "+390250552776")


def test_refuses_nonprivate_or_symlinked_archive(tmp_path):
    profile, sessions = archive(tmp_path)
    sessions.close()
    sessions.path.chmod(0o644)
    with pytest.raises(ValueError, match="Private"):
        CallSessions(profile, profile.name, "exact-business", "+390250552776")
    sessions.path.unlink()
    target = tmp_path / "target"
    target.touch()
    sessions.path.symlink_to(target)
    with pytest.raises(OSError):
        CallSessions(profile, profile.name, "exact-business", "+390250552776")
