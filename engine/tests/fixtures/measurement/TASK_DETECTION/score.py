"""Reference scoring of a TASK_DETECTION answer against its case (see README).

The answer is the input of the model's ``task_decision`` call. It is scored
by what the engine would do with it, so a harmless wording of the right
decision is not a critical failure:

- ``_analyze_event`` drops an answer that misses a required field or has a
  wrong type or enum value: the email stays pending and is retried
  (``invalid``, never critical);
- the email branch drops a ``create``/``update`` whose suggested action is
  shorter than five characters, ignores ``action_required`` except on
  ``create`` (a ``create`` without it creates nothing), and resolves a
  missing or unknown ``target_task_id`` to the only open task when there is
  exactly one (Fix B); an ``update``/``close`` with no target does nothing.

``score_answer`` returns ``{"passed", "critical", "outcome"}``: the answer
passes when its outcome is the label's ``task_action`` or one of
``also_accept``, with the labelled ``target_task_id`` for ``update`` and
``close``; it fails critically when it does not pass and its outcome is in
the case's ``critical_on``.
"""

from __future__ import annotations

from typing import Any

# What an answer can amount to; ``critical_on`` lists some of these.
OUTCOMES = ("create", "update", "close", "none", "other_target", "invalid")
# The tool fields whose language the case's ``expect_lang`` governs.
FREE_TEXT = ("title", "suggested_action", "reason")

_ACTIONS = ("create", "update", "close", "none")
_URGENCIES = ("critical", "high", "medium", "low")


def effect(case: dict[str, Any], answer: Any) -> tuple[str, str | None]:
    """``(action, target)`` the engine applies for ``answer`` on this case."""
    from zylch.workers.task_creation import TASK_DECISION_TOOL

    required = TASK_DECISION_TOOL["input_schema"]["required"]
    if not isinstance(answer, dict) or any(key not in answer for key in required):
        return "invalid", None
    if (
        type(answer["action_required"]) is not bool
        or answer["task_action"] not in _ACTIONS
        or answer["urgency"] not in _URGENCIES
        or not isinstance(answer["reason"], str)
        or not isinstance(answer["suggested_action"], str)
    ):
        return "invalid", None
    action = answer["task_action"]
    if action in ("create", "update") and len(answer["suggested_action"].strip()) < 5:
        return "none", None
    if action == "create":
        return ("create", None) if answer["action_required"] else ("none", None)
    if action == "none":
        return "none", None
    open_ids = [task["id"] for task in case["input"].get("open_tasks", [])]
    target = answer.get("target_task_id")
    if target not in open_ids:
        target = open_ids[0] if len(open_ids) == 1 else None
    return (action, target) if target else ("none", None)


def score_answer(case: dict[str, Any], answer: Any) -> dict[str, Any]:
    """Score ``answer`` (the ``task_decision`` input) against ``case``."""
    label = case["label"]
    action, target = effect(case, answer)
    accepted = (label["task_action"], *label.get("also_accept", ()))
    if action in accepted and action in ("update", "close"):
        passed = target == label["target_task_id"]
        outcome = action if passed else "other_target"
    else:
        passed = action in accepted
        outcome = action
    return {
        "passed": passed,
        "critical": not passed and outcome in case["critical_on"],
        "outcome": outcome,
    }
