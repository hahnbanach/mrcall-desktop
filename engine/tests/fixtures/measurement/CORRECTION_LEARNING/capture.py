"""Capture harness for CORRECTION_LEARNING: the judge requests of ``learn_from_corrections``.

A correction is what the user changed in an approval-gated message before it was sent. The
engine judges each one twice, independently: ``extract_rule`` (tool ``record_rule``: a durable
policy for every future message?) and ``extract_fact`` (tool ``record_fact``: a corrected
standard business value?). Each case names one judge (``input.judge``) and is labelled for it;
this harness runs the whole ``learn_from_corrections`` path — both judges are called, as in
production — and returns the request of the case's judge.

The judges' prompts read the company's memory: the existing rules (``prefs:<owner>``,
rendered as the solve prompt renders them) and the existing fact categories
(``facts:<key>``). The case file holds each company's memory once, under ``memories`` at its
top level; a case names its company (``input.memory``), and the harness seeds that memory
into a throwaway profile through the memory suites' seeding helper before running the
company's cases. Both scripted answers decline, so nothing is written; a write would mean the
path changed, and is refused.
"""

from __future__ import annotations

from typing import Any

import zylch.llm as llm_pkg
from zylch.memory.blob_storage import BlobStorage
from zylch.services import facts_store
from zylch.services.correction_learning import learn_from_corrections
from zylch.storage.database import get_session
from zylch.storage.models import Blob

from tests.memory import seeding
from tests.measurement.capture_support import (
    CAPTURE_MODEL,
    CaptureError,
    cases_of,
    client_factory,
    disposable_profile,
    document_of,
    the_request,
    tool_answer,
    tool_names,
)

ROLE = "CORRECTION_LEARNING"
ENV_KEY = "MODEL_CORRECTION_LEARNING"
JUDGE_TOOLS = {"rule": "record_rule", "fact": "record_fact"}

# The shapes the harness writes today (tests/services/test_helper_writer_events.py): a rule
# under its STYLE control header, which rendering strips; a company fact under its header.
STYLE_HEADER = "#IDENTIFIERS\nEntity type: STYLE\nScope: account\n#ABOUT\n"
FACT_HEADER = "#IDENTIFIERS\nEntity type: FACT\nScope: company\n"

DECLINE = {
    "record_rule": {"is_durable_rule": False, "rule": "", "why": ""},
    "record_fact": {"is_fact_change": False, "category": "", "key": "", "value": ""},
}


def _answer(request: dict[str, Any]):
    name = tool_names(request)[0]
    return tool_answer(name, dict(DECLINE[name]))


def _seed(profile, memory: dict[str, Any]) -> None:
    """The company's rules and facts, written as the memory suites seed them."""
    storage = BlobStorage(get_session, profile.embedder)
    owner = profile.owner
    for rule in memory["rules"]:
        seeding.store_blob(storage, owner, f"prefs:{owner}", STYLE_HEADER + rule, "seed")
    facts = facts_store.facts_namespace(owner)
    for fact in memory["facts"]:
        content = (
            f"{FACT_HEADER}Category: {fact['category']}\nKey: {fact['key']}\n"
            f"#ABOUT\nValue: {fact['value']}"
        )
        seeding.store_blob(storage, owner, facts, content, "seed")


def _blob_count() -> int:
    with get_session() as session:
        return session.query(Blob).count()


def build_requests(cases: Any, *, model: str = CAPTURE_MODEL) -> list[dict[str, Any]]:
    """``{"case_id", "request"}`` per case: the kwargs its judge passes, as sent.

    ``cases`` is the ``cases.json`` document or its case list; with a list, the memories are
    read from the committed file. One throwaway profile per company memory.
    """
    memories = document_of(cases, ROLE)["memories"]
    ordered = cases_of(cases)
    by_memory: dict[str, list[dict[str, Any]]] = {}
    for case in ordered:
        by_memory.setdefault(case["input"]["memory"], []).append(case)
    requests: dict[str, dict[str, Any]] = {}
    for name, group in by_memory.items():
        with disposable_profile(ENV_KEY, model) as profile:
            _seed(profile, memories[name])
            seeded = _blob_count()
            calls: list = []
            factory = client_factory(calls, _answer)
            profile.monkeypatch.setattr(llm_pkg, "try_make_llm_client", factory)
            for case in group:
                calls.clear()
                written = learn_from_corrections([case["input"]["correction"]], profile.owner)
                if written or _blob_count() != seeded:
                    raise CaptureError(f"{case['id']}: the capture wrote {written!r}")
                tool = JUDGE_TOOLS[case["input"]["judge"]]
                requests[case["id"]] = the_request(case["id"], calls, model=model, tool=tool)
    return [{"case_id": case["id"], "request": requests[case["id"]]} for case in ordered]
