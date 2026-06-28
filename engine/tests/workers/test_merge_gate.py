"""Regression tests for the merge gate (2026-06 universal-'John'-sink).

Root cause: a prompt-cache refactor (58f392a) put only the one-line
preamble ("Merge these entities into a SINGLE ENTITY:") into the cached
system prompt — ``MERGE_PROMPT.split("EXISTING_ENTITY:")[0]`` — and dropped
the ENTIRE rule set, including the "return INSERT when the entities differ"
rule. The model was never told it could refuse, refused 0 times across 859
merges, and collapsed 400+ unrelated contacts into the first blob, each
one's specifics discarded.

These lock in the invariant (full instructions in the cached system prompt,
entity data ONLY in the user message) and the sentinel detection / canary,
all without a live LLM — so the structural regression can never return
silently. The semantic side (a real model actually returning INSERT) is
covered by the live test in tests/llm and by merge_gate_selfcheck() at
runtime.
"""
from unittest.mock import MagicMock

import pytest

from zylch.memory.llm_merge import (
    LLMMergeService,
    MERGE_INSTRUCTIONS,
    is_no_merge_response,
    merge_gate_selfcheck,
)


def _svc_with_fake_client(monkeypatch, returns_text):
    """LLMMergeService whose LLM returns fixed text, capturing call kwargs."""
    captured = {}

    def fake_create_message_sync(**kwargs):
        captured.update(kwargs)
        resp = MagicMock()
        resp.content = [MagicMock(text=returns_text)]
        return resp

    fake_client = MagicMock()
    fake_client.model = "fake-model"
    fake_client.create_message_sync.side_effect = fake_create_message_sync

    monkeypatch.setattr(
        "zylch.memory.llm_merge.make_llm_client", lambda model=None: fake_client
    )
    return LLMMergeService(), captured


# ── is_no_merge_response: the shared gate sentinel ──────────────────
@pytest.mark.parametrize(
    "text,expected",
    [
        ("INSERT", True),
        ("INSERT.", True),
        ("insert\n", True),
        ("  INSERT  ", True),
        ("SKIP", True),  # legacy sentinel the upsert paths used to miss
        ("skip", True),
        ("", False),
        (None, False),
        # A genuinely merged blob must NOT read as a refusal, even when its
        # prose happens to contain the word "insert".
        (
            "#IDENTIFIERS\nEntity type: PERSON\nName: X\n#ABOUT\nWe should insert this lead.",
            False,
        ),
        ("#IDENTIFIERS\nEntity type: COMPANY\nName: Acme", False),
    ],
)
def test_is_no_merge_response(text, expected):
    assert is_no_merge_response(text) is expected


# ── the regression invariant: rules in system, data in user ─────────
def test_merge_ships_full_rules_in_system_not_just_preamble(monkeypatch):
    svc, captured = _svc_with_fake_client(monkeypatch, "INSERT")
    existing = "#IDENTIFIERS\nName: John Doe\nEmail: john@acme.com"
    new = "#IDENTIFIERS\nName: Fani Motors\nEmail: info@fanimotors.it"

    result = svc.merge(existing, new)

    # The cached system prompt must carry the WHOLE instruction set —
    # this is exactly what 58f392a sliced off.
    system_text = captured["system"][0]["text"]
    assert "INSERT" in system_text, "system prompt lost the refuse-token rule"
    assert (
        "#IDENTIFIERS" in system_text
        and "#ABOUT" in system_text
        and "#HISTORY" in system_text
    ), "system prompt lost the output format"
    assert system_text.strip() != "Merge these entities into a SINGLE ENTITY:"
    assert system_text == MERGE_INSTRUCTIONS

    # Entity DATA must live in the user message, never baked into the cached
    # system block (that is what the refactor was reaching for; do it right).
    assert "john@acme.com" not in system_text
    assert "info@fanimotors.it" not in system_text
    user_text = captured["messages"][0]["content"]
    assert "john@acme.com" in user_text and "info@fanimotors.it" in user_text

    assert result == "INSERT"
    assert is_no_merge_response(result)


def test_merge_returns_blob_for_same_entity(monkeypatch):
    merged = "#IDENTIFIERS\nEntity type: PERSON\nName: John Doe\n#ABOUT\none\n#HISTORY\nx"
    svc, _ = _svc_with_fake_client(monkeypatch, merged)
    out = svc.merge("existing", "new")
    assert out == merged
    assert not is_no_merge_response(out)


# ── the canary (closes "the silence") ───────────────────────────────
def test_selfcheck_healthy_when_gate_refuses(monkeypatch):
    svc, _ = _svc_with_fake_client(monkeypatch, "INSERT")
    res = merge_gate_selfcheck(svc)
    assert res["healthy"] is True
    assert res["verdict"] == "refused"


def test_selfcheck_broken_open_when_gate_merges(monkeypatch):
    # The broken-open gate returns a merged blob for the two unrelated
    # canary fixtures instead of INSERT.
    merged = "#IDENTIFIERS\nEntity type: PERSON\nName: Aldo\n#ABOUT\nsink\n#HISTORY\ny"
    svc, _ = _svc_with_fake_client(monkeypatch, merged)
    res = merge_gate_selfcheck(svc)
    assert res["healthy"] is False
    assert res["verdict"] == "merged"


def test_selfcheck_unknown_on_error_never_disables(monkeypatch):
    svc, _ = _svc_with_fake_client(monkeypatch, "INSERT")
    svc.client.create_message_sync.side_effect = RuntimeError("api down")
    res = merge_gate_selfcheck(svc)
    # healthy=None means "couldn't check" — must NOT be treated as broken,
    # so a flaky API call never disables merging for a whole build.
    assert res["healthy"] is None
