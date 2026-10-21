"""How ``measure_roles.py`` scores one answer (milestone 10, brief D7; each role's README).

An answer is ``{"calls": [{"name", "input"}], "text", "stop_reason", "first",
"later"}``: the tool calls and all the text of the turn (label review G4: the
executor shows every text block, so a recap written beside a send counts),
the last stop reason, and for the agent roles the calls of the answer to the
captured request (``first``) and of every answer after it (``later``). It gets
three readings, each exactly as the role's README documents it:

- **label match** — TASK_DETECTION, REANALYZE and DEDUP through their
  ``score.py``; REPLY_NEED, INTENT, CORRECTION_LEARNING and SYNC_ANALYSIS by
  their answer classes; CHAT, TASK_SOLVE and the smoke roles through
  ``tests/measurement/conversation_judge.py``, plus "a non-empty answer"
  where a CHAT or TASK_SOLVE label asks for one (``answer: {}``);
- **critical** — only an outcome, class or failure kind the case's
  ``critical_on`` lists (rule G1 for the agent roles): a case whose
  ``critical_on`` is empty is never critical;
- **mechanical bars** — the role's tool called (the decision roles answering
  through one tool), every tool input valid against its schema (a subset of
  JSON Schema: type, required, properties, enum, items, additionalProperties
  false, anyOf/oneOf), a non-empty answer, the language (below) and, for the
  smoke roles, the form checks their labels carry (``max_chars``,
  ``min_chars``, ``single_line``, ``starts_with_any``, ``not_equal``,
  ``no_headings``, ``complete``). A bar that does not apply is ``None``.

**Text hygiene (G3).** Before every ``contains`` or regular-expression check
— of the text and of tool arguments — Markdown emphasis (``**x**``, ``__x__``,
``*x*``, ``_x_``, ``~~x~~``; an underscore inside a word such as
``USER_COMPANY`` is not emphasis) is stripped and non-breaking and thin spaces
become plain spaces. Form checks read the answer as given, stripped of
surrounding whitespace (NARRATION also of surrounding quotes).

**Language.** ``expect_lang`` per case (``None``: no bar). The method is
``text_language`` of ``tests/measurement/capture_support.py``, the one the
case sets were written against: lower-case, split into words on anything
that is not a letter, count the words in a fixed Italian and a fixed English
function-word list, the strictly larger count wins; a tie is undecided and
fails, except a text in which neither list has a single hit: nothing
reads its language, so it is skipped and fails neither the bar nor the
label (audit B1). An answer of fewer than ``MIN_LANGUAGE_WORDS`` (eight) words is too
short to detect reliably and the bar is skipped (G3). The text is the free
text the README names: the ``title``, ``suggested_action`` and ``reason`` of
TASK_DETECTION and REANALYZE, CORRECTION_LEARNING's rule, otherwise the
answer's text. CORRECTION_LEARNING's README also makes the rule's language
part of its label (``text_language`` on the rule, no length skip).
"""

from __future__ import annotations

import functools
import importlib.util
import json
import re
from typing import Any

import measurement_common as common

MIN_LANGUAGE_WORDS = 8
TASK_ROLES = ("TASK_DETECTION", "REANALYZE", "DEDUP")
# Decision roles whose answer is the input of the one tool their request offers.
TOOL_ANSWER_ROLES = TASK_ROLES + ("REPLY_NEED", "CORRECTION_LEARNING", "SYNC_ANALYSIS")
QUOTES = "\"'\u201c\u201d\u2018\u2019\u00ab\u00bb"
SPACES = dict.fromkeys(
    map(ord, "\u00a0\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f"), " "
)
EMPHASIS = (
    re.compile(r"\*\*(.+?)\*\*", re.S),
    re.compile(r"__(.+?)__", re.S),
    re.compile(r"~~(.+?)~~", re.S),
    re.compile(r"(?<![\w*])\*(?![\s*])(.+?)(?<![\s*])\*(?![\w*])", re.S),
    re.compile(r"(?<![\w_])_(?![\s_])(.+?)(?<![\s_])_(?![\w_])", re.S),
)
WORD = re.compile(r"[^\W\d_]+")


def normalize(text: str) -> str:
    """G3: emphasis markers stripped, non-breaking and thin spaces made plain."""
    text = (text or "").translate(SPACES)
    for pattern in EMPHASIS:
        text = pattern.sub(r"\1", text)
    return text


def normalized(value: Any) -> Any:
    """``normalize`` on every string of a tool input."""
    if isinstance(value, str):
        return normalize(value)
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalized(item) for item in value]
    return value


@functools.cache
def judge():
    common.importable()
    from tests.measurement import conversation_judge

    return conversation_judge


@functools.cache
def detector():
    common.importable()
    from tests.measurement.capture_support import text_language

    return text_language


@functools.cache
def score_module(role: str):
    path = common.FIXTURES / role / "score.py"
    spec = importlib.util.spec_from_file_location(f"measurement_score_{role.lower()}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def language_bar(text: str, expect: str | None) -> dict:
    """``{"ok", "detected", "words"}``; ``ok`` None when no bar applies or the text is short."""
    if expect is None:
        return {"ok": None, "detected": None, "words": None}
    words = len(WORD.findall((text or "").lower()))
    if words < MIN_LANGUAGE_WORDS:
        return {"ok": None, "detected": None, "words": words}
    detected = detector()(normalize(text))
    if detected is None and no_hits(text):  # unreadable, not wrong (audit B1)
        return {"ok": None, "detected": None, "words": words}
    return {"ok": detected == expect, "detected": detected, "words": words}


def no_hits(text: str) -> bool:
    """Whether neither function-word list has a hit in ``text`` (its language unreadable)."""
    from tests.measurement.capture_support import _FUNCTION_WORDS

    words = re.findall(r"[^\W\d_]+", normalize(text or "").lower())
    return not any(word in vocab for word in words for vocab in _FUNCTION_WORDS.values())


# ─── tool inputs ──────────────────────────────────────────────────────


def _is(value: Any, kind: str) -> bool:
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    types = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}
    return isinstance(value, types.get(kind, object))


def schema_errors(schema: Any, value: Any, path: str = "input") -> list[str]:
    """Where ``value`` breaks ``schema`` (the JSON Schema subset the module docstring names)."""
    if not isinstance(schema, dict):
        return []
    for key in ("anyOf", "oneOf"):
        if isinstance(schema.get(key), list) and schema[key]:
            if not any(not schema_errors(option, value, path) for option in schema[key]):
                return [f"{path}: matches no {key} branch"]
    kind = schema.get("type")
    kinds = kind if isinstance(kind, list) else [kind] if kind else []
    if kinds and not any(_is(value, k) for k in kinds):
        return [f"{path}: not {kind}"]
    errors = []
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in the enum")
    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        errors += [
            f"{path}.{key}: missing" for key in schema.get("required") or [] if key not in value
        ]
        for key, sub in properties.items():
            if key in value:
                errors += schema_errors(sub, value[key], f"{path}.{key}")
        if schema.get("additionalProperties") is False:
            errors += [f"{path}.{key}: not allowed" for key in value if key not in properties]
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for n, item in enumerate(value):
            errors += schema_errors(schema["items"], item, f"{path}[{n}]")
    return errors


def tool_schemas(request: dict) -> dict:
    return {tool.get("name"): tool.get("input_schema") for tool in request.get("tools") or []}


def answer_tool(role: str, request: dict) -> str | None:
    """The one tool a decision role answers through: the one its request offers."""
    if role not in TOOL_ANSWER_ROLES:
        return None
    names = list(tool_schemas(request))
    return names[0] if len(names) == 1 else None


def tool_input(answer: dict, tool: str | None) -> Any:
    """The input of the first call to ``tool``, or None when it was not called."""
    for call in answer.get("calls") or []:
        if call.get("name") == tool:
            return call.get("input")
    return None


# ─── label rules ──────────────────────────────────────────────────────


def _result(match: bool, outcome: str, critical_on: list, failures: list | None = None) -> dict:
    return {
        "label_match": match,
        "outcome": outcome,
        "critical": (not match) and outcome in critical_on,
        "failures": failures or [],
    }


def _task_role(role: str, case: dict, answer: dict, request: dict) -> dict:
    scored = score_module(role).score_answer(case, tool_input(answer, answer_tool(role, request)))
    return {
        "label_match": scored["passed"],
        "outcome": scored["outcome"],
        "critical": scored["critical"],
        "failures": [],
    }


def _reply_need(case: dict, answer: dict, request: dict) -> dict:
    raw = tool_input(answer, answer_tool("REPLY_NEED", request))
    verdicts = raw.get("verdicts") if isinstance(raw, dict) else None
    outcome = "invalid"
    # As `reply_need.adjudicate` reads it: the first well-formed verdict for index 0.
    for item in verdicts if isinstance(verdicts, list) else []:
        if (
            isinstance(item, dict)
            and isinstance(item.get("index"), int)
            and isinstance(item.get("needs_reply"), bool)
            and item["index"] == 0
        ):
            outcome = "needs_reply" if item["needs_reply"] else "no_reply"
            break
    wanted = "needs_reply" if case["label"]["needs_reply"] else "no_reply"
    return _result(outcome == wanted, outcome, case["critical_on"])


def intent_class(text: str) -> str:
    """The skill the router would read from ``text``, or ``invalid`` (its own parse)."""
    fence = "`" * 3
    try:
        if fence + "json" in text:
            text = text.split(fence + "json")[1].split(fence)[0].strip()
        elif fence in text:
            text = text.split(fence)[1].split(fence)[0].strip()
        parsed = json.loads(text)
    except (ValueError, IndexError):
        return "invalid"
    skill = parsed.get("primary_skill") if isinstance(parsed, dict) else None
    return skill if isinstance(skill, str) and skill else "invalid"


def _intent(case: dict, answer: dict, request: dict) -> dict:
    outcome = intent_class(answer.get("text") or "")
    return _result(outcome == case["label"]["primary_skill"], outcome, case["critical_on"])


def _groups_met(groups: list, text: str, *, fold: bool) -> bool:
    text = text.lower() if fold else text
    return all(any((alt.lower() if fold else alt) in text for alt in group) for group in groups)


def _correction(case: dict, answer: dict, request: dict) -> dict:
    label, judge_kind = case["label"], case["input"]["judge"]
    raw = tool_input(answer, answer_tool("CORRECTION_LEARNING", request))
    if not isinstance(raw, dict):
        return _result(False, "invalid", case["critical_on"])
    if judge_kind == "rule":
        rule = normalize(str(raw.get("rule") or "").strip())
        records = bool(raw.get("is_durable_rule")) and bool(rule)
        if not label["is_durable_rule"]:
            outcome = "record" if records else "no_record"
            return _result(outcome == "no_record", outcome, case["critical_on"])
        if not records:
            return _result(False, "no_record", case["critical_on"])
        language = detector()(rule)
        match = _groups_met(label.get("rule_must_contain", []), rule, fold=True) and (
            language == case["expect_lang"] or (language is None and no_hits(rule))
        )
        return _result(match, "record", case["critical_on"])
    fields = {
        name: normalize(str(raw.get(name) or "").strip()) for name in ("category", "key", "value")
    }
    records = bool(raw.get("is_fact_change")) and all(fields.values())
    if not label["is_fact_change"]:
        outcome = "record" if records else "no_record"
        return _result(outcome == "no_record", outcome, case["critical_on"])
    if not records:
        return _result(False, "no_record", case["critical_on"])
    value, wanted = fields["value"], label.get("value_must_contain", [])
    forbidden = [
        spelling for spelling in label.get("value_must_not_contain", []) if spelling in value
    ]
    alternatives = [alt for group in wanted for alt in group]
    if forbidden and not any(alt in value for alt in alternatives):
        return _result(False, "old_value", case["critical_on"])
    match = (
        _groups_met(wanted, value, fold=False)
        and not forbidden
        and fields["category"].lower() == label["category"].strip().lower()
    )
    return _result(match, "record", case["critical_on"])


def _sync(case: dict, answer: dict, request: dict) -> dict:
    raw = tool_input(answer, answer_tool("SYNC_ANALYSIS", request))
    if not isinstance(raw, dict):
        return _result(False, "invalid", case["critical_on"])
    action = raw.get("expected_action")
    outcome = {None: "none", "answer": "answer", "reminder": "reminder"}.get(action, "other")
    label = case["label"]
    if label["needs_action"]:
        named = label.get("expected_action")
        right = outcome == named if named else outcome in ("answer", "reminder")
    else:
        right = outcome == "none"
    match = right and raw.get("open") is label["needs_action"]
    return _result(match, outcome, case["critical_on"])


def _conversation(role: str, case: dict, answer: dict, document: dict) -> dict:
    text = normalize(answer.get("text") or "")
    if role in common.AGENT_ROLES:
        turn = {
            "first": normalized(answer.get("first") or []),
            "later": normalized(answer.get("later") or []),
            "text": text,
        }
        found = judge().failures(case, turn, document.get("write_tools", []))
        if case["label"].get("answer") is not None and not text.strip():
            found.append("answer_empty")
    else:
        found = judge().failures(case, {"text": _as_given(role, answer)[1]})
    return {
        "label_match": not found,
        "outcome": "pass" if not found else ",".join(found),
        "critical": judge().is_critical(case, found),
        "failures": found,
    }


CLASS_RULES = {
    "REPLY_NEED": _reply_need,
    "INTENT": _intent,
    "CORRECTION_LEARNING": _correction,
    "SYNC_ANALYSIS": _sync,
}


def label(role: str, case: dict, answer: dict, request: dict, document: dict) -> dict:
    if role in TASK_ROLES:
        return _task_role(role, case, answer, request)
    if role in CLASS_RULES:
        return CLASS_RULES[role](case, answer, request)
    return _conversation(role, case, answer, document)


# ─── mechanical bars ──────────────────────────────────────────────────


def _as_given(role: str, answer: dict) -> tuple[str, str]:
    """The answer stripped as the README reads it, and its G3-normalised form."""
    text = (answer.get("text") or "").strip()
    if role == "NARRATION":
        text = text.strip(QUOTES).strip()
    return text, normalize(text)


def free_text(role: str, case: dict, answer: dict, request: dict) -> str:
    """The free text whose language ``expect_lang`` governs (module docstring)."""
    if role in ("TASK_DETECTION", "REANALYZE"):
        raw = tool_input(answer, answer_tool(role, request))
        fields = score_module(role).FREE_TEXT
        return " ".join(str(raw.get(f)) for f in fields if isinstance(raw, dict) and raw.get(f))
    if role == "CORRECTION_LEARNING":
        raw = tool_input(answer, answer_tool(role, request))
        return str(raw.get("rule") or "") if isinstance(raw, dict) else ""
    return answer.get("text") or ""


def _form(label_: dict, text: str, stop_reason: str | None) -> dict:
    bars: dict[str, bool] = {}
    if "max_chars" in label_:
        bars["max_chars"] = len(text) <= label_["max_chars"]
    if "min_chars" in label_:
        bars["min_chars"] = len(text) >= label_["min_chars"]
    if label_.get("single_line"):
        bars["single_line"] = "\n" not in text
    if label_.get("starts_with_any"):
        bars["starts_with_any"] = any(
            text.lower().startswith(prefix.lower()) for prefix in label_["starts_with_any"]
        )
    if label_.get("not_equal"):
        bars["not_equal"] = all(
            text.lower() != other.strip().lower() for other in label_["not_equal"]
        )
    if label_.get("no_headings"):
        bars["no_headings"] = not any(line.lstrip().startswith("#") for line in text.splitlines())
    if label_.get("complete"):
        bars["complete"] = stop_reason != "max_tokens"
    return bars


def bars(role: str, case: dict, answer: dict, request: dict) -> tuple[dict, dict]:
    """The mechanical bars (``None`` where one does not apply) and the language reading."""
    schemas, calls = tool_schemas(request), answer.get("calls") or []
    tool = answer_tool(role, request)
    out: dict[str, Any] = {"tool_called": None, "valid_input": None, "non_empty": None}
    if tool is not None:
        given = tool_input(answer, tool)
        out["tool_called"] = given is not None
        out["non_empty"] = isinstance(given, dict) and bool(given)
    elif role in common.AGENT_ROLES:
        out["non_empty"] = bool(calls) or bool((answer.get("text") or "").strip())
    else:
        out["non_empty"] = bool(_as_given(role, answer)[0])
    if calls and schemas:
        out["valid_input"] = all(
            call.get("name") in schemas
            and isinstance(call.get("input"), dict)
            and not schema_errors(schemas[call["name"]], call["input"])
            for call in calls
        )
    if role in common.SMOKE_ROLES:
        out.update(_form(case["label"], _as_given(role, answer)[0], answer.get("stop_reason")))
    language = language_bar(free_text(role, case, answer, request), case.get("expect_lang"))
    out["language"] = language["ok"]
    return out, language


def score(role: str, case: dict, answer: dict, request: dict, document: dict) -> dict:
    """Every reading of one answer: label, critical, bars (see the module docstring)."""
    result = label(role, case, answer, request, document)
    found, language = bars(role, case, answer, request)
    result.update(
        bars=found,
        bars_ok=all(value is not False for value in found.values()),
        language=language,
    )
    return result
