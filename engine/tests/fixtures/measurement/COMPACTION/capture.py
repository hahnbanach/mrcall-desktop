"""Capture harness for COMPACTION: the summarizer's request for each case's chat history.

Builder: ``zylch.services.chat_compaction.compact_if_needed``, which
``ChatService`` runs on a restored conversation before every chat turn. It
keeps the first turn and the last ten verbatim, renders the turns between as
prose (``_render_middle_for_summary``) and asks the role's model for one
summary (``_summarize`` → ``create_message``).

Production compacts past 80,000 estimated tokens; a smoke case sets
``input.soft_limit`` low so a short history takes the same path. Head, tail
and rendering are production's (``keep_first`` and ``keep_recent`` are not
overridden), so only the length of the middle differs from a real run. The
harness checks that the summary was spliced in, which is what proves the
summarizer's path ran to its end.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from tests.measurement import conversation_capture as cc

ROLE = "COMPACTION"


def run_case(case: Dict[str, Any], client: Any) -> List[Dict[str, Any]]:
    """Compact the case's history with ``client`` as the summarizer; return the result."""
    from zylch.services import chat_compaction

    given = case["input"]
    with cc.disposable_profile(given.get("profile")) as profile:
        cc.route_llm(profile.mp, client)
        return asyncio.run(
            chat_compaction.compact_if_needed(given["history"], soft_limit=given["soft_limit"])
        )


def build_requests(cases: Any, *, calls: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """The summarizer's request for each case, as ``_summarize`` passed it."""
    from zylch.services import chat_compaction

    captured = []
    for case in cc.case_list(cases):
        client = cc.CapturingClient(answer="Summary of the earlier conversation.")
        compacted = run_case(case, client)
        kept = chat_compaction.KEEP_FIRST + 1 + chat_compaction.KEEP_RECENT
        if len(compacted) != kept:
            raise RuntimeError(f"{case['id']}: the history was not compacted")
        if calls is not None:
            calls[case["id"]] = len(client.requests)
        captured.append(cc.entry(case, client.requests[-1]))
    return captured
