"""Reference scoring of a REANALYZE answer against its case (see README).

The answer is the input of the model's ``reanalyze_decision`` call. It is
scored by what ``reanalyze_task`` does with it: the action is lower-cased,
a missing one reads as ``keep``, and anything but ``close`` or ``update``
keeps the task. A wrong action may still be harmless, which is why
``critical_on`` names the harmful outcomes per case.

``score_answer`` returns ``{"passed", "critical", "outcome"}``: the answer
passes when its outcome is the label's ``action`` or one of
``also_accept``; with ``urgency_at_least`` an ``update`` proposing a lower
urgency is the outcome ``update_lowered`` and does not pass. It fails
critically when it does not pass and its outcome is in ``critical_on``.
"""

from __future__ import annotations

from typing import Any

# What an answer can amount to; ``critical_on`` lists some of these.
OUTCOMES = ("keep", "close", "update", "update_lowered", "invalid")
# The tool fields whose language the case's ``expect_lang`` governs.
FREE_TEXT = ("title", "suggested_action", "reason")

_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def effect(answer: Any) -> str:
    """The action ``reanalyze_task`` applies for ``answer``."""
    if not isinstance(answer, dict):
        return "invalid"
    action = answer.get("action") or "keep"
    if not isinstance(action, str):
        return "invalid"
    action = action.lower()
    return action if action in ("close", "update") else "keep"


def score_answer(case: dict[str, Any], answer: Any) -> dict[str, Any]:
    """Score ``answer`` (the ``reanalyze_decision`` input) against ``case``."""
    label = case["label"]
    outcome = effect(answer)
    floor = label.get("urgency_at_least")
    if outcome == "update" and floor:
        proposed = str(answer.get("urgency") or "").strip().lower()
        if proposed and _RANK.get(proposed, 0) < _RANK[floor]:
            outcome = "update_lowered"
    passed = outcome in (label["action"], *label.get("also_accept", ()))
    return {
        "passed": passed,
        "critical": not passed and outcome in case["critical_on"],
        "outcome": outcome,
    }
