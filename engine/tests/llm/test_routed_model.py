"""routed_model() + per-worker model-routing wiring (P4 / FIX 3).

routed_model() reads a MODEL_* knob LIVE from saved profile settings (blank/unset →
None = engine default). The wiring tests assert each worker passes the
resolved value straight to its client factory, so flipping a knob in the
profile .env re-routes exactly that worker on its next call — no restart.
"""

import types
from unittest.mock import MagicMock

import pytest

from zylch.llm import routed_model


@pytest.fixture
def saved_model(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(tmp_path))
    path = tmp_path / ".env"
    values = {}
    path.write_text("")

    def save(key, value=None):
        if value is None:
            values.pop(key, None)
        else:
            values[key] = value
        path.write_text("".join(f'{k}="{v}"\n' for k, v in values.items()))

    return save


# ── routed_model() unit behaviour ───────────────────────────────────────
def test_routed_model_returns_value_when_set(monkeypatch, saved_model):
    saved_model("MODEL_UNIT_TEST", "claude-sonnet-4-5")
    assert routed_model("MODEL_UNIT_TEST") == "claude-sonnet-4-5"


def test_routed_model_strips_whitespace(monkeypatch, saved_model):
    saved_model("MODEL_UNIT_TEST", "  claude-haiku-4-5  ")
    assert routed_model("MODEL_UNIT_TEST") == "claude-haiku-4-5"


def test_routed_model_blank_is_none(monkeypatch, saved_model):
    saved_model("MODEL_UNIT_TEST", "   ")
    assert routed_model("MODEL_UNIT_TEST") is None


def test_routed_model_unset_is_none(monkeypatch, saved_model):
    saved_model("MODEL_UNIT_TEST")
    assert routed_model("MODEL_UNIT_TEST") is None


def test_routed_model_is_isolated_per_key(monkeypatch, saved_model):
    saved_model("MODEL_A", "model-a")
    saved_model("MODEL_B")
    assert routed_model("MODEL_A") == "model-a"
    assert routed_model("MODEL_B") is None


# ── wiring: MODEL_TASK_DETECTION → TaskWorker.__init__ ──────────────────
def _neuter_heavy_worker_deps(monkeypatch, module):
    """Stub the embedding/search machinery so a worker's __init__ is cheap."""
    monkeypatch.setattr(module, "EmbeddingEngine", lambda *a, **k: object())
    monkeypatch.setattr(module, "HybridSearchEngine", lambda *a, **k: object())
    if hasattr(module, "BlobStorage"):
        monkeypatch.setattr(module, "BlobStorage", lambda *a, **k: object())


def test_task_detection_knob_wired(monkeypatch, saved_model):
    import zylch.workers.task_creation as tc

    captured = {}
    monkeypatch.setattr(
        tc, "make_llm_client", lambda model=None: captured.setdefault("model", model)
    )
    _neuter_heavy_worker_deps(monkeypatch, tc)
    monkeypatch.setattr(
        "zylch.workers.thread_presenter.load_user_aliases_for_owner",
        lambda owner: [],
    )

    saved_model("MODEL_TASK_DETECTION", "claude-detect-x")
    tc.TaskWorker(MagicMock(), "owner@x.io", "owner@x.io")
    assert captured["model"] == "claude-detect-x"


def test_task_detection_knob_default_is_none(monkeypatch, saved_model):
    import zylch.workers.task_creation as tc

    captured = {}
    monkeypatch.setattr(
        tc, "make_llm_client", lambda model=None: captured.setdefault("model", model)
    )
    _neuter_heavy_worker_deps(monkeypatch, tc)
    monkeypatch.setattr(
        "zylch.workers.thread_presenter.load_user_aliases_for_owner",
        lambda owner: [],
    )

    saved_model("MODEL_TASK_DETECTION")
    tc.TaskWorker(MagicMock(), "owner@x.io", "owner@x.io")
    assert captured["model"] is None


# ── wiring: MODEL_MEMORY_EXTRACT + MODEL_MEMORY_MERGE → MemoryWorker ─────
def test_memory_extract_and_merge_knobs_wired(monkeypatch, saved_model):
    import zylch.workers.memory as mem

    captured = {}
    monkeypatch.setattr(
        mem, "make_llm_client", lambda model=None: captured.setdefault("extract", model)
    )

    class _FakeMerge:
        def __init__(self, model=None):
            captured["merge"] = model

    monkeypatch.setattr(mem, "LLMMergeService", _FakeMerge)
    _neuter_heavy_worker_deps(monkeypatch, mem)

    saved_model("MODEL_MEMORY_EXTRACT", "claude-extract-x")
    saved_model("MODEL_MEMORY_MERGE", "claude-merge-x")
    mem.MemoryWorker(MagicMock(), "owner@x.io")
    assert captured["extract"] == "claude-extract-x"
    assert captured["merge"] == "claude-merge-x"


# ── wiring: MODEL_MEMORY_MERGE → merge_gate_selfcheck's own service ─────
def test_merge_gate_uses_memory_merge_knob(monkeypatch, saved_model):
    from zylch.memory.llm_merge import merge_gate_selfcheck

    captured = {}

    def _fake_factory(model=None):
        captured["model"] = model
        client = MagicMock()
        client.model = model or "default"
        client.create_message_sync.return_value = types.SimpleNamespace(
            stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text="INSERT")]
        )
        return client

    monkeypatch.setattr("zylch.memory.llm_merge.make_llm_client", _fake_factory)
    saved_model("MODEL_MEMORY_MERGE", "claude-mergegate-x")

    res = merge_gate_selfcheck()  # merge_service=None → builds its own
    assert captured["model"] == "claude-mergegate-x"
    assert res["healthy"] is True  # INSERT → distinct entities correctly refused
