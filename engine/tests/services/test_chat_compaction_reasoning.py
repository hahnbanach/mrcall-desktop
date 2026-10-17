"""Chat compaction rewrites history, so it carries no reasoning (brief D3, AC 2).

A reasoning block is bound to the conversation before it; compaction replaces
the middle of that conversation with a summary, so the turns it keeps — the
head and the tail — keep none, and the summarizer is never shown one.
"""

from __future__ import annotations

import asyncio

from zylch.services import chat_compaction

THINKING = {"type": "thinking", "thinking": "PRIVATE-REASONING", "signature": "SIGNATURE-1"}
REDACTED = {"type": "redacted_thinking", "data": "OPAQUE-REDACTED"}


def _loop(n):
    call = {"type": "tool_use", "id": f"tu-{n}", "name": "lookup", "input": {"n": n}}
    return [
        {"role": "user", "content": f"question {n} " + "x" * 400},
        {
            "role": "assistant",
            "content": [THINKING, REDACTED, {"type": "text", "text": "ok"}, call],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": f"tu-{n}", "content": "r"}],
        },
        {"role": "assistant", "content": [THINKING]},
    ]


def test_compaction_keeps_no_reasoning_and_summarizes_none(monkeypatch):
    seen = []

    async def summarize(middle_text):
        seen.append(middle_text)
        return "SUMMARY"

    monkeypatch.setattr(chat_compaction, "_summarize", summarize)
    history = [m for n in range(6) for m in _loop(n)]
    out = asyncio.run(chat_compaction.compact_if_needed(history, soft_limit=10, keep_recent=4))
    assert any("SUMMARY" in str(m["content"]) for m in out)
    blocks = [b for m in out if isinstance(m["content"], list) for b in m["content"]]
    assert not [b for b in blocks if b.get("type") in ("thinking", "redacted_thinking")]
    # The kept turns keep their tool exchange; a turn that was only reasoning is gone.
    assert {"type": "tool_use", "id": "tu-5", "name": "lookup", "input": {"n": 5}} in blocks
    assert not [m for m in out if m["content"] == []]
    assert "PRIVATE-REASONING" not in seen[0] and "SIGNATURE-1" not in seen[0]
    assert "OPAQUE-REDACTED" not in seen[0]
    assert history[1]["content"][0] == THINKING  # the caller's list is not mutated
