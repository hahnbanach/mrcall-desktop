"""call_site() tagging at the outermost worker LLM calls (P4 / FIX 4).

Each background worker wraps its create_message* call in call_site("<tag>")
so llm_usage.call_site attributes spend per worker. A stub client records
current_call_site() at call time; we assert the right tag is active for each
worker. (The tag→row propagation itself, incl. the async→thread hop, is
covered by tests/llm/test_usage.py.)
"""

import asyncio
import types
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from zylch.llm.usage import current_call_site


def _text_resp(text="INSERT"):
    """A minimal Anthropic-shape response with a single text block (no
    tool_use), so tool-driven workers fall through to their graceful
    'no decision' path after the site is recorded."""
    return types.SimpleNamespace(
        content=[types.SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        usage={},
        model="rec-model",
    )


class _Rec:
    """One recorder that satisfies BOTH the client protocol
    (create_message / create_message_sync) and the LLMMergeService protocol
    (.merge), appending the active call_site tag on every call."""

    model = "rec-model"

    def __init__(self):
        self.sites = []

    async def create_message(self, **kwargs):
        self.sites.append(current_call_site())
        return _text_resp()

    def create_message_sync(self, **kwargs):
        self.sites.append(current_call_site())
        return _text_resp()

    def merge(self, existing, new):
        self.sites.append(current_call_site())
        return "INSERT"


# ── task.detect ─────────────────────────────────────────────────────────
def test_task_detect_tag():
    from zylch.workers.task_creation import TaskWorker

    w = TaskWorker.__new__(TaskWorker)
    w.owner_id = "owner@x.io"
    w.user_email = "owner@x.io"
    w._task_prompt = "Analyse {event_type} for {user_email}: {event_data}"
    w._task_prompt_loaded = True
    rec = _Rec()
    w.client = rec

    asyncio.run(w._analyze_event("email", {"body": "hello"}, "blob-context"))
    assert rec.sites == ["task.detect"]


# ── memory.extract (email path — Mario-approved addition) ───────────────
def test_memory_extract_tag_email():
    from zylch.workers.memory import MemoryWorker

    w = MemoryWorker.__new__(MemoryWorker)
    w._custom_prompt = "Extract entities. #IDENTIFIERS/#ABOUT/#HISTORY. No placeholders."
    w._custom_prompt_loaded = True
    rec = _Rec()
    w.client = rec

    w._extract_entities(
        {
            "from_email": "eva@fanimotors.it",
            "to_email": ["support@x.io"],
            "subject": "hi",
            "date": "2026-06-01",
            "body_plain": "Buongiorno.",
        },
        "eva@fanimotors.it",
    )
    assert "memory.extract" in rec.sites


# ── memory.extract (calendar) + memory.merge in one drive ───────────────
def test_calendar_extract_and_merge_tags():
    from zylch.workers.memory import MemoryWorker

    w = MemoryWorker.__new__(MemoryWorker)
    w.owner_id = "owner@x.io"
    w.namespace = "user:owner@x.io"
    rec = _Rec()
    w.client = rec  # _extract_calendar_facts → create_message_sync → memory.extract
    w.llm_merge = rec  # self.llm_merge.merge(...) → memory.merge
    w.hybrid_search = MagicMock()
    w.hybrid_search.find_for_reconsolidation.return_value = types.SimpleNamespace(
        content="existing blob", blob_id="b1"
    )
    w.blob_storage = MagicMock()
    w.storage = MagicMock()

    ok = asyncio.run(
        w.process_calendar_event(
            {"id": "evt1", "summary": "Sync", "start_time": "2026-07-05T10:00"}
        )
    )
    assert ok is True
    assert rec.sites == ["memory.extract", "memory.merge"]


# ── canary ──────────────────────────────────────────────────────────────
def test_canary_tag():
    from zylch.memory.llm_merge import merge_gate_selfcheck

    rec = _Rec()
    res = merge_gate_selfcheck(rec)  # pass our recorder as the merge service
    assert rec.sites == ["canary"]
    assert res["healthy"] is True  # INSERT → distinct entities refused


# ── fresh-DB fixture for the storage-driven sweeps ──────────────────────
@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "tags.db"))
    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield
    db_mod.dispose_engine()


def _insert_task(owner, **over):
    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem

    tid = over.pop("id", str(uuid.uuid4()))
    fields = {
        "id": tid,
        "owner_id": owner,
        "event_type": "email",
        "event_id": str(uuid.uuid4()),
        "action_required": True,
        "urgency": "medium",
        "suggested_action": "Reply",
        "reason": "waiting",
        "analyzed_at": datetime.now(timezone.utc).replace(tzinfo=None),
        "sources": {},
    }
    fields.update(over)
    with get_session() as s:
        s.add(TaskItem(**fields))
    return tid


def _patch_client(monkeypatch, rec):
    """Route try_make_llm_client (imported lazily in the sweeps) to the
    recorder and capture the model= knob it was asked for."""
    captured = {}

    def factory(model=None):
        captured["model"] = model
        return rec

    monkeypatch.setattr("zylch.llm.try_make_llm_client", factory)
    return captured


# ── f4.reanalyze (+ MODEL_REANALYZE wiring) ─────────────────────────────
def test_f4_reanalyze_tag(fresh_db, monkeypatch):
    from zylch.workers.task_reanalyze import reanalyze_task

    owner = "owner@x.io"
    monkeypatch.setenv("EMAIL_ADDRESS", owner)
    monkeypatch.setenv("MODEL_REANALYZE", "claude-reanalyze-x")
    tid = _insert_task(owner, sources={"thread_id": "T1"})
    rec = _Rec()
    captured = _patch_client(monkeypatch, rec)

    asyncio.run(reanalyze_task(tid, owner))
    assert "f4.reanalyze" in rec.sites
    assert captured["model"] == "claude-reanalyze-x"


# ── dedup.f8 (+ MODEL_DEDUP wiring) ─────────────────────────────────────
def test_dedup_f8_tag(fresh_db, monkeypatch):
    from zylch.workers.task_dedup_sweep import run_dedup_sweep

    owner = "owner@x.io"
    monkeypatch.setenv("MODEL_DEDUP", "claude-dedup-x")
    # Two open tasks sharing a contact → one cluster → arbiter call fires.
    _insert_task(owner, contact_email="dup@acme.io")
    _insert_task(owner, contact_email="dup@acme.io")
    rec = _Rec()
    captured = _patch_client(monkeypatch, rec)

    asyncio.run(run_dedup_sweep(owner))
    assert "dedup.f8" in rec.sites
    assert captured["model"] == "claude-dedup-x"


# ── dedup.f9 (+ MODEL_DEDUP wiring) ─────────────────────────────────────
def test_dedup_f9_tag(fresh_db, monkeypatch):
    from zylch.workers.task_topic_dedup import run_topic_dedup

    owner = "owner@x.io"
    monkeypatch.setenv("MODEL_DEDUP", "claude-dedup-x")
    for _ in range(4):  # >= MIN_TASKS_FOR_TOPIC_DEDUP
        _insert_task(owner)
    rec = _Rec()
    captured = _patch_client(monkeypatch, rec)

    asyncio.run(run_topic_dedup(owner))
    assert "dedup.f9" in rec.sites
    assert captured["model"] == "claude-dedup-x"
