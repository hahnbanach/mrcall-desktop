#!/usr/bin/env python3
"""Run every arm on every case of each role and score the answers (milestone 10, plan S4b).

The arms are the measurement bootstrap (``resolve_models.py --bootstrap``,
saved to a file and passed as ``--arms``) plus the reference
(``requirements.json``: ``moonshotai/kimi-k3``), which runs first in every
role so a role cut short by the cap still has its yardstick. Each role's
cases are its ``requests.json`` (``build_measurement_requests.py``), checked
against today's case set and prompts before anything is sent.

**The transport is the engine's.** One disposable profile — a private
temporary directory whose ``.env`` (mode 600, deleted after) holds
``LLM_PROVIDER=openrouter``, the key from ``OPENROUTER_API_KEY`` (never from
argv, never printed) and a daily budget equal to the cap — and per cell (one
arm on one case) a client from ``make_llm_client(model=<arm>)``: the one
request shape, admission, the reservation ledger and the OpenRouter transport,
K3 through its adapter. The model is the arm's, never the case's: a captured
``model`` (``measurement/capture``, ``<role model>``) and any sampling field
are dropped, and the client shapes the request for the arm as production
does. A replay pins the client's datetime line to the case's ``capture_now``
(label review G5). The decision and smoke roles replay their captured request;
CHAT and TASK_SOLVE continue the turn through their harness's ``run_case``,
whose scripted tools answer every call.

**Spend** (``measurement_ledger.py``): before each dispatch the engine's own
reservation bound of the exact request is checked against ``--cap`` with
everything spent or uncertain, and written as an intent; the receipt settles
it after. No retry: a cell with an intent is never dispatched again, so an
interrupted run resumes with the same ``--out`` and skips it. Two transport
failures in a row skip the rest of that arm in that role.

**Results** (``<out>/results.jsonl``, one row per cell and repetition): the
answer's tool calls and text, usage, cost, latency, and the scoring of
``measurement_scoring.py`` (label match, critical, mechanical bars).
``--repeat-disagreements`` then runs a second repetition of every cell whose
label result differs from the reference's on the same case, and last (D7) the
reference's second repetition of every case.

    python scripts/measure_roles.py --arms ARMS.json --project            # free projection
    python scripts/measure_roles.py --arms ARMS.json --out DIR --dry-run  # scripted transport
    python scripts/measure_roles.py --arms ARMS.json --out DIR --cap 20   # paid

Exit codes: 0 done; 1 refused (stale requests, no key, corrupt ledger);
3 the cap stopped the run (what was measured is recorded).
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import measurement_common as common  # noqa: E402
import measurement_scoring as scoring  # noqa: E402
from measurement_ledger import CapExceeded, Ledger  # noqa: E402
from measurement_runtime import (  # noqa: E402
    DRY_KEY,
    KEY_ENV,
    Cell,
    Context,
    Results,
    RoleRun,
    answer_of,
    base_row,
    cell_client,
    clock_for,
    measurement_profile,
    price_refusal,
    replay_kwargs,
)

logger = logging.getLogger("measure_roles")
DEFAULT_CAP = Decimal("20")
FAILURES_BEFORE_SKIP = 2
EXIT_CAP = 3


def run_cell(ctx: Context, run: RoleRun, arm: dict, case: dict, repetition: int) -> dict:
    """One arm on one case: dispatch through the guard, then score; returns the result row."""
    from zylch.llm.usage import call_site

    cell = Cell(run.role, arm["id"], case["id"], repetition)
    entry = run.entry(case["id"])
    agent = run.role in common.AGENT_ROLES
    client, guard = cell_client(ctx, cell, other_profile=agent)
    started, answer, error = time.perf_counter(), None, None
    try:
        with call_site(f"measurement.{run.role.lower()}"):
            if agent:
                outcome = run.harness.run_case(case, client)
                turn = outcome["turn"]
                answer = {"calls": outcome["calls"], "text": turn["text"], "stop_reason": None}
                answer.update(first=turn["first"], later=turn["later"])
            else:
                clock = clock_for(ctx, entry["capture_now"])
                kwargs = replay_kwargs(entry, arm["id"])
                response = client.create_message_sync(**kwargs, run_clock=clock)
                answer = answer_of(response)
    except CapExceeded as exc:
        error = str(exc)
    except Exception as exc:  # noqa: BLE001 - recorded, never retried
        error = f"{type(exc).__name__}: {exc}"
    failed = [d for d in guard.dispatches if "error" in d]
    if guard.cap_hit or (error and "daily budget" in error and not failed):
        # The engine's own budget, the backstop, refused before the transport.
        status = "cap"
    elif failed or error or answer is None:
        status = "error"
        error = error or failed[0]["error"]
    elif not guard.dispatches:
        # An agent loop answers a refusal with text of its own: no request left.
        status, error = "error", "no request reached the transport"
    else:
        status = "scored"
    row = base_row(run, arm, case, repetition, status, error)
    usage = {"input_tokens": 0, "output_tokens": 0}
    for dispatch in guard.dispatches:
        for side in usage:
            value = (dispatch.get("usage") or {}).get(side)
            usage[side] += value if isinstance(value, int) else 0
    row.update(
        answer=answer,
        dispatches=guard.dispatches,
        usage=usage,
        cost_micro_usd=sum(d.get("cost") or 0 for d in guard.dispatches),
        latency_ms=round((time.perf_counter() - started) * 1000),
        snapshot_version=ctx.snapshot_version,
    )
    if status == "scored":
        row["scoring"] = scoring.score(run.role, case, answer, entry["request"], run.document)
    logger.debug(f"[measure] {cell.key} status={status} error={error}")
    return row


def measure(
    ctx: Context, runs: list[RoleRun], repetition: int = 1, only: set | None = None
) -> None:
    """Every (role, arm, case) in priority order, skipping what the ledger already holds.

    ``only`` limits the cells to these ``(role, arm, case_id)`` triples. Raises
    ``CapExceeded`` after recording the cell the cap stopped.
    """
    for run in runs:
        for arm in run.arms:
            streak, unpriced = 0, price_refusal(arm["id"])
            for case in run.document["cases"]:
                if only is not None and (run.role, arm["id"], case["id"]) not in only:
                    continue
                cell = Cell(run.role, arm["id"], case["id"], repetition)
                if cell.key in ctx.results.done():
                    continue
                if cell.key in ctx.ledger.dispatched_cells():
                    ctx.results.append(base_row(run, arm, case, repetition, "interrupted"))
                    continue
                if unpriced or streak >= FAILURES_BEFORE_SKIP:
                    status = "unpriced" if unpriced else "skipped"
                    ctx.results.append(base_row(run, arm, case, repetition, status, unpriced))
                    continue
                row = run_cell(ctx, run, arm, case, repetition)
                ctx.results.append(row)
                if row["status"] == "cap":
                    raise CapExceeded(row["error"])
                streak = streak + 1 if row["status"] == "error" else 0


def disagreements(rows: list[dict], runs: list[RoleRun]) -> set:
    """``(role, arm, case_id)`` whose first-repetition label result differs from the reference's."""
    first = {
        (r["role"], r["arm"], r["case_id"]): r["scoring"]["label_match"]
        for r in rows
        if r["repetition"] == 1 and r["status"] == "scored"
    }
    found = set()
    for run in runs:
        reference = next(arm["id"] for arm in run.arms if arm["reference"])
        for case in run.document["cases"]:
            ref = first.get((run.role, reference, case["id"]))
            for arm in run.arms:
                mine = first.get((run.role, arm["id"], case["id"]))
                if ref is not None and mine is not None and not arm["reference"] and mine != ref:
                    found.add((run.role, arm["id"], case["id"]))
    return found


def run_all(ctx: Context, runs: list[RoleRun], repeat: bool) -> int:
    """The first repetition, then (``repeat``) the disagreements and the reference's second."""
    try:
        measure(ctx, runs)
        if repeat:
            measure(ctx, runs, 2, only=disagreements(ctx.results.rows, runs))
            reference = {
                (run.role, arm["id"], case["id"])
                for run in runs
                for arm in run.arms
                if arm["reference"]
                for case in run.document["cases"]
            }
            measure(ctx, runs, 2, only=reference)
    except CapExceeded as stop:
        print(f"stopped by the cap: {stop}", file=sys.stderr)
        return EXIT_CAP
    return 0


def load_runs(roles: list[str], arms: dict, *, check_fresh: bool = True) -> list[RoleRun]:
    """Each role's documents, refused when its requests are stale for today's code."""
    import build_measurement_requests as builder

    runs = []
    for role in [r for r in common.PRIORITY if r in roles]:
        committed = common.load_requests(role)
        if committed["case_set_sha256"] != common.case_set_sha256(role):
            raise SystemExit(f"{role}: requests.json was captured from another cases.json")
        if check_fresh and builder.drift(role, builder.build(role)):
            raise SystemExit(f"{role}: requests.json is stale; run build_measurement_requests.py")
        harness = common.load_harness(role) if role in common.AGENT_ROLES else None
        runs.append(RoleRun(role, common.load_document(role), committed, arms[role], harness))
    return runs


def summary(rows: list[dict]) -> list[str]:
    """Per role and arm: scored cases, label matches, bars and critical failures."""
    table: dict = {}
    for row in common.latest_rows(rows):
        entry = table.setdefault(
            (row["role"], row["arm"]), {"n": 0, "match": 0, "bars": 0, "crit": 0}
        )
        if row["status"] != "scored":
            entry.setdefault(row["status"], 0)
            entry[row["status"]] += 1
            continue
        entry["n"] += 1
        entry["match"] += row["scoring"]["label_match"]
        entry["bars"] += not row["scoring"]["bars_ok"]
        entry["crit"] += row["scoring"]["critical"]
    return [f"{role} {arm}: {counts}" for (role, arm), counts in table.items()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure the bootstrap arms on each role.")
    parser.add_argument(
        "--arms", type=Path, required=True, help="resolve_models.py --bootstrap output"
    )
    parser.add_argument("--roles", help="comma-separated roles (default: every role with cases)")
    parser.add_argument("--out", type=Path, help="output directory (ledger, results; resumable)")
    parser.add_argument("--cap", type=Decimal, default=DEFAULT_CAP, help="hard cap in USD")
    parser.add_argument("--repeat-disagreements", action="store_true")
    parser.add_argument("--project", action="store_true", help="free cost projection, no call")
    parser.add_argument("--dry-run", action="store_true", help="scripted transport, no network")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    common.importable()
    asked = [r.strip() for r in (args.roles or "").split(",") if r.strip()]
    unknown = [r for r in asked if r not in common.HARNESS_ROLES + common.CORPUS_ROLES]
    if unknown:
        parser.error(f"unknown role(s) {unknown}")
    roles = [r for r in asked or common.HARNESS_ROLES if r in common.HARNESS_ROLES]
    corpus = not asked or any(r in common.CORPUS_ROLES for r in asked)
    arms = common.load_arms(args.arms)
    if args.project:
        import measurement_projection as projection

        runs = load_runs(roles, arms, check_fresh=False)
        return projection.main(runs, arms, args.cap, corpus_roles=corpus)
    if asked and corpus:
        parser.error(f"{common.CORPUS_ROLES} run on the corpus runner (test_mnemonic_corpus_live)")
    if args.out is None:
        parser.error("--out is required unless --project")
    key = DRY_KEY if args.dry_run else os.environ.get(KEY_ENV, "").strip()
    if not key:
        print(f"refused: {KEY_ENV} is not set; nothing sent", file=sys.stderr)
        return 1
    runs = load_runs(roles, arms)
    args.out.mkdir(parents=True, exist_ok=True)
    lock = (args.out / "measure.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    from zylch.llm.roles import catalogue

    forbidden = () if args.dry_run else (key,)
    cap_micro = int(args.cap * 1_000_000)
    ledger = Ledger(args.out / "ledger.jsonl", cap_micro, forbidden)
    results = Results(args.out / "results.jsonl", forbidden)
    version = catalogue.layers()[0]["version"]
    http = None
    if args.dry_run:
        import measurement_dry

        http = measurement_dry.scripted_http(measurement_dry.default_answer)
    ctx = Context(ledger, results, key, version, http)
    run_note = {
        "roles": [run.role for run in runs],
        "cap_usd": str(args.cap),
        "dry_run": args.dry_run,
        "snapshot_version": version,
        "arms": args.arms.name,
        "arms_sha256": common.sha256_hex(args.arms.read_bytes()),
    }
    (args.out / f"run-{int(time.time())}.json").write_text(json.dumps(run_note, indent=1))
    with measurement_profile(key, args.cap):
        code = run_all(ctx, runs, args.repeat_disagreements)
    print("\n".join(summary(results.rows)))
    totals = {k: v / 1e6 for k, v in ledger.totals().items()}
    print(f"ledger (USD): {totals}; cap {args.cap}")
    return code


if __name__ == "__main__":
    sys.exit(main())
