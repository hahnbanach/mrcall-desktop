#!/usr/bin/env python3
"""One role's measurement of the arms it is given, through ``measure_roles.py``'s own loop.

The daily model-table job's driver (``model_table_edges.Measurement`` runs it in
a process of its own). ``measure_roles.py`` measures the bootstrap arms with the
reference always first (``measurement_common.load_arms``): the one-off
measurement, where brief D7 judges each arm against the reference of the same
run. The daily job keeps the reference's result while its case-set and prompt
hashes are today's and judges a challenger against it, so it measures exactly
the arms it names, the reference only when it names it. Everything else is
slice S4b's: the role's requests (``load_runs``, refused when stale for today's
code), the disposable profile (``measurement_profile``: the key from
``OPENROUTER_API_KEY``, never from argv, in a mode-600 ``.env`` deleted after),
the ledger (an intent before each dispatch, the cap checked on settled spend
plus every open intent's bound, no retry), the results, the transport and the
scoring (``measure_roles.run_all``).

    python scripts/model_table_measure.py --role ROLE --arms ARMS.json --out DIR --cap 2 [--dry-run]

``ARMS.json`` is ``[{"id", "score", "reference"}]`` (``score``: the arm's index
score for the role). ``DIR`` receives ``ledger.jsonl`` and ``results.jsonl``.
Exit codes are ``measure_roles.py``'s: 0 done; 1 refused (stale requests, no key,
a corrupt ledger); 3 the cap stopped the run (what was measured is recorded).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import measure_roles  # noqa: E402
import measurement_common as common  # noqa: E402
from measurement_ledger import Ledger  # noqa: E402
from measurement_runtime import (  # noqa: E402
    DRY_KEY,
    KEY_ENV,
    Context,
    Results,
    measurement_profile,
)


def arms_for(role: str, given: list) -> dict:
    """``{role: [arm]}`` in ``measure_roles``' shape, exactly the arms given."""
    index = common.requirements()["roles"][role]["index"]
    arms = []
    for arm in given:
        reference = arm.get("reference") is True
        arms.append(
            {"id": arm["id"], "score": arm.get("score"), "index": index, "reference": reference}
        )
    return {role: arms}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure the given arms on one role.")
    parser.add_argument("--role", required=True, choices=common.HARNESS_ROLES)
    parser.add_argument("--arms", type=Path, required=True, help='[{"id", "score", "reference"}]')
    parser.add_argument(
        "--out", type=Path, required=True, help="the ledger's and results' directory"
    )
    parser.add_argument("--cap", type=Decimal, required=True, help="hard cap in USD")
    parser.add_argument("--dry-run", action="store_true", help="scripted transport, no network")
    args = parser.parse_args(argv)
    common.importable()
    key = DRY_KEY if args.dry_run else os.environ.get(KEY_ENV, "").strip()
    if not key:
        print(f"refused: {KEY_ENV} is not set; nothing sent", file=sys.stderr)
        return 1
    given = arms_for(args.role, json.loads(args.arms.read_text(encoding="utf-8")))
    try:
        runs = measure_roles.load_runs([args.role], given)
    except SystemExit as refused:  # load_runs refuses stale requests by exiting
        print(f"refused: {refused}", file=sys.stderr)
        return 1
    from zylch.llm.roles import catalogue

    args.out.mkdir(parents=True, exist_ok=True)
    forbidden = () if args.dry_run else (key,)
    ledger = Ledger(args.out / "ledger.jsonl", int(args.cap * 1_000_000), forbidden)
    results = Results(args.out / "results.jsonl", forbidden)
    http = None
    if args.dry_run:
        import measurement_dry

        http = measurement_dry.scripted_http(measurement_dry.default_answer)
    ctx = Context(ledger, results, key, catalogue.layers()[0]["version"], http)
    with measurement_profile(key, args.cap):
        return measure_roles.run_all(ctx, runs, False)


if __name__ == "__main__":
    sys.exit(main())
