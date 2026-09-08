"""One `search_local_memory` page is bounded, and a blob is never echoed twice.

The tool returned every ranked blob's full content twice — once in the
message and once in `data.results` — and honoured any `limit` the model
asked for. A hundred blobs were 250 KB of tool result on the production
profile, on top of the email search in the same step. Incident:
`~/hb/docs/known-issues/2026-09-08-engine-chat-prompt-unbounded.md`.

Content is never cut: the model reads it back into `update_memory`, and a
cut blob would be written back short. The page is clamped instead, and
each blob appears once.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from zylch.assistant.core import ZylchAIAgent
from zylch.tools import contact_tools as mod
from zylch.tools.contact_tools import SearchLocalMemoryTool

OWNER = "owner@example.com"


class _Ranker:
    def __init__(self, n: int):
        self.n = n

    def search(self, owner_id, query, limit):
        return [
            SimpleNamespace(
                blob_id=f"blob-{i}",
                namespace=f"user:{owner_id}",
                content=f"# PERSON sentinel-{i:03d}\n" + ("detail line\n" * 30),
                hybrid_score=0.9,
                fts_score=0.5,
                semantic_score=0.4,
            )
            for i in range(min(self.n, limit))
        ]


def _formatted(result) -> str:
    agent = ZylchAIAgent.__new__(ZylchAIAgent)
    return agent._format_tool_result(result)


def test_the_page_is_clamped_and_each_blob_appears_once():
    tool = SearchLocalMemoryTool(search_engine=_Ranker(100), owner_id=OWNER)

    result = asyncio.run(tool.execute(query="private label", limit=100))

    assert result.data["count"] == mod.MAX_RESULTS
    assert f"limit 100 clamped to {mod.MAX_RESULTS}" in result.message.splitlines()[0]
    text = _formatted(result)
    for i in range(mod.MAX_RESULTS):
        assert text.count(f"sentinel-{i:03d}") == 1, f"blob {i} echoed more than once"
    for r in result.data["results"]:
        assert r["content"].endswith("detail line\n"), "blob content must be whole"
    assert "blob_id=blob-0" in result.message


def test_a_small_page_is_not_clamped():
    tool = SearchLocalMemoryTool(search_engine=_Ranker(100), owner_id=OWNER)

    result = asyncio.run(tool.execute(query="x", limit=10))

    assert result.data["count"] == 10
    assert "clamped" not in result.message
