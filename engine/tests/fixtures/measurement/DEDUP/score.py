"""Reference scoring of a DEDUP answer against its case (see README).

``dedup.f8`` — the answer is the ``dedup_decision`` input. As in
``run_dedup_sweep``, a truthy ``is_duplicate_group`` with a ``keeper_id``
from the cluster closes the other tasks (``merge``); a keeper outside the
cluster makes the sweep skip it (``invalid_keeper``); anything else closes
nothing (``distinct``). A merge around another keeper is ``other_keeper``.

``dedup.f9`` — the answer is the ``topic_dedup_decision`` input. Two
readings:

- what the engine would close: the answer passed through the sweep's own
  filter (``_validate_decision``: unknown or reused ids dropped, pairs of
  different or unknown parties refused). Closing a task outside its
  labelled group is ``wrong_close``;
- what the model decided: each answered cluster read as the group
  ``{keeper_id} ∪ duplicate_ids`` (one-member clusters ignored, a reused id
  is ``wrong_groups``). The groups must equal the label's
  (``wrong_groups`` otherwise) and keep the labelled keepers
  (``other_keeper`` otherwise); then the answer is a ``match``.

``score_answer`` returns ``{"passed", "critical", "outcome"}``; it fails
critically when it does not pass and its outcome is in ``critical_on``.
"""

from __future__ import annotations

from typing import Any

# What an answer can amount to; ``critical_on`` lists some of these.
OUTCOMES = {
    "dedup.f8": ("merge", "distinct", "other_keeper", "invalid_keeper", "invalid"),
    "dedup.f9": ("match", "other_keeper", "wrong_groups", "wrong_close", "invalid"),
}
# The sweeps' prompts set no output language: no free text is language-checked.
FREE_TEXT = ()


def score_answer(case: dict[str, Any], answer: Any) -> dict[str, Any]:
    """Score ``answer`` (the call site's tool input) against ``case``."""
    if case["call_site"] == "dedup.f8":
        outcome, passed = _cluster_arbiter(case, answer)
    else:
        outcome, passed = _topic_sweep(case, answer)
    return {
        "passed": passed,
        "critical": not passed and outcome in case["critical_on"],
        "outcome": outcome,
    }


def _cluster_arbiter(case: dict[str, Any], answer: Any) -> tuple[str, bool]:
    label = case["label"]
    if not isinstance(answer, dict):
        return "invalid", False
    ids = {task["id"] for task in case["input"]["open_tasks"]}
    if not bool(answer.get("is_duplicate_group")):
        outcome = "distinct"
    elif answer.get("keeper_id") not in ids:
        outcome = "invalid_keeper"
    elif label["is_duplicate_group"] and answer["keeper_id"] != label["keeper_id"]:
        outcome = "other_keeper"
    else:
        outcome = "merge"
    return outcome, outcome == ("merge" if label["is_duplicate_group"] else "distinct")


def _topic_sweep(case: dict[str, Any], answer: Any) -> tuple[str, bool]:
    from zylch.workers.task_topic_dedup import _validate_decision

    if not isinstance(answer, dict) or not isinstance(answer.get("clusters"), list):
        return "invalid", False
    tasks = {task["id"]: task for task in case["input"]["open_tasks"]}
    labelled = {
        frozenset([c["keeper_id"], *c["duplicate_ids"]]): c["keeper_id"]
        for c in case["label"]["clusters"]
    }
    group_of = {member: group for group in labelled for member in group}
    for cluster in _validate_decision(answer, set(tasks), tasks):
        keeper = group_of.get(cluster["keeper_id"])
        if any(keeper is None or group_of.get(d) != keeper for d in cluster["duplicate_ids"]):
            return "wrong_close", False
    answered: dict[frozenset, Any] = {}
    seen: set = set()
    for cluster in answer["clusters"]:
        if not isinstance(cluster, dict):
            return "wrong_groups", False
        keeper = cluster.get("keeper_id")
        duplicates = cluster.get("duplicate_ids")
        members = [keeper, *(duplicates if isinstance(duplicates, list) else [])]
        group = frozenset(m for m in members if isinstance(m, str))
        if len(group) < 2:
            continue
        if group & seen:
            return "wrong_groups", False
        seen |= group
        answered[group] = keeper
    if set(answered) != set(labelled):
        return "wrong_groups", False
    if any(answered[group] != labelled[group] for group in labelled):
        return "other_keeper", False
    return "match", True
