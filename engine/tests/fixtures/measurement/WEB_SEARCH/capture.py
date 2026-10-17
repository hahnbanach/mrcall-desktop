"""Capture harness for WEB_SEARCH: the request of the solve loop's web search.

Builder: ``zylch.services.solve_tools._web_search``, what the task solve's
``web_search`` tool runs: one ``create_message_sync`` with the user turn
"Search the web and answer: <query>", no tools, ``max_tokens`` 1000. The
model answers from what it knows; nothing searches.

The role's other call site, the chat's ``WebSearchTool``
(``zylch/tools/web_search.py``), sends Anthropic's server tool
``web_search_20250305``. The engine's admission refuses a server tool on the
direct and OpenRouter transports ("server-tool costs require an explicit
bound"), so that request cannot be measured; :func:`capture_chat_tool_request`
captures it only so a test can show the refusal still holds.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from tests.measurement import conversation_capture as cc

ROLE = "WEB_SEARCH"


def run_case(case: Dict[str, Any], client: Any) -> str:
    """Run the solve loop's web search for the case's query with ``client``."""
    from zylch.services import solve_tools

    given = case["input"]
    with cc.disposable_profile(given.get("profile")) as profile:
        cc.route_llm(profile.mp, client)
        return solve_tools._web_search({"query": given["query"]})


def build_requests(cases: Any, *, calls: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """The web-search request of each case, as ``_web_search`` passed it."""
    captured = []
    for case in cc.case_list(cases):
        client = cc.CapturingClient(answer="No public information found.")
        answer = run_case(case, client)
        if answer != client.answer:
            raise RuntimeError(f"{case['id']}: the search did not finish: {answer}")
        if calls is not None:
            calls[case["id"]] = len(client.requests)
        captured.append(cc.entry(case, client.requests[-1]))
    return captured


def capture_chat_tool_request(query: str) -> Dict[str, Any]:
    """The request the chat's ``WebSearchTool`` sends for ``query`` (not measured)."""
    from zylch.tools import web_search

    client = cc.CapturingClient(answer="No public information found.")
    with cc.disposable_profile() as profile:
        cc.route_llm(profile.mp, client, web_search)
        asyncio.run(web_search.WebSearchTool().execute(query=query))
    return client.requests[-1]
