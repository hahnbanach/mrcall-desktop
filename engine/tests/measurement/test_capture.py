"""Each measurement case reaches its role's call site exactly once, through the engine's own path.

Milestone 10 measures a role by replaying, on several models, the request the engine builds
for each synthetic case (brief D7). These tests run each role's capture harness — a throwaway
profile, a recording client, no network, no key — and hold that every case yields exactly one
request at the role's call site, carrying the role's tool where it has one, built from that
case's own input; that a case the engine would settle without a model is refused instead of
silently measuring nothing; and that each case file keeps the label schema its README
documents, grounded in the input, synthetic, and balanced in classes and languages.

Each case also says which wrong answers are critical (``critical_on``, from which ``critical``
is derived) and which language its scored free text must be in (``expect_lang``, None where
no free text is scored); both follow the rules the role's README states, checked here.
"""

from __future__ import annotations

import copy
import importlib
import json
import re
from collections import Counter

import pytest

from tests.measurement.capture_support import (
    Call,
    CaptureError,
    disposable_profile,
    load_capture,
    load_cases,
    text_language,
    the_request,
)

ROLES = ("REPLY_NEED", "INTENT", "CORRECTION_LEARNING", "SYNC_ANALYSIS")
JUDGE_TOOLS = {"rule": "record_rule", "fact": "record_fact"}
CASE_KEYS = {"id", "lang", "input", "label", "critical", "critical_on", "expect_lang", "why"}


def expected_tool(role, case):
    """The tool the role's call site offers for ``case``; None where the role answers in text."""
    if role == "REPLY_NEED":
        return "reply_need_decision"
    if role == "SYNC_ANALYSIS":
        return "classify_thread"
    if role == "CORRECTION_LEARNING":
        return JUDGE_TOOLS[case["input"]["judge"]]
    return None


def edited_text(correction):
    edited = correction["edited"]
    return edited.get("body") or edited.get("message") or edited.get("text") or ""


def case_marker(role, case):
    """A piece of the case's own input its request must carry."""
    data = case["input"]
    if role == "REPLY_NEED":
        return data["message"]["subject"]
    if role == "INTENT":
        return data["user_input"]
    if role == "CORRECTION_LEARNING":
        return edited_text(data["correction"])
    newest = max(data["messages"], key=lambda m: m["date"])
    return newest["subject"]


def resolve(dotted):
    parts = dotted.split(".")
    for cut in range(len(parts), 0, -1):
        try:
            target = importlib.import_module(".".join(parts[:cut]))
        except ImportError:
            continue
        for name in parts[cut:]:
            target = getattr(target, name)
        return target
    raise ImportError(dotted)


# ─── the capture: one request per case, at the call site ──────────────


@pytest.mark.parametrize("role", ROLES)
def test_every_case_yields_one_request_at_the_role_call_site(role):
    doc = load_cases(role)
    out = load_capture(role).build_requests(doc["cases"])

    assert [item["case_id"] for item in out] == [case["id"] for case in doc["cases"]]
    for case, item in zip(doc["cases"], out):
        request = item["request"]
        assert set(item) == {"case_id", "request"}
        assert json.loads(json.dumps(request)) == request
        assert request["messages"] and isinstance(request["max_tokens"], int)
        tool = expected_tool(role, case)
        names = [t["name"] for t in request.get("tools") or []]
        assert names == ([tool] if tool else []), (case["id"], names)
        marker = json.dumps(case_marker(role, case), ensure_ascii=False)[1:-1]
        assert marker in json.dumps(request, ensure_ascii=False), case["id"]


def test_the_intent_prompt_lists_every_registry_skill():
    doc = load_cases("INTENT")
    out = load_capture("INTENT").build_requests(doc)
    for item in out:
        prompt = item["request"]["messages"][0]["content"]
        assert all(skill["name"] in prompt for skill in doc["skills"]), item["case_id"]


def test_a_reply_need_case_the_screen_answers_is_refused():
    case = copy.deepcopy(load_cases("REPLY_NEED")["cases"][0])
    case["input"]["message"]["body_plain"] += "\nE quando arriva la merce?"
    with pytest.raises(CaptureError, match="0 request"):
        load_capture("REPLY_NEED").build_requests([case])


def test_an_unchanged_correction_is_refused():
    case = copy.deepcopy(load_cases("CORRECTION_LEARNING")["cases"][0])
    case["input"]["correction"]["edited"] = case["input"]["correction"]["proposed"]
    with pytest.raises(CaptureError, match="0 request"):
        load_capture("CORRECTION_LEARNING").build_requests([case])


def test_a_request_from_a_client_built_for_another_role_is_refused():
    call = Call("create_message_sync", "another-role-model", {"messages": [], "tools": []})
    with pytest.raises(CaptureError, match="not for the role"):
        the_request("x-01", [call], model="measurement/capture")


def test_the_throwaway_profile_routes_the_role_and_cannot_build_a_real_client():
    from zylch.llm import make_llm_client, routed_model

    with disposable_profile("MODEL_INTENT", "measurement/capture"):
        assert routed_model("MODEL_INTENT") == "measurement/capture"
        with pytest.raises(RuntimeError, match="API key"):
            make_llm_client(model=routed_model("MODEL_INTENT"))


# ─── the case files: schema, grounding, synthetic data, balance ───────


def label_class(role, case):
    label = case["label"]
    if role == "REPLY_NEED":
        return label["needs_reply"]
    if role == "INTENT":
        return label["primary_skill"]
    if role == "CORRECTION_LEARNING":
        return (case["input"]["judge"], label.get("is_durable_rule", label.get("is_fact_change")))
    return label.get("expected_action", "unlabelled") if label["needs_action"] else None


def check_label(role, doc, case):
    label, data = case["label"], case["input"]
    if role == "REPLY_NEED":
        assert label.keys() == {"needs_reply"} and isinstance(label["needs_reply"], bool)
    elif role == "INTENT":
        assert label.keys() == {"primary_skill"}
        assert label["primary_skill"] in {skill["name"] for skill in doc["skills"]}
    elif role == "SYNC_ANALYSIS":
        assert isinstance(label["needs_action"], bool)
        if label["needs_action"]:
            assert label.get("expected_action", "answer") in ("answer", "reminder")
        else:
            assert label == {"needs_action": False, "expected_action": None}
    elif data["judge"] == "rule":
        assert isinstance(label["is_durable_rule"], bool)
        if label["is_durable_rule"]:
            assert label.keys() == {"is_durable_rule", "rule_must_contain"}
            sent = edited_text(data["correction"]).lower()
            for group in label["rule_must_contain"]:
                assert any(word.lower() in sent for word in group), (case["id"], group)
        else:
            assert label.keys() == {"is_durable_rule"}
    else:
        assert isinstance(label["is_fact_change"], bool)
        if not label["is_fact_change"]:
            assert label.keys() == {"is_fact_change"}
            return
        memory = doc["memories"][data["memory"]]
        assert label["category"] in {fact["category"] for fact in memory["facts"]}
        sent = edited_text(data["correction"])
        drafted = data["correction"]["proposed"]
        drafted = drafted.get("body") or drafted.get("message") or ""
        for group in label["value_must_contain"]:
            assert any(word in sent for word in group), (case["id"], group)
        # The forbidden spellings are the old value's: drafted, then corrected away.
        old = label["value_must_not_contain"]
        assert any(o in drafted for o in old) and not any(o in sent for o in old), case["id"]


def wrong_answers(role, doc, case):
    """The answer classes (README, "Label and scoring") that are wrong for ``case``."""
    label = case["label"]
    if role == "REPLY_NEED":
        return {"needs_reply", "no_reply", "invalid"} - {
            "needs_reply" if label["needs_reply"] else "no_reply"
        }
    if role == "INTENT":
        return {skill["name"] for skill in doc["skills"]} - {label["primary_skill"]} | {"invalid"}
    if role == "SYNC_ANALYSIS":
        if not label["needs_action"]:
            return {"answer", "reminder", "invalid"}
        right = label.get("expected_action")
        return {"none", "invalid"} | ({"answer", "reminder"} - {right} if right else set())
    if not label.get("is_durable_rule", label.get("is_fact_change")):
        return {"record", "invalid"}
    return {"no_record", "invalid"} | ({"old_value"} if case["input"]["judge"] == "fact" else set())


def check_critical(role, doc, case):
    """``critical_on`` lists wrong answers only, ``critical`` is derived, each role's rule holds."""
    critical_on, label = case["critical_on"], case["label"]
    assert case["critical"] is bool(critical_on), case["id"]
    assert len(set(critical_on)) == len(critical_on), case["id"]
    assert set(critical_on) <= wrong_answers(role, doc, case), case["id"]
    if role == "REPLY_NEED":  # silencing a request is the harm; a missing verdict degrades safely
        assert critical_on == (["no_reply"] if label["needs_reply"] else []), case["id"]
    elif role == "INTENT":  # the router has no caller: no wrong answer reaches anyone
        assert critical_on == [], case["id"]
    elif role == "SYNC_ANALYSIS":  # no call falls back to no action, the same miss as "none"
        assert critical_on == (["none", "invalid"] if label["needs_action"] else []), case["id"]
    elif label.get("is_durable_rule", label.get("is_fact_change")):
        # A must-record case: a miss is ordinary; only a fact recorded at its old value harms.
        fact = case["input"]["judge"] == "fact"
        assert critical_on == (["old_value"] if fact else []), case["id"]
    else:
        assert critical_on in ([], ["record"]), case["id"]


def check_expect_lang(role, case):
    """The language bar applies only to the free text a role scores, in the language it needs."""
    expect_lang, label = case["expect_lang"], case["label"]
    if role == "CORRECTION_LEARNING" and label.get("is_durable_rule"):
        # The rule is learned in the correction's own language, as the user wrote it.
        sent = edited_text(case["input"]["correction"])
        assert expect_lang == case["lang"] == text_language(sent), case["id"]
    else:  # no free text scored: REPLY_NEED's reason, SYNC's summary, facts, intent JSON
        assert expect_lang is None, case["id"]


@pytest.mark.parametrize("role", ROLES)
def test_the_case_file_keeps_its_schema_and_labels_its_input(role):
    doc = load_cases(role)
    assert doc["schema"] == 1 and doc["role"] == role
    assert callable(resolve(doc["builder"]))
    ids = [case["id"] for case in doc["cases"]]
    assert ids == [f"{role.lower()}-{n:02d}" for n in range(1, len(ids) + 1)]
    for case in doc["cases"]:
        assert set(case) == CASE_KEYS and case["lang"] in ("it", "en")
        assert isinstance(case["critical"], bool) and case["why"].strip()
        check_label(role, doc, case)
        check_critical(role, doc, case)
        check_expect_lang(role, case)


def test_the_language_check_reads_the_case_sets_own_sentences():
    memories = load_cases("CORRECTION_LEARNING")["memories"]
    assert {text_language(rule) for rule in memories["tipografia"]["rules"]} == {"it"}
    assert {text_language(rule) for rule in memories["studio"]["rules"]} == {"en"}
    assert text_language("Per l'assistenza indirizza i clienti all'email.") == "it"
    assert text_language("Direct customers to the help form.") == "en"
    assert text_language("Supporto via e-mail, help form") is None  # no function word: undecided


@pytest.mark.parametrize("role", ROLES)
def test_the_case_file_is_synthetic_and_balanced(role):
    doc = load_cases(role)
    text = json.dumps(doc, ensure_ascii=False)
    for address in re.findall(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)", text):
        assert address.endswith(".example"), address
    # Only the fictional ranges: Milan or London, then 0000 0xxx. Real mobile ranges such as
    # +39 333 or +39 347 are refused.
    for phone in re.findall(r"\+\d[\d ]{6,}\d", text):
        assert re.fullmatch(r"\+(39 02|44 20) 0000 0\d{3}", phone), phone
    cases = doc["cases"]
    assert len(cases) >= 20
    assert max(Counter(label_class(role, c) for c in cases).values()) <= 0.6 * len(cases)
    langs = Counter(c["lang"] for c in cases)
    assert all(langs[lang] >= 0.35 * len(cases) for lang in ("it", "en")), langs
