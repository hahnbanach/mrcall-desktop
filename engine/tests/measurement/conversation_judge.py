"""The labels of the agent and smoke roles, read as code: what a turn failed, and what is critical.

The READMEs of CHAT, TASK_SOLVE, COMPACTION, NARRATION, WEB_SEARCH and TRAIN
define their labels; this module is the reference reading of the decision and
content checks, so the rule a measurement applies and the rule the case sets
were written against cannot drift apart unseen. Language (``expect_lang``) and
form — the answer's length, a single line, the "Sto " opening, no headings, an
answer not cut at its token limit, not the fallback — are the measurement's
mechanical bars and are not read here.

A turn is what a model did with a case's captured request
(``conversation_capture.ReplayClient.turn``): ``first``, the tool calls of its
answer to that request; ``later``, the calls of every answer after it, when
the measurement continued the turn; ``text``, the text to check, when it is
scored. A smoke role's turn is its ``text`` alone.

The critical rule. A failure is critical only in a case marked ``critical``,
and only when its kind is in the case's ``critical_on``:

- ``never_call`` — a tool the label forbids was called, in any answer;
- ``unmatched_write`` — the answer to the captured request called a write or
  send tool (the document's ``write_tools``) that no ``first_call`` spec names;
- ``wrong_arguments`` — that answer called a tool a spec names with arguments
  no spec for that tool accepts, a call made next to a matching one included;
- ``contains`` / ``matches_none`` — a fact the answer must state is missing,
  or an invented one is there.

No call, a read-only call the label does not forbid, or a question asked
instead is an ordinary failure.

Text is read as given: normalising it first (Markdown emphasis stripped,
non-breaking and thin spaces made plain — label review G3) is the
measurement's step, and the labels' alternatives are written for that text.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Sequence

FAILURE_KINDS = (
    "first_call",
    "never_call",
    "unmatched_write",
    "wrong_arguments",
    "contains",
    "contains_none",
    "matches",
    "matches_none",
)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def contains(groups: Sequence[Sequence[str]], value: Any) -> bool:
    """Every group has one of its alternatives in ``value`` (case-insensitive substring)."""
    text = _text(value).lower()
    return all(any(alternative.lower() in text for alternative in group) for group in groups)


def holds(matcher: Dict[str, Any], value: Any) -> bool:
    """A ``first_call`` argument matcher against the argument's value."""
    if "contains" in matcher:
        return contains(matcher["contains"], value)
    if "equals" in matcher:
        return _text(value).strip().lower() == matcher["equals"].strip().lower()
    if "digits_contain" in matcher:
        return matcher["digits_contain"] in re.sub(r"\D", "", _text(value))
    raise ValueError(f"unknown argument matcher {sorted(matcher)}")


def matches_spec(spec: Dict[str, Any], call: Dict[str, Any]) -> bool:
    """The call is the spec's tool, and every argument the spec lists is there and holds."""
    arguments = call.get("input") or {}
    return call["name"] == spec["name"] and all(
        name in arguments and holds(matcher, arguments[name])
        for name, matcher in (spec.get("args") or {}).items()
    )


def text_failures(checks: Dict[str, Any], text: str) -> List[str]:
    """The text checks of an answer spec (or of a smoke role's label) ``text`` fails."""
    lowered = text.lower()
    found = []
    if checks.get("contains") and not contains(checks["contains"], text):
        found.append("contains")
    if any(phrase.lower() in lowered for phrase in checks.get("contains_none", [])):
        found.append("contains_none")
    if any(not re.search(rx, text, re.IGNORECASE) for rx in checks.get("matches", [])):
        found.append("matches")
    if any(re.search(rx, text, re.IGNORECASE) for rx in checks.get("matches_none", [])):
        found.append("matches_none")
    return found


def failures(
    case: Dict[str, Any], turn: Dict[str, Any], write_tools: Iterable[str] = ()
) -> List[str]:
    """The kinds of check ``turn`` fails, in :data:`FAILURE_KINDS` order."""
    label = case["label"]
    if "first_call" not in label:
        found = set(text_failures(label, turn.get("text", "")))
        return [kind for kind in FAILURE_KINDS if kind in found]
    first, later = turn.get("first", []), turn.get("later", [])
    specs = (label["first_call"] or {}).get("any_of", [])
    named = {spec["name"] for spec in specs}
    writes = set(write_tools)
    found = set()
    # The decision: a call some spec accepts, or — when the label expects no
    # tool (``first_call`` null) — no call at all.
    if specs:
        decided = any(matches_spec(spec, call) for spec in specs for call in first)
    else:
        decided = not first
    if not decided:
        found.add("first_call")
    if any(call["name"] in label.get("never_call", []) for call in [*first, *later]):
        found.add("never_call")
    for call in first:
        if call["name"] in named:
            if not any(matches_spec(spec, call) for spec in specs if spec["name"] == call["name"]):
                found.add("wrong_arguments")
        elif call["name"] in writes:
            found.add("unmatched_write")
    if label.get("answer") is not None and "text" in turn:
        found.update(text_failures(label["answer"], turn["text"]))
    return [kind for kind in FAILURE_KINDS if kind in found]


def is_critical(case: Dict[str, Any], found: Iterable[str]) -> bool:
    """Whether ``found`` holds a failure the case marks critical."""
    return bool(case["critical"]) and any(kind in case["critical_on"] for kind in found)
