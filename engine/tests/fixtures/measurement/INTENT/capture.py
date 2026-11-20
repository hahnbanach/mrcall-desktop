"""Capture harness for INTENT: the request ``IntentRouter.classify_intent`` builds for one message.

``zylch.router.intent_classifier`` routes a user's chat message to one of the skills a
registry lists; its prompt embeds the registry's ``list_skills()`` and the message, and asks
for JSON naming the ``primary_skill``. The engine has no registry today (the module's own
docstring calls it dead, kept for a future skill router), so the case file supplies one —
``skills`` at its top level, shared by every case — and this harness hands it to the router
through the one method the router calls. The classes a case is labelled with are exactly
those skill names.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from zylch.router import intent_classifier

from tests.measurement.capture_support import (
    CAPTURE_MODEL,
    cases_of,
    client_factory,
    disposable_profile,
    document_of,
    text_answer,
    the_request,
)

ROLE = "INTENT"
ENV_KEY = "MODEL_INTENT"


class SkillRegistry:
    """The registry the router reads: ``list_skills()`` returns the case file's skills."""

    def __init__(self, skills: list[dict[str, str]]):
        self._skills = [dict(skill) for skill in skills]

    def list_skills(self) -> list[dict[str, str]]:
        return [dict(skill) for skill in self._skills]


def _answer(request: dict[str, Any]):
    # The JSON the router parses, so it returns a classification instead of its fallback.
    return text_answer(json.dumps({"primary_skill": "email_triage", "confidence": 0.5}))


def build_requests(cases: Any, *, model: str = CAPTURE_MODEL) -> list[dict[str, Any]]:
    """``{"case_id", "request"}`` per case: the kwargs ``classify_intent`` passes, as sent.

    ``cases`` is the ``cases.json`` document or its case list; with a list, the registry is
    read from the committed file.
    """
    registry = SkillRegistry(document_of(cases, ROLE)["skills"])
    out: list[dict[str, Any]] = []
    with disposable_profile(ENV_KEY, model) as profile:
        calls: list = []
        factory = client_factory(calls, _answer)
        profile.monkeypatch.setattr(intent_classifier, "make_llm_client", factory)
        for case in cases_of(cases):
            calls.clear()
            router = intent_classifier.IntentRouter(registry)
            asyncio.run(router.classify_intent(case["input"]["user_input"]))
            request = the_request(case["id"], calls, model=model)
            out.append({"case_id": case["id"], "request": request})
    return out
