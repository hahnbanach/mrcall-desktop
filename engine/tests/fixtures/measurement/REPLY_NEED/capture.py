"""Capture harness for REPLY_NEED: the request ``zylch.utils.reply_need`` builds for one message.

Each case is the newest inbound message of a thread, handed to ``classify`` in the shape
``emails.needs_reply`` builds (``zylch/rpc/reply_queries.py``): a customer's message on a
thread our side has already answered. ``classify`` screens it deterministically first; every
case is written to pass that screen (short, no question mark, no link, no attachment), so it
reaches ``adjudicate``, which builds the one request captured here. A case the screen answers
by itself never reaches a model and is refused.
"""

from __future__ import annotations

import asyncio
from typing import Any

import zylch.llm as llm_pkg
from zylch.utils import reply_need

from tests.measurement.capture_support import (
    CAPTURE_MODEL,
    cases_of,
    client_factory,
    disposable_profile,
    the_request,
    tool_answer,
)

ROLE = "REPLY_NEED"
ENV_KEY = "MODEL_REPLY_NEED"
TOOL = "reply_need_decision"


def candidate(case: dict[str, Any]) -> dict[str, Any]:
    """The message as ``emails.needs_reply`` hands it to ``classify``.

    The flags are the RPC's for a customer's message that reaches the model: not ours, not an
    autoresponder, no attachment, and a real answer of ours earlier on the thread.
    """
    message = case["input"]["message"]
    return {
        "id": case["id"],
        "from_email": message["from_email"],
        "subject": message["subject"],
        "date": "",
        "body_plain": message["body_plain"],
        "is_auto_reply": False,
        "is_user_sent": False,
        "has_attachments": False,
        "answered_before": True,
    }


def _answer(request: dict[str, Any]):
    # One message per request, so one verdict; "needs a reply" leaves nothing silenced.
    return tool_answer(TOOL, {"verdicts": [{"index": 0, "needs_reply": True, "reason": "capture"}]})


def build_requests(cases: Any, *, model: str = CAPTURE_MODEL) -> list[dict[str, Any]]:
    """``{"case_id", "request"}`` per case: the kwargs ``adjudicate`` passes, as sent."""
    out: list[dict[str, Any]] = []
    with disposable_profile(ENV_KEY, model) as profile:
        calls: list = []
        profile.monkeypatch.setattr(llm_pkg, "try_make_llm_client", client_factory(calls, _answer))
        for case in cases_of(cases):
            calls.clear()
            asyncio.run(reply_need.classify([candidate(case)]))
            request = the_request(case["id"], calls, model=model, tool=TOOL)
            out.append({"case_id": case["id"], "request": request})
    return out
