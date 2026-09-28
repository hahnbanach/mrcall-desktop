"""Private, rebuildable production call transcripts sourced only from provider deltas."""

import json
import os
import re
import sqlite3
import stat
from datetime import datetime, timezone
from pathlib import Path


def _utc(value=None):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value else datetime.now(timezone.utc).isoformat()


class CallSessions:
    """One local session per funded production ledger call, never a remote upload."""

    def __init__(self, profile: Path, owner: str, business_id: str, called: str):
        if profile.name != owner or not business_id or not (profile / "zylch.db").is_file():
            raise ValueError("Production transcript binding invalid")
        if any((parent / ".git").exists() for parent in (profile, *profile.parents)):
            raise ValueError("Production transcripts must remain outside Git")
        self.profile = profile
        self.owner = owner
        self.business_id = business_id
        self.called = called
        self.path = profile / "sessions.db"
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("Private transcript file required")
        finally:
            os.close(fd)
        self.db = sqlite3.connect(self.path, timeout=2)
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS sessions ("
            "id TEXT PRIMARY KEY, start_timestamp TEXT NOT NULL, timestamp TEXT NOT NULL, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, owner TEXT NOT NULL, "
            "business_id TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)))"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS sessions_business_start "
            "ON sessions(business_id, start_timestamp)"
        )
        self.db.commit()
        other = self.db.execute(
            "SELECT 1 FROM sessions WHERE owner<>? OR business_id<>? LIMIT 1",
            (owner, business_id),
        ).fetchone()
        if other:
            self.db.close()
            raise ValueError("Production transcript binding changed")

    def _write(self, session_id, started, data):
        if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", session_id):
            raise ValueError("Invalid voice session ID")
        now = _utc()
        start = _utc(started)
        payload = json.dumps(data, ensure_ascii=False, allow_nan=False)
        with self.db:
            self.db.execute(
                "INSERT INTO sessions (id,start_timestamp,timestamp,created_at,updated_at,"
                "owner,business_id,data) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET timestamp=excluded.timestamp, "
                "updated_at=excluded.updated_at, data=excluded.data "
                "WHERE sessions.owner=excluded.owner AND sessions.business_id=excluded.business_id",
                (session_id, start, now, now, now, self.owner, self.business_id, payload),
            )

    def begin(self, session_id, *, started=None, caller=None):
        data = {
            "conversation_transcription": [], "called_number": self.called,
            "caller_number": caller if isinstance(caller, str) and re.fullmatch(r"\+[1-9][0-9]{7,14}", caller) else None,
            "capture_status": "recording", "possible_pre_attach_gap": True,
        }
        self._write(session_id, started, data)

    def sync(self, session_id, path: Path, *, status="recording", started=None, caller=None, duration_ms=None):
        directory = self.profile / "voice-diagnostics"
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Private transcript source directory required")
        if path.parent != directory or not re.fullmatch(r"call-[0-9a-f]{32}\.db", path.name):
            raise ValueError("Invalid transcript source")
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Private transcript source required")
        source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = source.execute(
                "SELECT role,delta FROM transcript_deltas ORDER BY seq"
            ).fetchall()
        finally:
            source.close()
        messages = []
        for role, delta in rows:
            if role not in ("caller", "voice") or not isinstance(delta, str):
                raise ValueError("Invalid provider transcript delta")
            mapped = "user" if role == "caller" else "assistant"
            if messages and messages[-1]["role"] == mapped:
                messages[-1]["content"] += delta
            else:
                messages.append({"role": mapped, "content": delta})
        previous = self.db.execute("SELECT start_timestamp,data FROM sessions WHERE id=?", (session_id,)).fetchone()
        data = json.loads(previous[1]) if previous else {
            "called_number": self.called, "caller_number": caller,
        }
        data.update(
            conversation_transcription=messages,
            capture_status=status if messages or status in ("recording", "incomplete") else "no_provider_text",
            possible_pre_attach_gap=True,
        )
        if duration_ms is not None:
            data["duration_ms"] = duration_ms
        self._write(session_id, started or (datetime.fromisoformat(previous[0]).timestamp() if previous else None), data)

    def recover(self, ledger_rows):
        """Replay each private source and represent old funded calls without text."""
        sources = {}
        directory = self.profile / "voice-diagnostics"
        if directory.exists():
            for path in directory.glob("call-*.db"):
                try:
                    info = path.lstat()
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                        continue
                    source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                    try:
                        record = source.execute(
                            "SELECT data FROM events WHERE kind='call_attached' ORDER BY seq LIMIT 1"
                        ).fetchone()
                        has_deltas = source.execute(
                            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='transcript_deltas'"
                        ).fetchone() is not None
                    finally:
                        source.close()
                    session_id = json.loads(record[0]).get("call_id") if record else None
                    if isinstance(session_id, str) and has_deltas:
                        sources[session_id] = path
                except (sqlite3.Error, ValueError, OSError, TypeError):
                    continue
        for row in ledger_rows:
            session_id = row["session_id"]
            if not row["reserved_microusd"] or session_id.startswith("vonage:"):
                continue
            started = row["started_at"]
            evidence = json.loads(row["evidence"] or "{}")
            path = sources.get(session_id)
            if path:
                status = evidence.get("transcript_capture") or "incomplete"
                if row["state"] not in ("closed", "stopped"):
                    status = "incomplete"
                self.sync(session_id, path, status=status, started=started,
                          duration_ms=evidence.get("observed_elapsed_ms"))
            elif not self.db.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone():
                self._write(session_id, started, {
                    "conversation_transcription": [], "called_number": self.called,
                    "caller_number": None, "capture_status": "legacy_no_text",
                    "possible_pre_attach_gap": True,
                })
            else:
                existing = json.loads(self.db.execute(
                    "SELECT data FROM sessions WHERE id=?", (session_id,)
                ).fetchone()[0])
                if existing.get("capture_status") == "recording":
                    existing["capture_status"] = "incomplete"
                    self._write(session_id, started, existing)

    def close(self):
        self.db.close()
