"""The daily model-table job's paid results, kept the moment they are paid for (`v1/results.json`).

Pure: the job (`model_table_job.py`) reads and pushes the file. A run could
lose every measurement it paid for: they entered the cache — `measured.json`,
keyed by (model, role, case-set hash, prompt hash) — only with the final
publish, which a run killed by its timeout, or one that cannot publish,
never reaches. So each measurement's results are pushed to the data branch
as soon as the measurement ends, in the same commit as the ledger row that
records its call (`model_table_records.Spend.spent`): what is paid for and
what it bought land together, before the next check is sent. A hard kill
then loses at most the check in flight, whose bound the pushed reservation
still holds.

**The file.** `{"schema": 1, "results": [entry, ...], "smokes": [...],
"stops": [...]}` (the smokes' outcomes and the measurements' time-limit
stops: `model_table_outcomes.py`). `results` is in the order the
results were measured; an entry is `run`, `model`, `role`,
`case_set_sha256`, `prompt_sha256`, `measured_at` and `result`: the
measurement's result as `model_table_measured.aggregate` gives it, not yet
judged (a result is judged against the role's reference when it is
recorded). One entry per (model, role, case-set hash, prompt hash): a later
measurement replaces it. The job's records format (sorted keys, two-space
indent); no engine or billing server reads it.

**Replay** (`replay`). A run starts by recording, in order, every entry whose
hashes are its role's today and which `measured.json` does not already hold
(a result there for that model and role, under those hashes, measured at
the same time or later), exactly as a fresh measurement is recorded — judged
against the role's reference, a re-measurement staged and swapped when whole
— at no cost. An entry that cannot be judged yet (no reference result under
today's hashes) is kept for a later run.

**Pruning** (`prune`). The publication that carries `measured.json` drops
the entries it holds, and the entries measured under hashes that are no
longer their role's: the file keeps only what is paid for and not yet
published. A run that cannot publish leaves every entry in place.
"""

from __future__ import annotations

import copy

import model_table_outcomes as outcomes

SCHEMA = 1
FIELDS = ("run", "model", "role", "case_set_sha256", "prompt_sha256", "measured_at")
JUDGEABLE = ("n", "passes", "bars_ok", "critical", "complete")


def empty() -> dict:
    return {"schema": SCHEMA, "results": [], "smokes": [], "stops": []}


def check(doc: object) -> dict:
    """Return `doc` when it is a results file the job reads, else raise
    ValueError: the job never overwrites a paid result it cannot read."""
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise ValueError(f"results.json: not a schema {SCHEMA} results file")
    entries = doc.get("results")
    if not isinstance(entries, list):
        raise ValueError("results.json: results must be a list")
    for number, entry in enumerate(entries, 1):
        if not isinstance(entry, dict) or not all(
            isinstance(entry.get(field), str) for field in FIELDS
        ):
            raise ValueError(f"results.json: entry {number} lacks {', '.join(FIELDS)}")
        result = entry.get("result")
        if not isinstance(result, dict) or not all(field in result for field in JUDGEABLE):
            raise ValueError(f"results.json: entry {number} holds no measurement result")
    outcomes.check(doc)
    return doc


def key(entry: dict) -> tuple[str, str, str, str]:
    """The cache key: (model, role, case-set hash, prompt hash)."""
    return entry["model"], entry["role"], entry["case_set_sha256"], entry["prompt_sha256"]


def add(doc: dict, run: str, model: str, role: str, hashes, at: str, result: dict) -> dict:
    """A copy of `doc` holding this result, replacing one under the same key."""
    entry = {"run": run, "model": model, "role": role, "measured_at": at}
    entry.update(case_set_sha256=hashes[0], prompt_sha256=hashes[1], result=dict(result))
    out = copy.deepcopy(doc)
    out["results"] = [e for e in out["results"] if key(e) != key(entry)] + [entry]
    return out


def _held(measured: dict, entry: dict) -> bool:
    """Whether `measured` holds the entry's result, or a later one, for its
    model and role under its hashes (in the role, or its re-measurement)."""
    want = (entry["case_set_sha256"], entry["prompt_sha256"])
    places = [measured["roles"].get(entry["role"])]
    places.append((measured.get("remeasure") or {}).get(entry["role"]))
    for body in places:
        if not body:
            continue
        held = body.get("results", {}).get(entry["model"])
        if not isinstance(held, dict):
            continue
        hashes = (
            held.get("case_set_sha256", body["case_set_sha256"]),
            held.get("prompt_sha256", body["prompt_sha256"]),
        )
        if hashes == want and held.get("measured_at", "") >= entry["measured_at"]:
            return True
    return False


def _today(entry: dict, hashes: dict) -> bool:
    want = hashes.get(entry["role"])
    return want is not None and (entry["case_set_sha256"], entry["prompt_sha256"]) == tuple(want)


def replay(doc: dict, measured: dict, hashes: dict, store) -> list[str]:
    """Record each pending entry of `doc` through `store(role, model, result,
    at)` (module docstring), which returns None or why the entry could not be
    judged; the lines for the report."""
    lines = []
    for entry in doc["results"]:
        if entry["role"] not in measured["roles"] or not _today(entry, hashes):
            continue
        if _held(measured, entry):
            continue
        why = store(entry["role"], entry["model"], entry["result"], entry["measured_at"])
        what = f"{entry['role']} on {entry['model']} (measured {entry['measured_at']})"
        lines.append(f"{what}: {why}, kept" if why else f"{what}: taken from results.json")
    return lines


def prune(doc: dict, measured: dict, hashes: dict) -> dict:
    """A copy of `doc` without what the `measured` being published holds and
    without results under hashes no longer their role's (module docstring)."""
    out = copy.deepcopy(doc)
    keep = []
    for entry in out["results"]:
        role = entry["role"]
        stale = role not in hashes or (hashes[role] is not None and not _today(entry, hashes))
        if not stale and not _held(measured, entry):
            keep.append(entry)
    out["results"] = keep
    return out
