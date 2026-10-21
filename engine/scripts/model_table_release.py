#!/usr/bin/env python3
"""The release gate of the model table: the copies a release embeds (brief D8, AC 7).

`release.yml` fetches `v1/table.json` and `v1/snapshot.json` from the
`model-table` data branch into `zylch/llm/roles/` before the engine is
bundled and runs this check on them, so a release ships, as the engine's
run-time fallback (brief D9), the table the daily job last published. It
refuses — exit 1, with the reason as a workflow error — a copy that fails
the static gates (`gates.check_snapshot`, then `gates.check_table` against
this build's `requirements.json`) or whose snapshot was read more than 14
days ago. The age is the snapshot's `read_at`: the job republishes the
snapshot on every run that publishes, while it stamps the table again only
when a decision changes, so an old snapshot means the job has stopped
publishing. Standard library only.

    python engine/scripts/model_table_release.py [--roles DIR] [--max-age-days 14]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.append(str(HERE))  # resolve_models is a sibling script

import resolve_models as rm  # noqa: E402

MAX_AGE_DAYS = 14
STAMP = "%Y-%m-%dT%H:%M:%SZ"
NAMES = ("table.json", "snapshot.json", "requirements.json")


def problems(table, snapshot, requirements: dict, now: datetime, max_age_days: int) -> list[str]:
    """Why a release may not embed `table` and `snapshot` ([] when it may)."""
    try:
        rm.gates.check_snapshot(snapshot)
        rm.gates.check_table(table, requirements, snapshot)
    except rm.gates.GateError as err:
        return [str(err)]
    read_at = datetime.strptime(snapshot["read_at"], STAMP).replace(tzinfo=timezone.utc)
    if now - read_at > timedelta(days=max_age_days):
        stale = (
            f"the snapshot was read at {snapshot['read_at']}, more than {max_age_days} days "
            "ago: the daily model-table job has stopped publishing"
        )
        return [stale]
    return []


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    """Check the embedded copies; see the module docstring."""
    ap = argparse.ArgumentParser(description="Refuse a stale or failing embedded model table.")
    ap.add_argument("--roles", type=Path, default=rm.ROLES, help="where the copies are")
    ap.add_argument("--max-age-days", type=int, default=MAX_AGE_DAYS)
    args = ap.parse_args(argv)
    if not 0 < args.max_age_days <= MAX_AGE_DAYS:
        ap.error(f"the age limit is at most {MAX_AGE_DAYS} days")
    try:
        docs = {n: json.loads((args.roles / n).read_text(encoding="utf-8")) for n in NAMES}
    except (OSError, ValueError) as err:
        print(f"::error::model table refused: {err}")
        return 1
    table, snapshot = docs["table.json"], docs["snapshot.json"]
    when = now or datetime.now(timezone.utc)
    found = problems(table, snapshot, docs["requirements.json"], when, args.max_age_days)
    for problem in found:
        print(f"::error::model table refused: {problem}")
    if found:
        return 1
    print(
        f"model table embedded: table {table['version']}, "
        f"snapshot {snapshot['version']} read at {snapshot['read_at']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
