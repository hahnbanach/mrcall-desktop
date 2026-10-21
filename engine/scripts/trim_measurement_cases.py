#!/usr/bin/env python3
"""Trim a role's measured cases to N and keep the rest in reserve (milestone 10, plan S4, IR2).

IR2's spend rule: when the expected spend of the one-off measurement is over
USD 16 (the cap less 20 %), the case counts are reduced before any paid call,
never below twelve decisions per decision role and five scenarios for CHAT and
TASK_SOLVE (``MINIMUM``). A trim is persistent: the cases not kept move from
``<ROLE>/cases.json`` to ``<ROLE>/reserve.json`` and ``requests.json`` is
captured again from the kept set, so its ``case_set_sha256`` is the kept
set's and the one-off run and the daily job measure the same cases. The
reserve stays authored and reviewed: the case files' own tests read both
files (``tests/measurement/case_sets.py``).

    python scripts/trim_measurement_cases.py --role REPLY_NEED --keep 14 --plan --arms ARMS.json
    python scripts/trim_measurement_cases.py --role REPLY_NEED --keep 14
    python scripts/trim_measurement_cases.py --role REPLY_NEED --restore
    python scripts/trim_measurement_cases.py --role CHAT --keep-ids chat-01,chat-02,... \
        --chosen-by "IR2 round 1" --why "..."

**The selection** depends on the authored cases and N alone: a second trim
starts again from every authored case, and the same inputs keep the same
cases.

1. Every case whose ``critical_on`` is non-empty.
2. For each value of the role's decision field (``label_value``, in the order
   the values first appear), cases until two of that value are kept, or every
   case of a value that has fewer than two.
3. The rest, one at a time, until N.

Every pick after step 1 takes, among its candidates, a case of the input
language (``lang``) with fewer cases kept so far, so that the two languages
end as near equal as the counts allow, and in that language the
lowest-numbered id. On a tie it takes the lowest-numbered id of either
language. Among the rest, the highest-numbered ids are therefore dropped first.

The decision field (``label_value``) is the label class that the case files'
own balance tests count. CHAT and TASK_SOLVE are scenarios (a first call,
forbidden calls, an answer) with no single decision field.

| Role | Decision field |
|---|---|
| TASK_DETECTION | ``task_action`` |
| REANALYZE | ``action`` |
| DEDUP | duplicates or distinct, per call site: ``is_duplicate_group`` (``dedup.f8``), ``clusters`` (``dedup.f9``) |
| REPLY_NEED | ``needs_reply`` |
| INTENT | ``primary_skill`` |
| CORRECTION_LEARNING | the judge and its must-record flag |
| SYNC_ANALYSIS | ``expected_action`` of a thread that needs action, else none |

**Refused** (exit 1, nothing written):

- a role the plan sets no minimum for (the smokes; the corpus roles have no
  case file here);
- N below the role's minimum;
- N below its critical cases;
- N below what steps 1 and 2 must keep (the message gives that floor);
- N above its authored cases.

**Files.** ``cases.json`` keeps its own text: the kept cases as written, in
order, among the document's other keys. ``reserve.json`` holds the others
verbatim with the authored order (``case_sets.py``). ``--restore`` puts every
case back and removes ``reserve.json``, as does N equal to the authored count,
and the files are then byte for byte what they were. If ``requests.json``
cannot be captured, the three files are put back as they were.

**A reviewed exception** (``--keep-ids``) names the exact kept set when a
review finds the rule's choice drops a case the role needs; ``--chosen-by``
and ``--why`` are required. It is refused when it drops a critical case or
goes below the floors (the plan's minimum, two of each label value), and
for ids that are not the role's authored cases. ``reserve.json`` records it
(``exception``: who chose it, why, and what the rule would keep at that
size), and while it stands a ``--keep N`` is refused rather than silently
undoing it: ``--restore`` first, or another ``--keep-ids``.

``--plan`` writes nothing. It prints the cases that would move and, with
``--arms``, the projection's delta for every arm of the role: the maximum and
the expected spend of ``measurement_projection`` over the cases measured now
and over the kept ones. The authored cases are captured afresh, so a case
coming back from the reserve is priced too.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_measurement_requests as builder  # noqa: E402
import measurement_common as common  # noqa: E402

common.importable()
from tests.measurement.case_sets import RESERVE, authored_document, load_reserve  # noqa: E402

logger = logging.getLogger("trim_measurement_cases")
MINIMUM = {**{role: 12 for role in common.DECISION_ROLES}, "CHAT": 5, "TASK_SOLVE": 5}
PER_VALUE = 2
RULE = "trim_measurement_cases.py: authored and reviewed, not measured; --restore puts them back"
RESERVE_LEAD, RESERVE_END = "\n    ", "\n  ]\n}\n"
DECODER = json.JSONDecoder()


class Refused(RuntimeError):
    """The trim cannot keep N cases under the rule (module docstring)."""


def label_value(role: str, case: dict) -> object:
    """The value of the role's decision field in ``case``; None for a role without one."""
    label = case["label"]
    if role == "TASK_DETECTION":
        return label["task_action"]
    if role == "REANALYZE":
        return label["action"]
    if role == "DEDUP":
        site = case["call_site"]
        group = label["is_duplicate_group"] if site == "dedup.f8" else bool(label["clusters"])
        return f"{site} {'duplicates' if group else 'distinct'}"
    if role == "REPLY_NEED":
        return label["needs_reply"]
    if role == "INTENT":
        return label["primary_skill"]
    if role == "CORRECTION_LEARNING":
        flag = label.get("is_durable_rule", label.get("is_fact_change"))
        return f"{case['input']['judge']} {flag}"
    if role == "SYNC_ANALYSIS":
        return label.get("expected_action", "unlabelled") if label["needs_action"] else "none"
    return None


def number(case: dict, position: int) -> tuple[int, int]:
    """The id's own number (``reply_need-07`` is 7), then the authored position."""
    found = re.search(r"(\d+)$", case["id"])
    return (int(found.group(1)) if found else position, position)


def floor(role: str, cases: list[dict]) -> int:
    """How many cases steps 1 and 2 keep: the critical ones and two of each value."""
    critical = [case for case in cases if case["critical_on"]]
    total = Counter(label_value(role, case) for case in cases)
    held = Counter(label_value(role, case) for case in critical)
    missing = (max(0, min(PER_VALUE, n) - held[v]) for v, n in total.items() if v is not None)
    return len(critical) + sum(missing)


def select(role: str, cases: list[dict], keep: int) -> list[str]:
    """The ids the rule keeps of ``cases`` (authored order), or ``Refused``."""
    if role not in MINIMUM:
        raise Refused(f"{role}: the plan sets it no minimum; only {', '.join(MINIMUM)} are trimmed")
    critical = [case for case in cases if case["critical_on"]]
    if keep > len(cases):
        raise Refused(f"{role}: {keep} is more than its {len(cases)} authored cases")
    if keep < MINIMUM[role]:
        raise Refused(f"{role}: {keep} is below the plan's minimum of {MINIMUM[role]}")
    if keep < len(critical):
        raise Refused(f"{role}: {keep} is below its {len(critical)} critical cases")
    need = floor(role, cases)
    if keep < need:
        raise Refused(
            f"{role}: {keep} is below the {need} the rule must keep "
            f"({len(critical)} critical cases and two of each label value)"
        )
    position = {case["id"]: n for n, case in enumerate(cases)}
    kept, rest = list(critical), [case for case in cases if not case["critical_on"]]

    def take(pool: list[dict]) -> None:
        held = Counter(case["lang"] for case in kept)
        chosen = min(pool, key=lambda c: (held[c["lang"]], number(c, position[c["id"]])))
        kept.append(chosen)
        rest.remove(chosen)

    for value in dict.fromkeys(label_value(role, case) for case in cases):
        while value is not None and sum(label_value(role, c) == value for c in kept) < PER_VALUE:
            pool = [case for case in rest if label_value(role, case) == value]
            if not pool:
                break
            take(pool)
    while len(kept) < keep:
        take(rest)
    chosen = {case["id"] for case in kept}
    return [case["id"] for case in cases if case["id"] in chosen]


def _skip(text: str, i: int) -> int:
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    return i


def spans(text: str) -> tuple[str, list[tuple[str, str]], list[str], str]:
    """``(prefix, [(id, the case's text)], separators, suffix)`` of the ``cases`` array."""
    i = _skip(text, 0)
    if text[i : i + 1] != "{":
        raise Refused("a case file is not a JSON object")
    i = _skip(text, i + 1)
    while text[i : i + 1] == '"':
        key, i = DECODER.raw_decode(text, i)
        i = _skip(text, i)
        if text[i : i + 1] != ":":
            raise Refused("a case file is not a JSON object")
        i = _skip(text, i + 1)
        if key != "cases":
            _value, i = DECODER.raw_decode(text, i)
            i = _skip(text, i)
            i = _skip(text, i + 1) if text[i : i + 1] == "," else i
            continue
        if text[i : i + 1] != "[":
            raise Refused("a case file whose cases are not an array")
        items, j = [], _skip(text, i + 1)
        prefix = text[:j]
        while text[j] != "]":
            case, end = DECODER.raw_decode(text, j)
            items.append((case["id"], j, end))
            j = _skip(text, end)
            j = _skip(text, j + 1) if text[j] == "," else j
        gaps = [text[a[2] : b[1]] for a, b in zip(items, items[1:])]
        return prefix, [(cid, text[s:e]) for cid, s, e in items], gaps, text[items[-1][2] :]
    raise Refused("a case file without a cases array")


def separator_of(text: str) -> tuple[str, dict, str, str]:
    """``(prefix, {id: text}, separator, suffix)`` of a cases.json written one way throughout."""
    prefix, items, gaps, suffix = spans(text)
    if len(set(gaps)) != 1:
        raise Refused("cases.json separates its cases in more than one way; trim it by hand")
    return prefix, dict(items), gaps[0], suffix


def reserve_text(
    role: str,
    keep: int,
    order: list[str],
    texts: list[str],
    separator: str,
    exception: dict | None = None,
) -> str:
    """``reserve.json`` (``case_sets.py``): the reserve cases as written, the authored order,
    and the reviewed exception that chose the kept set, if one did."""
    head = {"schema": 1, "role": role, "rule": RULE, "kept": keep, "order": order}
    if exception is not None:
        head["exception"] = exception
    lines = "".join(f'  "{k}": {json.dumps(v, ensure_ascii=False)},\n' for k, v in head.items())
    return "{\n" + lines + '  "cases": [' + RESERVE_LEAD + separator.join(texts) + RESERVE_END


def select_ids(role: str, cases: list[dict], ids: list[str]) -> list[str]:
    """The exact kept set ``ids`` (authored order), or ``Refused``: authored cases only, every
    critical case kept, the plan's minimum and two of each label value (the floors)."""
    if role not in MINIMUM:
        raise Refused(f"{role}: the plan sets it no minimum; only {', '.join(MINIMUM)} are trimmed")
    known, wanted = {case["id"] for case in cases}, set(ids)
    if len(wanted) != len(ids) or wanted - known:
        raise Refused(f"{role}: not each an authored case once: {sorted(wanted - known) or ids}")
    dropped = [c["id"] for c in cases if c["critical_on"] and c["id"] not in wanted]
    if dropped:
        raise Refused(f"{role}: the kept set drops critical case(s) {', '.join(dropped)}")
    if len(wanted) < MINIMUM[role]:
        raise Refused(f"{role}: {len(wanted)} is below the plan's minimum of {MINIMUM[role]}")
    total = Counter(label_value(role, case) for case in cases)
    held = Counter(label_value(role, c) for c in cases if c["id"] in wanted)
    for value, n in total.items():
        if value is not None and held[value] < min(PER_VALUE, n):
            raise Refused(
                f"{role}: the kept set holds {held[value]} of {value}; the rule keeps two"
            )
    return [case["id"] for case in cases if case["id"] in wanted]


def recorded_exception(role: str) -> dict | None:
    """The reviewed exception the role's ``reserve.json`` records, if any."""
    reserve = load_reserve(common.FIXTURES / role)
    return (reserve or {}).get("exception")


def plan_of(
    role: str, keep: int | None, ids: list[str] | None = None, exception: dict | None = None
) -> dict:
    """The selection for ``keep`` (every authored case when None), or the reviewed exception
    ``ids`` (``exception``: who chose it and why), and what it moves."""
    if role not in MINIMUM:
        raise Refused(f"{role}: the plan sets it no minimum; only {', '.join(MINIMUM)} are trimmed")
    authored = authored_document(common.FIXTURES / role)
    cases = authored["cases"]
    standing = recorded_exception(role)
    if ids is None and keep is not None and standing is not None:
        raise Refused(
            f"{role}: its kept set is a reviewed exception ({standing.get('chosen_by')}:"
            f" {standing.get('why')}); --restore first, or pass another --keep-ids"
        )
    if ids is not None:
        kept = select_ids(role, cases, ids)
        try:
            rule = select(role, cases, len(kept))
        except Refused:
            rule = None
        exception = {**(exception or {}), "rule_would_keep": rule}
    else:
        kept, exception = select(role, cases, len(cases) if keep is None else keep), None
    measured = [case["id"] for case in common.load_document(role)["cases"]]
    plan = {"role": role, "authored": authored, "kept": kept, "measured": measured}
    return {**plan, "exception": exception, "standing": standing}


def apply(plan: dict) -> dict:
    """Write cases.json, reserve.json and requests.json for ``plan``; returns requests.json."""
    role = plan["role"]
    role_dir = common.FIXTURES / role
    paths = (role_dir / "cases.json", role_dir / RESERVE, common.requests_path(role))
    before = {path: path.read_bytes() if path.is_file() else None for path in paths}
    prefix, texts, separator, suffix = separator_of(before[paths[0]].decode("utf-8"))
    if before[paths[1]] is not None:
        texts.update(spans(before[paths[1]].decode("utf-8"))[1])
    order = [case["id"] for case in plan["authored"]["cases"]]
    kept = set(plan["kept"])
    moved = [texts[case_id] for case_id in order if case_id not in kept]
    cases_text = prefix + separator.join(texts[i] for i in order if i in kept) + suffix
    try:
        paths[0].write_bytes(cases_text.encode("utf-8"))
        if moved:
            exception = plan.get("exception")
            reserve = reserve_text(role, len(kept), order, moved, separator, exception)
            paths[1].write_bytes(reserve.encode("utf-8"))
        else:
            paths[1].unlink(missing_ok=True)
        fresh = builder.build(role)
        paths[2].write_bytes(common.dump(fresh).encode("utf-8"))
    except BaseException:
        for path, data in before.items():
            if data is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(data)
        raise
    logger.debug(f"[trim] {role}: kept {len(kept)}, reserve {len(moved)}")
    return fresh


def describe(plan: dict) -> list[str]:
    """What ``plan`` keeps and moves, one line each."""
    role, cases = plan["role"], plan["authored"]["cases"]
    by_id = {case["id"]: case for case in cases}
    kept = [by_id[case_id] for case_id in plan["kept"]]
    langs = Counter(case["lang"] for case in kept)
    lines = [
        f"{role}: keep {len(kept)} of {len(cases)} authored (measured now {len(plan['measured'])}):"
        f" critical {sum(bool(case['critical_on']) for case in kept)},"
        f" {', '.join(f'{lang} {n}' for lang, n in sorted(langs.items()))}"
    ]
    values = Counter(str(label_value(role, case)) for case in kept)
    if label_value(role, cases[0]) is not None:
        lines.append("  label values kept: " + ", ".join(f"{v} {n}" for v, n in values.items()))
    out = [case_id for case_id in plan["measured"] if case_id not in plan["kept"]]
    back = [case_id for case_id in plan["kept"] if case_id not in plan["measured"]]
    for label, ids in (("to the reserve", out), ("back from the reserve", back)):
        named = [f"{i} ({by_id[i]['lang']}, {label_value(role, by_id[i])})" for i in ids]
        lines.append(f"  {label} ({len(ids)}): {', '.join(named) or 'none'}")
    exception = plan.get("exception")
    if exception is not None:
        rule = ", ".join(exception["rule_would_keep"] or ["(none at this size)"])
        lines.append(
            f"  a reviewed exception, chosen by {exception['chosen_by']}: {exception['why']}"
        )
        lines.append(f"  the rule would keep: {rule}")
    return lines


def projection_delta(plan: dict, arms: list[dict]) -> list[str]:
    """Per arm, the projection over the cases measured now and over the kept ones."""
    import measurement_projection as projection
    from measurement_runtime import RoleRun

    from zylch.llm.budget_pricing import BudgetError
    from zylch.llm.roles import catalogue

    role, document = plan["role"], plan["authored"]
    run = RoleRun(role, document, {"requests": common.capture(role, document)}, arms)
    now, kept = set(plan["measured"]), set(plan["kept"])
    lines = [f"  projection, USD now -> kept (snapshot {catalogue.layers()[0]['version']}):"]
    total = [Decimal(0)] * 4
    for arm in arms:
        client = projection.client_for(arm["id"])
        try:
            cells = {
                case["id"]: projection.harness_cell(run, arm["id"], case, client)
                for case in document["cases"]
            }
        except BudgetError as refused:
            lines.append(f"    {arm['id']}: not priced ({refused})")
            continue
        sums = [sum((cells[i][k] for i in ids), Decimal(0)) for k in (0, 1) for ids in (now, kept)]
        total = [a + b for a, b in zip(total, sums)]
        name = f"{arm['id']} (reference)" if arm["reference"] else arm["id"]
        lines.append(f"    {name:40} {_pair('max', *sums[:2])}  {_pair('expected', *sums[2:])}")
    lines.append(f"    {'the role':40} {_pair('max', *total[:2])}  {_pair('expected', *total[2:])}")
    return lines


def _pair(label: str, before: Decimal, after: Decimal) -> str:
    return f"{label} {before:8.4f} -> {after:8.4f} ({after - before:+.4f})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trim a role's measured cases; keep the rest.")
    parser.add_argument("--role", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--keep", type=int, help="the number of cases to measure")
    action.add_argument("--restore", action="store_true", help="measure every authored case")
    action.add_argument(
        "--keep-ids", help="a reviewed exception: the exact kept ids, comma-separated"
    )
    parser.add_argument("--chosen-by", help="with --keep-ids: who chose the exception")
    parser.add_argument("--why", help="with --keep-ids: why the rule's choice would not do")
    parser.add_argument("--plan", action="store_true", help="print what would move; write nothing")
    parser.add_argument("--arms", type=Path, help="with --plan: the bootstrap arms, for the delta")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    ids, exception = None, None
    if args.keep_ids is not None:
        if not (args.chosen_by or "").strip() or not (args.why or "").strip():
            parser.error("--keep-ids is a reviewed exception: --chosen-by and --why are required")
        ids = [part.strip() for part in args.keep_ids.split(",") if part.strip()]
        exception = {"chosen_by": args.chosen_by.strip(), "why": args.why.strip()}
    try:
        keep = None if args.restore or ids is not None else args.keep
        plan = plan_of(args.role, keep, ids, exception)
    except Refused as refused:
        print(f"refused: {refused}", file=sys.stderr)
        return 1
    print("\n".join(describe(plan)))
    if args.plan:
        if args.arms:
            print("\n".join(projection_delta(plan, common.load_arms(args.arms)[args.role])))
        return 0
    trimmed = len(plan["kept"]) < len(plan["authored"]["cases"])
    reserve = (common.FIXTURES / args.role / RESERVE).is_file()
    if (
        plan["kept"] == plan["measured"]
        and reserve == trimmed
        and (plan["exception"] == plan["standing"])
    ):
        print("nothing to move")
        return 0
    fresh = apply(plan)
    reserve_note = f"wrote {RESERVE}" if trimmed else f"removed {RESERVE}"
    print(
        f"wrote cases.json ({len(plan['kept'])} cases) and requests.json, {reserve_note}:"
        f" case set {fresh['case_set_sha256']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
