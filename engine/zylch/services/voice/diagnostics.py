"""Opt-in isolated call diagnostics; never retain wire payloads or hidden thinking."""

import contextvars
import json
import logging
import math
import os
import re
import sqlite3
import stat
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

logger = logging.getLogger(__name__)
RUN = contextvars.ContextVar("voice_diagnostic_run", default=None)


@dataclass(frozen=True)
class DiagnosticOptions:
    enabled: bool = False
    lookup_delay: float = 0
    backend_delay: float = 0
    fail_lookup: bool = False
    secrets: tuple = ()

    @classmethod
    def for_production(cls, config):
        """Protected production sink, without the isolated fault-injection controls."""
        profile = config.profile
        if not (profile / "zylch.db").is_file():
            raise ValueError("Production diagnostics require an ordinary profile")
        if any((parent / ".git").exists() for parent in (profile, *profile.parents)):
            raise ValueError("Diagnostics must remain outside Git")
        secrets = tuple(
            value.get_secret_value() for value in (
                config.api_key, config.webhook_secret,
                config.vonage_api_key, config.vonage_signature_secret,
                config.firebase_web_api_key,
            )
        )
        return cls(enabled=True, secrets=secrets)

    @classmethod
    def load(cls, profile: Path):
        values = dotenv_values(profile / ".env", interpolate=False)
        if values.get("VOICE_DIAGNOSTICS") != "1":
            return cls()
        if (
            any(
                values.get(k) != profile.name
                for k in ("OWNER_ID", "VOICE_SMOKE_TEST_PROFILE", "VOICE_ENGINE_ISOLATED_PROFILE")
            )
            or (profile / "zylch.db").exists()
        ):
            raise ValueError("Diagnostics require the explicit isolated profile")
        # Refuse repository paths, including a worktree's .git file.
        if any((parent / ".git").exists() for parent in (profile, *profile.parents)):
            raise ValueError("Diagnostics must remain outside Git")
        delays = [
            float(values.get(k) or 0)
            for k in ("VOICE_DIAGNOSTIC_LOOKUP_DELAY", "VOICE_DIAGNOSTIC_BACKEND_DELAY")
        ]
        if any(not math.isfinite(v) or v < 0 for v in delays):
            raise ValueError("Invalid diagnostic delay")
        secrets = tuple(
            v
            for k, v in values.items()
            if v and re.search(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", k)
        )
        return cls(True, *delays, values.get("VOICE_DIAGNOSTIC_FAIL_LOOKUP") == "1", secrets)


class CallTrace:
    """One private SQLite file per call. Failure degrades evidence, never cleanup.

    Callers provide allowlisted observations only. This sink never receives an
    SDK response, session configuration, SIP metadata, raw audio or model thinking.
    """

    def __init__(self, profile, session_id, revision, evidence, options):
        self.db = None
        self.evidence = evidence
        self.started = time.monotonic()
        self.options = options
        self.session_id = session_id
        self.revision = revision
        if not options.enabled:
            return
        evidence["diagnostics"] = "incomplete"
        try:
            directory = profile / "voice-diagnostics"
            directory.mkdir(mode=0o700, exist_ok=True)
            info = directory.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("Private diagnostic directory required")
            import uuid

            path = directory / f"call-{uuid.uuid4().hex}.db"
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            self.db = sqlite3.connect(path, timeout=0)
            # Small nonblocking WAL commits keep diagnostic disk fsync off the
            # audio reader's per-event path. This is evidence, not the cost ledger.
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=NORMAL")
            self.db.execute(
                "CREATE TABLE events (seq INTEGER PRIMARY KEY, utc TEXT, "
                "elapsed_ms INTEGER, kind TEXT, data TEXT)"
            )
            evidence["diagnostic_file"] = path.name
            evidence["diagnostics"] = "recording"
            self.record(
                "call_attached",
                lookup_delay=options.lookup_delay,
                backend_delay=options.backend_delay,
                fail_lookup=options.fail_lookup,
                playback="unverified; transcript/audio reflection is not handset playback",
            )
        except Exception:
            self._failed()

    def _failed(self):
        self.evidence["diagnostics"] = "incomplete"
        logger.warning("[voice] private diagnostic capture incomplete")
        if self.db:
            try:
                self.db.close()
            except Exception:
                pass
            self.db = None

    def _clean(self, value):
        if isinstance(value, str):
            for secret in sorted(self.options.secrets, key=len, reverse=True):
                value = value.replace(secret, "[REDACTED]")
            value = re.sub(
                r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED_TOKEN]", value
            )
            return re.sub(r"\b(?:sk-|whsec_)[A-Za-z0-9_-]+", "[REDACTED_KEY]", value)
        if isinstance(value, dict):
            return {k: self._clean(v) for k, v in value.items()}
        if isinstance(value, (tuple, list)):
            return [self._clean(v) for v in value]
        return value

    def record(self, kind, **data):
        if self.db is None:
            return
        try:
            payload = dict(
                call_id=self.session_id, config_revision=self.revision, run=RUN.get(), **data
            )
            self.db.execute(
                "INSERT INTO events (utc,elapsed_ms,kind,data) VALUES (?,?,?,?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    round((time.monotonic() - self.started) * 1000),
                    kind,
                    json.dumps(self._clean(payload), ensure_ascii=False),
                ),
            )
            self.db.commit()
        except Exception:
            self._failed()

    def close(self):
        if self.db is not None:
            self.record("trace_closed")
            if self.db is not None:
                try:
                    self.db.close()
                    self.db = None
                    self.evidence["diagnostics"] = "complete"
                except Exception:
                    self._failed()
