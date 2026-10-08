"""``measurement_scoring.py`` against the committed cases: the README rules, read as code.

Answers built from each label pass and are never critical; the wrong answers
each README names fail, critically exactly when ``critical_on`` lists them.
Also held: Markdown emphasis and non-breaking spaces never hide a fact
(label review G3), the language bar skips a short answer and fails a long
one in the other language, the smoke roles' form bars, a CHAT or TASK_SOLVE
answer that must not be empty, every tool input checked on its schema, and
the non-empty bar failing an empty answer in each of its three readings: a
tool called with nothing, an agent turn with no call and no text, a text
answer that is blank.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import measurement_common as common  # noqa: E402
import measurement_scoring as scoring  # noqa: E402

PREFIX = {
    "it": "Rispondere sempre ai clienti con la regola: ",
    "en": "Always tell the customer about the rule: ",
}


def cases(role):
    document = common.load_document(role)
    requests = {e["case_id"]: e["request"] for e in common.load_requests(role)["requests"]}
    return document, [(case, requests[case["id"]]) for case in document["cases"]]


def call(name, **given):
    return {"calls": [{"name": name, "input": given}], "text": "", "stop_reason": "tool_use"}


def scored(role, document, case, request, answer):
    return scoring.score(role, case, answer, request, document)


def right_answer(role, case, request):
    label, tool = case["label"], scoring.answer_tool(role, request)
    if role == "REPLY_NEED":
        return call(tool, verdicts=[{"index": 0, "needs_reply": label["needs_reply"]}])
    if role == "INTENT":
        text = "```json\n" + json.dumps({"primary_skill": label["primary_skill"]}) + "\n```"
        return {"calls": [], "text": text, "stop_reason": "end_turn"}
    if role == "SYNC_ANALYSIS":
        action = label.get("expected_action", "answer") if label["needs_action"] else None
        return call(tool, summary="ok", open=label["needs_action"], expected_action=action)
    if case["input"]["judge"] == "rule":
        if not label["is_durable_rule"]:
            return call(tool, is_durable_rule=False, rule="", why="one-off")
        words = " ".join(group[0] for group in label["rule_must_contain"])
        return call(tool, is_durable_rule=True, rule=PREFIX[case["expect_lang"]] + words, why="x")
    if not label["is_fact_change"]:
        return call(tool, is_fact_change=False, category="", key="", value="")
    value = " ".join(group[0] for group in label["value_must_contain"])
    return call(tool, is_fact_change=True, category=label["category"], key="k", value=value)


@pytest.mark.parametrize("role", ["REPLY_NEED", "INTENT", "SYNC_ANALYSIS", "CORRECTION_LEARNING"])
def test_an_answer_built_from_the_label_passes_every_reading(role):
    document, every = cases(role)
    for case, request in every:
        result = scored(role, document, case, request, right_answer(role, case, request))
        assert result["label_match"] and not result["critical"], (case["id"], result)
        assert result["bars_ok"], (case["id"], result["bars"])


@pytest.mark.parametrize("role", ["REPLY_NEED", "SYNC_ANALYSIS", "CORRECTION_LEARNING"])
def test_no_call_fails_the_tool_bar_and_is_critical_only_where_listed(role):
    document, every = cases(role)
    for case, request in every:
        result = scored(role, document, case, request, {"calls": [], "text": "Fatto."})
        assert result["bars"]["tool_called"] is False and not result["bars_ok"]
        assert not result["label_match"] and result["outcome"] == "invalid"
        assert result["critical"] == ("invalid" in case["critical_on"]), case["id"]


def test_reply_need_silencing_a_request_is_critical_and_the_reverse_is_not():
    document, every = cases("REPLY_NEED")
    for case, request in every:
        flipped = call(
            "reply_need_decision",
            verdicts=[{"index": 0, "needs_reply": not case["label"]["needs_reply"]}],
        )
        result = scored("REPLY_NEED", document, case, request, flipped)
        assert not result["label_match"]
        assert result["critical"] == case["label"]["needs_reply"], case["id"]


def test_correction_learning_reads_old_values_and_the_rule_s_language():
    document, every = cases("CORRECTION_LEARNING")
    for case, request in every:
        label = case["label"]
        if label.get("is_fact_change"):
            old = call("record_fact", is_fact_change=True, category=label["category"], key="k")
            old["calls"][0]["input"]["value"] = label["value_must_not_contain"][0]
            result = scored("CORRECTION_LEARNING", document, case, request, old)
            assert result["outcome"] == "old_value" and result["critical"], case["id"]
        if label.get("is_durable_rule"):
            other = {"it": "en", "en": "it"}[case["expect_lang"]]
            words = " ".join(group[0] for group in label["rule_must_contain"])
            translated = call("record_rule", is_durable_rule=True, rule=PREFIX[other] + words)
            result = scored("CORRECTION_LEARNING", document, case, request, translated)
            assert not result["label_match"] and not result["critical"], case["id"]


def test_g3_emphasis_and_thin_spaces_never_hide_a_fact():
    document, every = cases("WEB_SEARCH")
    case, request = every[0]
    thin = chr(0x202F)  # a narrow no-break space between the number and its noun
    text = f"Il codice destinatario è da **7**{thin}caratteri alfanumerici per i privati."
    result = scored(
        "WEB_SEARCH", document, case, request, {"text": text, "stop_reason": "end_turn"}
    )
    assert result["label_match"], result
    assert scoring.normalize("USER_COMPANY e {user_email}") == "USER_COMPANY e {user_email}"
    assert scoring.normalize("*nota* e __bold__ e ~~via~~") == "nota e bold e via"


def test_the_language_bar_skips_a_short_answer_and_fails_a_long_one_in_the_other_language():
    assert scoring.language_bar("Inviata.", "en")["ok"] is None
    long_en = "The customer wants the quote for the windows before the end of the week."
    assert scoring.language_bar(long_en, "en")["ok"] is True
    assert scoring.language_bar(long_en, "it")["ok"] is False
    assert scoring.language_bar(long_en, None)["ok"] is None


def test_a_text_no_function_word_reads_skips_the_language_bar_and_the_label():
    # Audit B1: correction_learning-01's rule by DeepSeek, eleven words, no hit in
    # either list. Unreadable is not wrong: the bar and the rule's language skip it.
    rule = "Per assistenza, indirizza i clienti all'email anziché offrire richiamate telefoniche."
    assert scoring.no_hits(rule) and scoring.language_bar(rule, "it")["ok"] is None
    tie = "Per assistenza, indirizza i clienti all'email and the richiamate di telefono"
    assert scoring.language_bar(tie, "it")["ok"] is False  # a tie with hits still fails
    document, every = cases("CORRECTION_LEARNING")
    case, request = next((c, r) for c, r in every if c["id"] == "correction_learning-01")
    answer = call("record_rule", is_durable_rule=True, rule=rule)
    result = scored("CORRECTION_LEARNING", document, case, request, answer)
    assert result["label_match"] and result["bars"]["language"] is None, result


def test_the_smoke_form_bars_read_the_label():
    document, every = cases("NARRATION")
    case, request = next((c, r) for c, r in every if c["label"].get("starts_with_any"))
    good = {"text": '"Sto cercando la fattura di Kestrel nelle email."', "stop_reason": "end_turn"}
    result = scored("NARRATION", document, case, request, good)
    assert result["label_match"] and result["bars_ok"], result
    fallback = {"text": "Sto pensando alla tua richiesta.", "stop_reason": "max_tokens"}
    bars = scored("NARRATION", document, case, request, fallback)["bars"]
    assert bars["not_equal"] is False and bars["max_chars"] is True
    long_text = {"text": "Cerco la fattura\n" + "x" * 90, "stop_reason": "end_turn"}
    bars = scored("NARRATION", document, case, request, long_text)["bars"]
    assert bars["single_line"] is False and bars["max_chars"] is False
    assert bars["starts_with_any"] is False


def test_an_agent_answer_the_label_wants_must_not_be_empty_and_calls_are_schema_checked():
    document, every = cases("TASK_SOLVE")
    case, request = next((c, r) for c, r in every if c["label"]["first_call"] is None)
    silent = scored("TASK_SOLVE", document, case, request, {"calls": [], "text": " ", "first": []})
    assert "answer_empty" in silent["failures"] and not silent["label_match"]
    bad = {"name": "send_email", "input": {"subject": 3}}
    turn = {"calls": [bad], "text": "", "first": [bad], "later": []}
    assert scored("TASK_SOLVE", document, case, request, turn)["bars"]["valid_input"] is False


def test_the_schema_subset_checks_types_required_enums_and_closed_objects():
    schema = {
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": ["string", "null"], "enum": ["x", None]},
        },
        "required": ["a"],
        "additionalProperties": False,
    }
    assert scoring.schema_errors(schema, {"a": 1, "b": None}) == []
    assert scoring.schema_errors(schema, {"a": True})
    assert scoring.schema_errors(schema, {"b": "x"})
    assert scoring.schema_errors(schema, {"a": 1, "b": "y"})
    assert scoring.schema_errors(schema, {"a": 1, "c": 2})


def empty_answer(role, request):
    """The empty answer of each reading of the non-empty bar."""
    tool = scoring.answer_tool(role, request)
    if tool is not None:  # the role's tool, called with nothing in it
        return {"calls": [{"name": tool, "input": {}}], "text": "", "stop_reason": "tool_use"}
    return {"calls": [], "text": " \n ", "first": [], "later": [], "stop_reason": "end_turn"}


@pytest.mark.parametrize("role", ["REPLY_NEED", "TASK_SOLVE", "INTENT", "NARRATION"])
def test_the_non_empty_bar_fails_an_empty_answer_in_each_reading(role):
    # REPLY_NEED answers through its tool, TASK_SOLVE is an agent turn, INTENT and
    # NARRATION answer in text: the bar's three branches.
    document, every = cases(role)
    case, request = every[0]
    empty = scored(role, document, case, request, empty_answer(role, request))
    assert empty["bars"]["non_empty"] is False and not empty["bars_ok"], empty["bars"]
    given = {"calls": [], "text": "Fatto.", "first": [], "later": [], "stop_reason": "end_turn"}
    if role in ("REPLY_NEED", "INTENT"):
        given = right_answer(role, case, request)
    assert scored(role, document, case, request, given)["bars"]["non_empty"] is True
