"""Tests for learning durable rules from message corrections.

Unit-level: the LLM judge is faked. These check the plumbing —
diff guard, durable vs one-off gating, formatting, tool filtering —
not live model behaviour.
"""

from __future__ import annotations

import zylch.services.correction_learning as cl
from zylch.services.correction_learning import extract_rule, learn_from_corrections


class _FakeBlock:
    def __init__(self, data):
        self.input = data


class _FakeResponse:
    stop_reason = "tool_use"

    def __init__(self, data):
        self.content = [_FakeBlock(data)]


class _FakeClient:
    def __init__(self, data):
        self._data = data
        self.calls = 0

    def create_message_sync(self, **kwargs):
        self.calls += 1
        return _FakeResponse(self._data)


# ─── extract_rule ─────────────────────────────────────────────


def test_extract_rule_durable_formats_with_why():
    client = _FakeClient(
        {
            "is_durable_rule": True,
            "rule": "For support, direct customers to email.",
            "why": "user removed an offer to phone back",
        }
    )
    out = extract_rule(
        "We'll happily call you back.",
        "Please email us for support.",
        [],
        client,
    )
    assert out == "For support, direct customers to email.\nWhy: user removed an offer to phone back"


def test_extract_rule_non_durable_returns_none():
    client = _FakeClient({"is_durable_rule": False, "rule": "", "why": ""})
    assert extract_rule("draft A", "draft B", [], client) is None


def test_extract_rule_skips_llm_when_unchanged():
    client = _FakeClient({"is_durable_rule": True, "rule": "x", "why": "y"})
    assert extract_rule("identical", "identical", [], client) is None
    assert client.calls == 0


def test_extract_rule_durable_but_empty_rule_returns_none():
    client = _FakeClient({"is_durable_rule": True, "rule": "  ", "why": "z"})
    assert extract_rule("a", "b", [], client) is None


# ─── learn_from_corrections ───────────────────────────────────


def test_learn_writes_only_message_tool_diffs(monkeypatch):
    monkeypatch.setattr(cl, "_existing_rules", lambda owner_id: [])
    written = []
    monkeypatch.setattr(
        cl, "_write_rule", lambda owner_id, content: (written.append(content) or "blob-1")
    )
    client = _FakeClient(
        {
            "is_durable_rule": True,
            "rule": "Never offer to phone a customer for support.",
            "why": "removed call offer",
        }
    )
    corrections = [
        {
            "tool_name": "send_email",
            "proposed": {"body": "We'll call you back."},
            "edited": {"body": "Email us for support."},
        },
        # Non-message tool: must be ignored, no rule attempted.
        {
            "tool_name": "run_python",
            "proposed": {"code": "x"},
            "edited": {"code": "y"},
        },
    ]
    ids = learn_from_corrections(corrections, "owner-1", client=client)
    assert ids == ["blob-1"]
    assert written == ["Never offer to phone a customer for support.\nWhy: removed call offer"]


def test_learn_empty_corrections_noop():
    assert learn_from_corrections([], "owner-1", client=_FakeClient({})) == []
