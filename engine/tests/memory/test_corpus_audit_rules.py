"""The corpus verdict's rules after the audit of the paid run (milestone 10, S4b5).

- B2: "a child inherited the sender's identity" reads the identifier header's
  email only; a body that quotes the sender's address inherits nothing.
- C1: a ``must_preserve`` entry may list the same substance in either
  language, and any one of them preserves it.
- C2: REVIEW is an allowed outcome where the M9 prompt prescribes it.
- A failed extraction (``_parse_entities`` raising) leaves its raw text in the
  row (``extraction_failures``); the worker still raises as before.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.memory import corpus_live_provider as provider
from tests.memory import corpus_live_record as rec
from tests.memory import mnemonic_cases as cases

SEEDED = SimpleNamespace(real=lambda fixture: fixture)


def row(*, texts=(), outcome=None, children=0):
    ops = [{"outcome": outcome, "reason": "", "parent_event_id": None, "state": "done"}]
    ops += [
        {"outcome": "committed", "reason": "", "parent_event_id": "p", "state": "done"}
    ] * children
    return {
        "committed_ids": [[f"blob-{n}", "v"] for n, _ in enumerate(texts)],
        "committed_content": {f"blob-{n}": text for n, text in enumerate(texts)},
        "forbidden_target_hits": [],
        "operations": ops,
    }


def multi_entity_case():
    return next(c for c in cases.load_incidents()["cases"] if "children" in c["expected"])


def test_a_child_inherits_the_sender_only_through_its_identifier_header():
    spec = multi_entity_case()
    sender = f"sender-{spec['id']}@corpus.invalid"
    kids = len(spec["expected"]["children"])
    quoted = f"#IDENTIFIERS\nEmail: other@corpus.invalid\n#ABOUT\nWrote to us from {sender}."
    inherited = f"#IDENTIFIERS\nEmail: {sender}\n#ABOUT\nA contact."
    clean = rec.judge(spec, row(texts=[quoted], children=kids), SEEDED)["critical"]
    assert not any("inherited" in c for c in clean)
    bad = rec.judge(spec, row(texts=[inherited], children=kids), SEEDED)["critical"]
    assert any("inherited" in c for c in bad)


def test_must_preserve_accepts_either_language():
    spec = cases.case("customer_price_correction")
    english = "#IDENTIFIERS\nName: Boreale\n#ABOUT\n74 euro from October, as agreed."
    assert not [
        n
        for n in rec.judge(spec, row(texts=[english]), SEEDED)["noncritical"]
        if "must_preserve" in n
    ]
    neither = "#IDENTIFIERS\nName: Boreale\n#ABOUT\n74 euro."
    missing = rec.judge(spec, row(texts=[neither]), SEEDED)["noncritical"]
    assert any("ottobre" in n for n in missing) and any("concordato" in n for n in missing)


@pytest.mark.parametrize(
    "case_id",
    [
        "unrelated_same_name_people",
        "customer_forwarding_number_correction",
        "customer_price_correction",
        "planned_not_completed",
    ],
)
def test_review_is_an_allowed_outcome_where_the_prompt_prescribes_it(case_id):
    verdict = rec.judge(cases.case(case_id), row(outcome="review_needed"), SEEDED)
    assert not any("no allowed outcome" in n for n in verdict["noncritical"])


def test_a_failed_extraction_keeps_its_raw_text():
    def parse(raw):
        raise ValueError("no entity delimiter")

    worker = SimpleNamespace(_parse_entities=parse)
    failures = provider.record_failed_extractions(worker)
    with pytest.raises(ValueError):
        worker._parse_entities("garbled model output")
    assert failures == [{"raw": "garbled model output", "error": "ValueError: no entity delimiter"}]
