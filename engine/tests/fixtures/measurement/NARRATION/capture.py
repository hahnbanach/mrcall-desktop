"""Capture harness for NARRATION: the request of each case's narration RPC.

Builders: ``zylch.rpc.methods.narration_summarize`` (the live line the app
shows while a chat turn runs, from the sidecar's latest log lines;
``max_tokens`` 60) and ``zylch.rpc.methods.narration_predict`` (the first
placeholder, predicted from the user's message; ``max_tokens`` 40). A case
names its builder in ``input.builder`` and passes the RPC's parameters as the
renderer does (``input.params``: ``lines`` and ``context`` for summarize,
``message`` and ``context`` for predict).

``narration_summarize`` drops log lines it judges noise before it calls the
model; a case whose lines were all dropped would send nothing, and the
harness then fails rather than return an empty capture.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from tests.measurement import conversation_capture as cc

ROLE = "NARRATION"

BUILDERS = {
    "zylch.rpc.methods.narration_summarize": "narration_summarize",
    "zylch.rpc.methods.narration_predict": "narration_predict",
}


def run_case(case: Dict[str, Any], client: Any) -> Dict[str, Any]:
    """Call the case's narration RPC with ``client`` as the role's client."""
    from zylch.rpc import methods

    given = case["input"]
    handler = getattr(methods, BUILDERS[given["builder"]])
    with cc.disposable_profile(given.get("profile")) as profile:
        cc.route_llm(profile.mp, client)
        return asyncio.run(handler(dict(given["params"]), lambda *_args: None))


def build_requests(cases: Any, *, calls: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """The narration request of each case, as the RPC passed it."""
    captured = []
    for case in cc.case_list(cases):
        client = cc.CapturingClient(answer="Sto lavorando alla tua richiesta.")
        run_case(case, client)
        if not client.requests:
            raise RuntimeError(f"{case['id']}: the RPC answered without calling the model")
        if calls is not None:
            calls[case["id"]] = len(client.requests)
        captured.append(cc.entry(case, client.requests[-1]))
    return captured
