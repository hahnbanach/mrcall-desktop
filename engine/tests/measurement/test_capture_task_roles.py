"""Capture harnesses of the task roles: TASK_DETECTION, REANALYZE, DEDUP.

Milestone 10 measures each role by replaying, on several models, the
request the engine builds for that role and scoring the answer against a
label. The case sets live in ``tests/fixtures/measurement/<ROLE>/`` with a
``capture.py`` harness each. These tests hold the contract the measurement
relies on, with no network and no key:

- every committed case — the authored set, ``cases.json`` with any reserve a
  trim moved (``case_sets.py``) — drives the role's own code path to exactly one
  request, from the role's call site, routed through the role's model key,
  offering the role's tool;
- the request is JSON-serialisable and pinned to the case's clock, so it is
  the same on any day;
- labels are well formed and refer to tasks the case actually contains;
  the label classes and the two languages are balanced;
- ``expect_lang`` is the language the captured prompt requires (none for
  DEDUP, whose prompts set no output language);
- the cases are synthetic (``*.example`` addresses and fictional numbers);
- a capture leaves the process environment and the storage singletons as
  it found them, and refuses a case that produces no request.

The scoring rules (``critical_on``, ``score.py``) are tested in
``test_scoring_task_roles.py``.
"""

from __future__ import annotations

import functools
import json
import os
import re
from collections import Counter
from datetime import UTC, datetime

import pytest

from tests.measurement.task_roles_env import (
    FIXTURES,
    CaptureError,
    fixture_module,
    load_authored,
    parse_instant,
)

ROLES = ("TASK_DETECTION", "REANALYZE", "DEDUP")
# The authored set (case_sets.py): the measured cases and any a trim moved to reserve.
CASE_FILES = ("cases.json", "reserve.json")
# The call sites of each role and the tool each one offers the model.
TOOLS = {
    "TASK_DETECTION": {"task.detect": "task_decision"},
    "REANALYZE": {"f4.reanalyze": "reanalyze_decision"},
    "DEDUP": {"dedup.f8": "dedup_decision", "dedup.f9": "topic_dedup_decision"},
}
CASE_KEYS = {"id", "lang", "expect_lang", "call_site", "input", "label", "critical_on"}
CASE_KEYS |= {"critical", "why"}
# The product's own call-notification relay domain (the sender
# zylch.utils.notifier_senders recognises, and its message ids); every
# other address is invented, and a WhatsApp chat id is a fictional number
# at WhatsApp's own domain.
RELAY_DOMAIN = "@transactional.mrcall.ai"
WHATSAPP_JID = re.compile(r"390200000\d{3}@s\.whatsapp\.net")
FICTIONAL_PHONES = (
    re.compile(r"\+39 02 0000 0\d{3}"),
    re.compile(r"\+390200000\d{3}"),
    re.compile(r"\+44 1632 960 \d{3}"),
)
# The trained prompt's language instruction, the one the free text answers to.
LANGUAGE_RULE = re.compile(r"Write suggested actions, titles and reasons in (Italian|English)")
LANGUAGES = {"Italian": "it", "English": "en"}


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """Override the root conftest's Supabase-era autouse fixture: no storage here."""
    yield


@functools.cache
def harness(role: str):
    """Import ``<ROLE>/capture.py`` by path, as the measurement scripts do."""
    return fixture_module(role, "capture")


@functools.cache
def captured(role: str):
    """Every committed case of ``role`` captured once (shared by the tests below)."""
    cases = load_authored(role)["cases"]
    return cases, harness(role).build_requests(cases)


def _task_ids(case):
    spec = case["input"]
    tasks = spec.get("open_tasks", []) + ([spec["task"]] if "task" in spec else [])
    return {task["id"] for task in tasks}


def _check_label(role, case):
    label = case["label"]
    ids = _task_ids(case)
    if role == "TASK_DETECTION":
        actions = ("create", "update", "close", "none")
        accepted = (label["task_action"], *label.get("also_accept", ()))
        assert set(label) <= {"task_action", "action_required", "target_task_id", "also_accept"}
        assert all(a in actions for a in accepted) and len(set(accepted)) == len(accepted)
        # action_required is scored on create only, where false suppresses the task.
        assert ("action_required" in label) is (label["task_action"] == "create")
        assert label.get("action_required", True) is True
        if {"update", "close"} & set(accepted):
            assert label["target_task_id"] in ids
        else:
            assert "target_task_id" not in label
        assert sum(1 for mail in case["input"]["emails"] if mail.get("pending")) == 1
    elif role == "REANALYZE":
        accepted = (label["action"], *label.get("also_accept", ()))
        assert set(label) <= {"action", "also_accept", "urgency_at_least"}
        assert all(a in ("keep", "close", "update") for a in accepted)
        assert len(set(accepted)) == len(accepted)
        if "urgency_at_least" in label:
            assert "update" in accepted
            assert label["urgency_at_least"] in ("low", "medium", "high", "critical")
    elif case["call_site"] == "dedup.f8":
        assert isinstance(label["is_duplicate_group"], bool)
        if label["is_duplicate_group"]:
            assert label["keeper_id"] in ids
        else:
            assert "keeper_id" not in label
    else:
        seen = set()
        for cluster in label["clusters"]:
            members = {cluster["keeper_id"], *cluster["duplicate_ids"]}
            assert cluster["keeper_id"] not in cluster["duplicate_ids"]
            assert len(members) >= 2 and members <= ids and not members & seen
            seen |= members
        assert len(ids) >= 4  # the topic sweep skips smaller open lists


def _label_class(role, case):
    label = case["label"]
    if role == "TASK_DETECTION":
        return label["task_action"]
    if role == "REANALYZE":
        return label["action"]
    if case["call_site"] == "dedup.f8":
        return "duplicates" if label["is_duplicate_group"] else "distinct"
    return "duplicates" if label["clusters"] else "distinct"


@pytest.mark.parametrize("role", ROLES)
def test_case_document_is_well_formed(role):
    document = load_authored(role)
    assert document["schema"] == 1 and document["role"] == role
    builders = document["builder"]
    sites = TOOLS[role]
    if isinstance(builders, dict):  # one builder per call site (DEDUP)
        assert set(builders) == set(sites)
    else:
        assert builders.startswith("zylch.")
    ids = [case["id"] for case in document["cases"]]
    assert len(ids) == len(set(ids))
    for number, case in enumerate(document["cases"], 1):
        assert set(case) == CASE_KEYS, case["id"]
        assert case["id"] == f"{role.lower()}-{number:02d}"
        assert case["lang"] in ("it", "en")
        assert case["call_site"] in sites
        assert case["critical"] is bool(case["critical_on"])  # derived, never set by hand
        assert len(case["why"]) > 40
        parse_instant(case["input"]["now"])
        _check_label(role, case)


@pytest.mark.parametrize("role", ROLES)
def test_expect_lang_follows_the_role_rule(role):
    for case in load_authored(role)["cases"]:
        if role == "DEDUP":
            assert case["expect_lang"] is None, case["id"]  # no output language is set
        else:  # the owner's language, whatever the language of the mail
            assert case["expect_lang"] == case["input"]["profile"], case["id"]


@pytest.mark.parametrize("role", ROLES)
def test_label_classes_and_languages_are_balanced(role):
    cases = load_authored(role)["cases"]
    assert 18 <= len(cases) <= 24
    classes = Counter(_label_class(role, case) for case in cases)
    assert len(classes) >= 2 and max(classes.values()) <= 0.6 * len(cases)
    languages = Counter(case["lang"] for case in cases)
    assert min(languages["it"], languages["en"]) >= 0.4 * len(cases)
    assert 0 < sum(case["critical"] for case in cases) < len(cases)
    if role == "DEDUP":
        sites = Counter(case["call_site"] for case in cases)
        assert sites["dedup.f8"] >= 8 and sites["dedup.f9"] >= 8


@pytest.mark.parametrize("role", ROLES)
def test_cases_are_synthetic(role):
    files = [FIXTURES / role / name for name in CASE_FILES]
    texts = [path.read_text(encoding="utf-8") for path in files if path.is_file()]
    if role == "TASK_DETECTION":
        texts += [p.read_text(encoding="utf-8") for p in (FIXTURES / role).glob("*.txt")]
        texts.append((FIXTURES / role / "profiles.json").read_text(encoding="utf-8"))
    for text in texts:
        for address in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text):
            fictional = address.endswith(".example") or WHATSAPP_JID.fullmatch(address)
            assert address.endswith(RELAY_DOMAIN) or fictional, address
        for number in re.findall(r"\+\d[\d ]{7,}\d", text):
            assert any(p.fullmatch(number) for p in FICTIONAL_PHONES), number


@pytest.mark.parametrize("role", ROLES)
def test_each_case_captures_one_request_from_its_call_site(role):
    cases, requests = captured(role)
    assert [item["case_id"] for item in requests] == [case["id"] for case in cases]
    for case, item in zip(cases, requests):
        request = item["request"]
        assert item["call_site"] == case["call_site"]
        assert TOOLS[role][case["call_site"]] in [tool["name"] for tool in request["tools"]]
        assert request["max_tokens"] > 0 and request["system"]
        assert [message["role"] for message in request["messages"]] == ["user"]
        json.dumps(request)  # the measurement stores and replays it as JSON
        if role == "TASK_DETECTION":  # score.py resolves targets among the tasks shown
            for task_id in _task_ids(case):
                assert task_id in request["messages"][0]["content"], case["id"]


@pytest.mark.parametrize("role", ROLES)
def test_expect_lang_is_the_language_the_prompt_requires(role):
    cases, requests = captured(role)
    for case, item in zip(cases, requests):
        system = " ".join(block["text"] for block in item["request"]["system"])
        rules = {LANGUAGES[name] for name in LANGUAGE_RULE.findall(system)}
        assert rules == ({case["expect_lang"]} if case["expect_lang"] else set()), case["id"]


@pytest.mark.parametrize("role", ROLES)
def test_requests_are_pinned_to_the_case_clock(role):
    cases, requests = captured(role)
    today = datetime.now(UTC).date().isoformat()  # the real clock the builders would read
    for case, item in zip(cases, requests):
        day = case["input"]["now"][:10]
        text = json.dumps(item["request"], ensure_ascii=False)
        if role == "TASK_DETECTION":
            assert f"Date: {day}" in text
        elif role == "REANALYZE":
            assert f"Today's date: {day}" in text
        elif case["call_site"] == "dedup.f9":
            assert f"Today is {day}." in text
        if today != day and today not in json.dumps(case["input"], ensure_ascii=False):
            assert today not in text, f"{case['id']} leaked the real date"


def test_capture_restores_the_environment_and_storage():
    from zylch.config import settings
    from zylch.storage import database

    case = load_authored("REANALYZE")["cases"][0]
    before = dict(os.environ)
    identity = (settings.email_address, settings.email_aliases)
    harness("REANALYZE").build_requests([case])
    assert dict(os.environ) == before
    assert (settings.email_address, settings.email_aliases) == identity
    assert database._engine is None


def _copy(role, index=0):
    return json.loads(json.dumps(load_authored(role)["cases"][index]))


def test_capture_refuses_a_case_without_its_request():
    case = _copy("TASK_DETECTION")
    for mail in case["input"]["emails"]:
        mail.pop("pending", None)  # already task-processed: nothing to detect
    with pytest.raises(CaptureError, match="0 LLM calls"):
        harness("TASK_DETECTION").build_requests([case])
    case = _copy("DEDUP")
    case["call_site"] = "dedup.f9"  # two open tasks: the topic sweep never calls
    with pytest.raises(CaptureError, match="0 LLM calls"):
        harness("DEDUP").build_requests([case])


def test_capture_refuses_a_request_from_another_call_site():
    case = _copy("REANALYZE")
    case["call_site"] = "task.detect"
    with pytest.raises(CaptureError, match="call site 'f4.reanalyze'"):
        harness("REANALYZE").build_requests([case])
