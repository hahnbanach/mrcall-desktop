"""Capture harness for SYNC_ANALYSIS: the request ``EmailSyncManager`` builds for one thread.

Each case is one email thread. The harness writes its messages into the throwaway profile's
``emails`` table (as the worker suites seed mail), then runs ``sync_emails`` over a real
``EmailArchiveManager``: the archive reads the thread back, the manager orders it by date and
``_agent_analyze`` builds the ``classify_thread`` request for the newest message — subject,
sender, message count and that message's body with whatever it quotes. One thread per case,
so one request; the table is emptied between cases.

Of the role's other call sites, ``calendar_sync.py`` builds a client and never sends a
request, and ``process_pipeline.py`` sends a one-token preflight ping that decides nothing;
neither has a decision to label, so neither is captured.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from zylch.storage.database import get_session
from zylch.storage.models import Email
from zylch.storage.storage import Storage
from zylch.tools import email_sync
from zylch.tools.email_archive import EmailArchiveManager

from tests.measurement.capture_support import (
    CAPTURE_MODEL,
    CaptureError,
    cases_of,
    client_factory,
    disposable_profile,
    the_request,
    tool_answer,
)

ROLE = "SYNC_ANALYSIS"
ENV_KEY = "MODEL_SYNC_ANALYSIS"
TOOL = "classify_thread"


def _answer(request: dict[str, Any]):
    return tool_answer(TOOL, {"summary": "", "open": False, "expected_action": None})


def _utc(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp).astimezone(UTC)


def _seed_thread(owner: str, case: dict[str, Any]) -> None:
    """The case's messages as the only mail in the profile."""
    with get_session() as session:
        session.query(Email).filter(Email.owner_id == owner).delete()
        for n, message in enumerate(case["input"]["messages"], start=1):
            when = _utc(message["date"])
            session.add(
                Email(
                    owner_id=owner,
                    gmail_id=f"{case['id']}-m{n}",
                    thread_id=f"thread-{case['id']}",
                    from_email=message["from_email"],
                    from_name=message.get("from_name"),
                    to_email=message["to_email"],
                    subject=message["subject"],
                    date=when.replace(tzinfo=None),
                    date_timestamp=int(when.timestamp()),
                    body_plain=message["body_plain"],
                )
            )


def _window_days(case: dict[str, Any]) -> int:
    """A window that holds the whole thread whenever the capture runs (the dates are fixed)."""
    oldest = min(_utc(m["date"]) for m in case["input"]["messages"])
    return max(30, (datetime.now(UTC) - oldest + timedelta(days=2)).days)


def build_requests(cases: Any, *, model: str = CAPTURE_MODEL) -> list[dict[str, Any]]:
    """``{"case_id", "request"}`` per case: the kwargs ``_agent_analyze`` passes, as sent."""
    out: list[dict[str, Any]] = []
    with disposable_profile(ENV_KEY, model) as profile:
        calls: list = []
        factory = client_factory(calls, _answer)
        profile.monkeypatch.setattr(email_sync, "try_make_llm_client", factory)
        storage = Storage()
        archive = EmailArchiveManager(None, profile.owner, supabase_storage=storage)
        manager = email_sync.EmailSyncManager(
            archive, owner_id=profile.owner, supabase_storage=storage
        )
        for case in cases_of(cases):
            calls.clear()
            _seed_thread(profile.owner, case)
            stats = manager.sync_emails(days_back=_window_days(case))
            if stats["total_threads"] != 1:
                raise CaptureError(f"{case['id']}: {stats['total_threads']} thread(s) synced")
            request = the_request(case["id"], calls, model=model, tool=TOOL)
            out.append({"case_id": case["id"], "request": request})
    return out
