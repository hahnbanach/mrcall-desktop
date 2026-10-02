"""The daily model-table job's records: the spend ledger, the working measurement, the report.

Pure: the job (`model_table_job.py`) reads and writes the files. Amounts are
USD as canonical decimal strings (`rm.snapshot.text`), never floats.

**`ledger.json`** (data branch, `v1/`) holds the job's paid calls by month
(UTC, `YYYY-MM`): `{"schema": 1, "months": {"2026-10": [run, ...]}}`, one row
per run that paid for anything: `run` (its id), `reserved_usd`, `opened_at`,
`spent_usd` and `settled_at` (null until settled) and `calls` (filled at
settlement: kind, model, role, why, bound, spend, outcome). A run pushes its
reservation before its first paid call and settles it after; a month's use
is what its runs spent, or reserved where a run never settled (it stopped
mid-way: its outcome is uncertain, so its whole reservation stays counted,
as the engine's own ledger keeps an uncertain hold).

**`measured.json`** (data branch) is the engine's `roles/measured.json` as
the job last used it: the measurement's file, with each result the job adds
stamped with its own `case_set_sha256`, `prompt_sha256` and `measured_at`
(the resolver ignores extra result fields), so a result stays keyed by
(model, role, case-set hash, prompt hash) after its role is re-measured
under new hashes. The job's thresholds are the measurement's: it adds
pass/fail results, it never re-derives a threshold.
"""

from __future__ import annotations

import copy
import json
import re
from decimal import Decimal, InvalidOperation

import resolve_models as rm

LEDGER_SCHEMA = 1
MONTH = re.compile(r"^[0-9]{4}-[0-9]{2}$")


def usd(amount: Decimal) -> str:
    """An amount as the records write it."""
    return rm.snapshot.text(amount)


def _amount(value: object, where: str) -> Decimal:
    try:
        amount = Decimal(value) if isinstance(value, str) else None
    except InvalidOperation:
        amount = None
    if amount is None or not amount.is_finite() or amount < 0:
        raise ValueError(f"ledger.json: {where} is not an amount in USD")
    return amount


def empty_ledger() -> dict:
    return {"schema": LEDGER_SCHEMA, "months": {}}


def check_ledger(doc: object) -> dict:
    """Return `doc` when it is a ledger the job reads, else raise ValueError:
    the job never overwrites a spend record it cannot read."""
    if not isinstance(doc, dict) or doc.get("schema") != LEDGER_SCHEMA:
        raise ValueError(f"ledger.json: not a schema {LEDGER_SCHEMA} ledger")
    months = doc.get("months")
    if not isinstance(months, dict):
        raise ValueError("ledger.json: months must be an object")
    for month, runs in months.items():
        if not MONTH.match(month) or not isinstance(runs, list):
            raise ValueError(f"ledger.json: months.{month} must be a list of runs")
        for row in runs:
            where = f"months.{month}"
            if not isinstance(row, dict) or not isinstance(row.get("run"), str):
                raise ValueError(f"ledger.json: {where} holds a row without a run id")
            _amount(row.get("reserved_usd"), f"{where} / {row['run']} reserved_usd")
            if row.get("spent_usd") is not None:
                _amount(row["spent_usd"], f"{where} / {row['run']} spent_usd")
    return doc


def month_used(ledger: dict, month: str, skip: str | None = None) -> Decimal:
    """What `month`'s runs spent, or reserved where one never settled,
    leaving out the run `skip`."""
    used = Decimal(0)
    for row in ledger["months"].get(month, []):
        if row["run"] != skip:
            used += Decimal(
                row["spent_usd"] if row["spent_usd"] is not None else row["reserved_usd"]
            )
    return used


def _row(ledger: dict, month: str, run: str) -> dict | None:
    return next((row for row in ledger["months"].get(month, []) if row["run"] == run), None)


def reserve(ledger: dict, month: str, run: str, amount: Decimal, at: str) -> dict:
    """A copy of `ledger` holding `run`'s reservation of `amount` (opened, or raised)."""
    out = copy.deepcopy(ledger)
    row = _row(out, month, run)
    if row is None:
        row = {"run": run, "opened_at": at, "spent_usd": None, "settled_at": None, "calls": []}
        out["months"].setdefault(month, []).append(row)
    row["reserved_usd"] = usd(amount)
    return out


def settle(ledger: dict, month: str, run: str, spent: Decimal, calls: list, at: str) -> dict:
    """A copy of `ledger` with `run` settled at `spent`, its calls recorded."""
    out = copy.deepcopy(ledger)
    row = _row(out, month, run)
    row.update(spent_usd=usd(spent), settled_at=at, calls=calls)
    return out


def dump(doc: dict) -> str:
    """The file layout of the job's own records: sorted keys, two-space indent."""
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _key(body: dict) -> tuple[str, str]:
    return body["case_set_sha256"], body["prompt_sha256"]


def working_measured(published: dict | None, build: dict | None, hashes: dict) -> dict | None:
    """The measurement the run starts from: the published one (the job's
    latest), else the build copy; a role the build copy measured under the
    current hashes while the published one did not (a re-measurement since)
    is taken from the build copy."""
    base = copy.deepcopy(published if published is not None else build)
    if base is None or published is None or build is None:
        return base
    for role, body in build["roles"].items():
        want, held = hashes.get(role), base["roles"].get(role)
        if want is None or _key(body) != tuple(want):
            continue
        if held is None or _key(held) != tuple(want):
            base["roles"][role] = copy.deepcopy(body)
    return base


def record_result(measured: dict, role: str, model: str, result: dict, hashes, at: str) -> None:
    """Record `result` (`{pass, ...}`) for `model` in `role`, measured at `at`
    under `hashes` (None: the role's recorded ones). When the role's hashes
    move, every earlier result keeps its own first, so none reads as current."""
    body = measured["roles"][role]
    cs, ph = tuple(hashes) if hashes is not None else _key(body)
    if _key(body) != (cs, ph):
        for earlier in body["results"].values():
            earlier.setdefault("case_set_sha256", body["case_set_sha256"])
            earlier.setdefault("prompt_sha256", body["prompt_sha256"])
        body["case_set_sha256"], body["prompt_sha256"] = cs, ph
    stamp = {"case_set_sha256": cs, "prompt_sha256": ph, "measured_at": at}
    body["results"][model] = {**result, **stamp}


def _table(head: tuple, rows: list) -> list[str]:
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    return lines + ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]


def report(s: dict) -> str:
    """The run's markdown report from its summary `s` (built by the job)."""
    lines = [
        "# Model table: daily resolution",
        "",
        f"- Run `{s['run']}`: **{s['status']}** (exit {s['code']})",
        (
            f"- Catalogue read {s.get('read_at') or 'not read'}; "
            f"benchmarks as of {s.get('benchmarks_as_of') or 'an unrecorded date'}"
        ),
    ]
    spend = s.get("spend")
    if spend:
        lines.append(
            f"- Spend {spend['month']}: USD {spend['used_before']} used before this run, "
            f"USD {spend['reserved']} reserved and USD {spend['spent']} spent by it, "
            f"monthly cap USD {spend['cap']}"
        )
    for title, key in (("Problems (nothing published)", "problems"), ("Notes", "notes")):
        if s.get(key):
            lines += ["", f"## {title}", ""] + [f"- {line}" for line in s[key]]
    lines += ["", "## Decision record", ""]
    if s.get("decision") is None:
        lines.append("- not compared: the run stopped before a table could be published")
    else:
        lines += [f"- {line}" for line in s["decision"]] or ["- no pick or order changed"]
    snap = s.get("snapshot")
    if snap:
        lines += ["", "## Snapshot", "", f"- version {snap['old']} -> {snap['new']}"]
        lines.append(f"- catalogue entries: {snap['added']} added, {snap['removed']} removed")
        lines += [f"- price of ranked {m}: {old} -> {new}" for m, old, new in snap["prices"]]
        lines += [f"- metadata of ranked {m}: {', '.join(f)}" for m, f in snap["metadata"]]
    if s.get("calls"):
        lines += ["", "## Paid checks", ""]
        head = ("check", "why", "bound USD", "spent USD", "outcome")
        rows = [
            (c["check"], c["why"], c["bound_usd"], c["spent_usd"], c["outcome"]) for c in s["calls"]
        ]
        lines += _table(head, rows)
    if s.get("deferred"):
        lines += ["", "## Checks not made", ""]
        lines += [f"- {check}: {why}" for check, why in s["deferred"]]
    if s.get("resampled"):
        lines += ["", "## Monthly re-sampling", ""] + [f"- {c}" for c in s["resampled"]]
    lines += ["", "## Empty Anthropic rankings", ""]
    lines += [f"- {where}" for where in s.get("empty_anthropic", [])] or ["- none"]
    lines += ["", "## Unscored models (never ranked until scored)", ""]
    unscored = s.get("unscored") or {}
    lines += [f"- {model}: {why}" for model, why in unscored.items()] or ["- none"]
    return "\n".join(lines) + "\n"
