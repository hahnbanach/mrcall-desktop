"""Scoring rules of the task roles: TASK_DETECTION, REANALYZE, DEDUP.

Each role's ``score.py`` scores a model's tool input against a case by
what the engine would do with it, and a case's ``critical_on`` names the
wrong outcomes that cause real harm. These tests hold the rules the label
review settled (no network, no key):

- every answer built from a label passes and is never critical;
- every outcome in ``critical_on`` is a reachable wrong answer and fails
  critically; an outcome the engine makes harmless is not listed;
- the reviewed cases score as agreed: ``create`` on an update case and
  ``action_required`` off a ``create`` label are not critical; only
  ``close`` is critical on REANALYZE-03; REANALYZE-05 accepts ``keep`` or an
  ``update`` that does not lower the urgency; cross-party F9 clusters close
  nothing; no answer at all is never critical.
"""

from __future__ import annotations

import functools
import itertools

import pytest

from tests.measurement.task_roles_env import fixture_module, load_cases

ROLES = ("TASK_DETECTION", "REANALYZE", "DEDUP")


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """Override the root conftest's Supabase-era autouse fixture: no storage here."""
    yield


@functools.cache
def scorer(role: str):
    """Import ``<ROLE>/score.py`` by path, as the measurement scripts do."""
    return fixture_module(role, "score")


def _case(role, number):
    return load_cases(role)["cases"][number - 1]


def _score(role, case, answer):
    return scorer(role).score_answer(case, answer)


def _open_ids(case):
    return [task["id"] for task in case["input"].get("open_tasks", [])]


def _accepted(role, case):
    label = case["label"]
    primary = label["task_action"] if role == "TASK_DETECTION" else label["action"]
    return (primary, *label.get("also_accept", ()))


def td_answer(action, target="", required=None):
    return {
        "task_action": action,
        "action_required": action in ("create", "update") if required is None else required,
        "urgency": "medium",
        "suggested_action": "Rispondere al cliente con i dettagli richiesti",
        "reason": "Il cliente aspetta una risposta su questa richiesta",
        "title": "Rispondere al cliente",
        "target_task_id": target,
    }


def ra_answer(action, urgency=None):
    answer = {"action": action, "reason": "Lo stato del thread lo richiede", "waiting_on": "us"}
    return {**answer, "urgency": urgency} if urgency else answer


def f9_answer(*groups):
    clusters = [
        {"topic": "same problem", "keeper_id": k, "duplicate_ids": list(d), "rationale": "same"}
        for k, *d in groups
    ]
    return {"clusters": clusters}


def _same_party_strays(case):
    """Same-party task pairs outside one labelled group: what F9 could wrongly close."""
    from zylch.workers.task_contact_identity import task_identity_key

    group_of = {}
    for cluster in case["label"]["clusters"]:
        for member in (cluster["keeper_id"], *cluster["duplicate_ids"]):
            group_of[member] = cluster["keeper_id"]
    party = {task["id"]: task_identity_key(task) for task in case["input"]["open_tasks"]}
    strays = []
    for a, b in itertools.combinations(party, 2):
        same_party = party[a] is not None and party[a] == party[b]
        same_group = group_of.get(a) is not None and group_of.get(a) == group_of.get(b)
        if same_party and not same_group:
            strays.append((a, b))
    return strays


def label_answers(role, case):
    """Answers that state the labelled decision (and each accepted alternative)."""
    label = case["label"]
    if role == "TASK_DETECTION":
        return [
            td_answer(a, label["target_task_id"] if a in ("update", "close") else "")
            for a in _accepted(role, case)
        ]
    if role == "REANALYZE":
        floor = label.get("urgency_at_least")
        return [ra_answer(a, floor if a == "update" else None) for a in _accepted(role, case)]
    if case["call_site"] == "dedup.f8":
        return [{**label, "reason": "Same contact, judged by the arbiter."}]
    return [f9_answer(*[(c["keeper_id"], *c["duplicate_ids"]) for c in label["clusters"]])]


def outcome_answer(role, case, outcome):
    """An answer the scorer reads as ``outcome`` on this case."""
    label, ids = case["label"], _open_ids(case)
    if role == "TASK_DETECTION":
        if outcome in ("create", "none"):
            return td_answer(outcome)
        if outcome in ("update", "close"):
            return td_answer(outcome, ids[0])
        action = next(a for a in _accepted(role, case) if a in ("update", "close"))
        return td_answer(action, next(i for i in ids if i != label["target_task_id"]))
    if role == "REANALYZE":
        return ra_answer("update", "low") if outcome == "update_lowered" else ra_answer(outcome)
    if case["call_site"] == "dedup.f8":
        keeper = {"merge": ids[0], "invalid_keeper": "not-a-task"}.get(outcome)
        if outcome == "other_keeper":
            keeper = next(i for i in ids if i != label["keeper_id"])
        return {"is_duplicate_group": outcome != "distinct", "keeper_id": keeper or ""}
    if outcome == "wrong_close":
        return f9_answer(_same_party_strays(case)[0])
    if outcome == "other_keeper":
        first = label["clusters"][0]
        swapped = (first["duplicate_ids"][0], first["keeper_id"], *first["duplicate_ids"][1:])
        rest = [(c["keeper_id"], *c["duplicate_ids"]) for c in label["clusters"][1:]]
        return f9_answer(swapped, *rest)
    return f9_answer()  # wrong_groups on a case with clusters


@pytest.mark.parametrize("role", ROLES)
def test_label_answers_pass_and_are_never_critical(role):
    for case in load_cases(role)["cases"]:
        for answer in label_answers(role, case):
            result = _score(role, case, answer)
            assert result["passed"] and not result["critical"], (case["id"], answer, result)


@pytest.mark.parametrize("role", ROLES)
def test_critical_on_lists_reachable_wrong_outcomes(role):
    for case in load_cases(role)["cases"]:
        outcomes = scorer(role).OUTCOMES
        outcomes = outcomes[case["call_site"]] if isinstance(outcomes, dict) else outcomes
        tokens = case["critical_on"]
        assert len(set(tokens)) == len(tokens) and set(tokens) <= set(outcomes), case["id"]
        assert "invalid" not in tokens, case["id"]  # no decision: the item stays pending
        ids = _open_ids(case)
        if role == "TASK_DETECTION":
            assert ids or not {"update", "close"} & set(tokens), case["id"]
            assert len(ids) >= 2 or "other_target" not in tokens, case["id"]
        elif role == "REANALYZE":
            assert "urgency_at_least" in case["label"] or "update_lowered" not in tokens
        elif case["call_site"] == "dedup.f8":
            assert not case["label"]["is_duplicate_group"] or not tokens, case["id"]
        else:  # a harmful F9 close exists exactly when a same-party stray pair does
            assert ("wrong_close" in tokens) is bool(_same_party_strays(case)), case["id"]
            assert set(tokens) <= {"wrong_close"}, case["id"]
        for outcome in tokens:
            result = _score(role, case, outcome_answer(role, case, outcome))
            assert result == {"passed": False, "critical": True, "outcome": outcome}, case["id"]


@pytest.mark.parametrize("role", ROLES)
def test_no_answer_is_never_critical(role):
    for case in load_cases(role)["cases"]:
        result = _score(role, case, None)
        assert result == {"passed": False, "critical": False, "outcome": "invalid"}


def test_task_detection_review_findings():
    quote = _case("TASK_DETECTION", 5)
    target = quote["label"]["target_task_id"]
    created = _score("TASK_DETECTION", quote, td_answer("create"))
    assert created == {"passed": False, "critical": False, "outcome": "create"}
    # action_required is read on create only: the right update passes without it.
    assert _score("TASK_DETECTION", quote, td_answer("update", target, required=False))["passed"]
    assert _score("TASK_DETECTION", quote, td_answer("update", "", required=False))["passed"]
    assert _score("TASK_DETECTION", quote, td_answer("none"))["critical"]
    lead = _case("TASK_DETECTION", 1)
    silent = _score("TASK_DETECTION", lead, td_answer("create", required=False))
    assert silent == {"passed": False, "critical": True, "outcome": "none"}
    two_tasks = _case("TASK_DETECTION", 20)
    flyer = next(i for i in _open_ids(two_tasks) if i != two_tasks["label"]["target_task_id"])
    wrong = _score("TASK_DETECTION", two_tasks, td_answer("update", flyer))
    assert wrong == {"passed": False, "critical": True, "outcome": "other_target"}
    thanks = _case("TASK_DETECTION", 21)
    assert _score("TASK_DETECTION", thanks, td_answer("none"))["passed"]
    assert _score("TASK_DETECTION", thanks, td_answer("close", ""))["critical"]
    assert not _score("TASK_DETECTION", thanks, td_answer("create"))["critical"]


def test_reanalyze_review_findings():
    ack = _case("REANALYZE", 3)
    assert _score("REANALYZE", ack, ra_answer("update", "critical"))["critical"] is False
    assert _score("REANALYZE", ack, ra_answer("close"))["critical"] is True
    no_rush = _case("REANALYZE", 5)
    for answer in (ra_answer("keep"), ra_answer("update", "medium"), ra_answer("update")):
        assert _score("REANALYZE", no_rush, answer)["passed"], answer
    lowered = _score("REANALYZE", no_rush, ra_answer("update", "low"))
    assert lowered == {"passed": False, "critical": False, "outcome": "update_lowered"}
    assert _score("REANALYZE", no_rush, ra_answer("Close"))["critical"]


def test_dedup_review_findings():
    traps = _case("DEDUP", 12)  # four different parties
    ids = _open_ids(traps)
    merged = _score("DEDUP", traps, f9_answer((ids[0], ids[1])))
    assert merged == {"passed": False, "critical": False, "outcome": "wrong_groups"}
    jobs = _case("DEDUP", 14)  # one client, distinct jobs: the engine lets the merge through
    assert _score("DEDUP", jobs, f9_answer(_same_party_strays(jobs)[0]))["critical"]
    distinct = _case("DEDUP", 2)
    keeper = _open_ids(distinct)[0]
    merge = {"is_duplicate_group": True, "keeper_id": keeper}
    assert _score("DEDUP", distinct, merge)["critical"]
    skipped = {"is_duplicate_group": True, "keeper_id": "not-a-task"}
    assert _score("DEDUP", distinct, skipped)["critical"] is False
    duplicates = _case("DEDUP", 1)
    assert not _score("DEDUP", duplicates, {"is_duplicate_group": False})["critical"]
