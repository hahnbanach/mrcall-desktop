"""Paid outcomes the daily model-table job remembers across runs: smokes and time-limit stops.

Pure; kept in `v1/results.json` beside the measurement results
(`model_table_results.py`), pushed with the check that paid for them.

**Smokes** (`smokes`: one entry per model, the latest). A smoke depends on
the model's request metadata — `reasoning`, `parameters`, `forced_tool`, in
the catalogue entry and the direct entry (`model_table_decide.METADATA`) —
so its outcome is kept with that metadata's `fingerprint` and stands only
while today's snapshot gives the model the same one: a changed model is
smoked again (brief D8). Each outcome stands `SMOKE_DAYS` (7) from when it
was paid for:

- `passed`: the model is not smoked again; its measurement may follow (a
  measurement the deadline deferred is not paid for with a second smoke).
- `failed`: the model is out of the run's options, as a smoke failed in the
  run is (a ranked model is replaced). After the 7 days the failure still
  stands, as `retry`, until the model passes a smoke or its metadata
  changes: the model is smoked again before anything else of it counts —
  a published entry or a passing measurement does not bring it back
  without a passing smoke (`model_table_decide._status`).
- `uncertain` (a call with no settled answer, an error, a smoke stopped by
  its own cap after a paid call): an entrant's smoke is not retried. A smoke
  the publication waits for — a ranked model whose metadata changed — is
  retried by every run, since without it nothing can be published.

A smoke that sent nothing (spent nothing) is not kept, nor an outcome of
a model today's snapshot does not hold (no fingerprint). Within a run no
smoke is sent twice.

**Stops** (`stops`: one entry per model and role). A measurement stopped at
its time limit (`model_table_deadline.limit_minutes`) is not tried again for
`STOP_DAYS` (14), unless the role's case-set or prompt hash or the model's
request metadata changes: a chronically slow model is not paid for daily.
A corpus run's stop is kept for the three memory roles it measures.

**Pruning** (`prune`, with the publication): what no longer stands goes.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone

import model_table_decide as decide

STAMP = "%Y-%m-%dT%H:%M:%SZ"
SMOKE_DAYS, STOP_DAYS = 7, 14
OUTCOMES = ("passed", "failed", "uncertain")
SMOKE_FIELDS = ("run", "model", "metadata_sha256", "at", "outcome", "detail")
STOP_FIELDS = ("run", "model", "role", "case_set_sha256", "prompt_sha256", "metadata_sha256")


def fingerprint(snapshot: dict, model: str, direct_id: str | None) -> str | None:
    """The sha256 of the model's request metadata in `snapshot`, catalogue
    entry and direct entry (module docstring); None for a model it lacks."""
    entry = snapshot.get("models", {}).get(model)
    if entry is None:
        return None
    direct = snapshot.get("direct", {}).get(direct_id) if direct_id else None
    parts = [
        {f: (body or {}).get("metadata", {}).get(f) for f in decide.METADATA}
        for body in (entry, direct)
    ]
    text = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check(doc: dict) -> None:
    """Raise ValueError unless `doc`'s `smokes` and `stops` (when present) are readable."""
    for name, fields in (("smokes", SMOKE_FIELDS), ("stops", STOP_FIELDS + ("at",))):
        entries = doc.get(name, [])
        if not isinstance(entries, list):
            raise ValueError(f"results.json: {name} must be a list")
        for number, entry in enumerate(entries, 1):
            if not isinstance(entry, dict) or not all(
                isinstance(entry.get(f), str) for f in fields if f != "detail"
            ):
                raise ValueError(f"results.json: {name} entry {number} lacks {', '.join(fields)}")
            if name == "smokes" and entry["outcome"] not in OUTCOMES:
                raise ValueError(f"results.json: smokes entry {number} has no outcome")
            _when(entry["at"])


def _when(at: str) -> datetime:
    try:
        return datetime.strptime(at, STAMP).replace(tzinfo=timezone.utc)
    except ValueError:
        raise ValueError(f"results.json: {at!r} is not a time") from None


def add_smoke(doc, run, model, metadata, at, outcome, detail) -> dict:
    """A copy of `doc` with this smoke outcome, replacing the model's last."""
    out = copy.deepcopy(doc)
    entry = {"run": run, "model": model, "metadata_sha256": metadata, "at": at}
    entry.update(outcome=outcome, detail=detail or "")
    out["smokes"] = [e for e in out.get("smokes", []) if e["model"] != model] + [entry]
    return out


def add_stop(doc, run, model, role, hashes, metadata, at, detail) -> dict:
    """A copy of `doc` with this time-limit stop, replacing the pair's last."""
    out = copy.deepcopy(doc)
    entry = {"run": run, "model": model, "role": role, "metadata_sha256": metadata, "at": at}
    entry.update(case_set_sha256=hashes[0], prompt_sha256=hashes[1], detail=detail)
    stops = out.get("stops", [])
    out["stops"] = [e for e in stops if (e["model"], e["role"]) != (model, role)] + [entry]
    return out


def _fresh(entry: dict, now: datetime) -> bool:
    return now < _when(entry["at"]) + timedelta(days=SMOKE_DAYS)


def _stands_smoke(entry: dict, now: datetime, fp) -> bool:
    """Whether the outcome still counts: under today's fingerprint, and
    fresh, or a failure (it stands until a smoke passes)."""
    lasting = _fresh(entry, now) or entry["outcome"] == "failed"
    return lasting and entry["metadata_sha256"] == fp(entry["model"])


def _stands_stop(entry: dict, now: datetime, fp, hashes: dict) -> bool:
    fresh = now < _when(entry["at"]) + timedelta(days=STOP_DAYS)
    want = hashes.get(entry["role"])
    today = want is not None and (entry["case_set_sha256"], entry["prompt_sha256"]) == tuple(want)
    return fresh and today and entry["metadata_sha256"] == fp(entry["model"])


def live(doc: dict, now: datetime, fp, hashes: dict) -> tuple[dict, dict]:
    """What stands today: `{model: (outcome, why)}` of the smokes and
    `{(model, role): why}` of the stops; `fp(model)` is today's fingerprint."""
    smokes, stops = {}, {}
    for e in doc.get("smokes", []):
        if not _stands_smoke(e, now, fp):
            continue
        until = (_when(e["at"]) + timedelta(days=SMOKE_DAYS)).strftime(STAMP)
        detail = f": {e['detail']}" if e["detail"] else ""
        if _fresh(e, now):
            smokes[e["model"]] = (
                e["outcome"],
                f"smoke {e['outcome']} at {e['at']}{detail}; it stands until {until} "
                "unless the model's request metadata changes",
            )
        else:  # a failure past its week: smoked again before it counts
            smokes[e["model"]] = (
                "retry",
                f"smoke failed at {e['at']}{detail}; it re-enters only after a passing smoke",
            )
    for e in doc.get("stops", []):
        if _stands_stop(e, now, fp, hashes):
            until = (_when(e["at"]) + timedelta(days=STOP_DAYS)).strftime(STAMP)
            stops[(e["model"], e["role"])] = (
                f"stopped at its time limit at {e['at']}; not tried again before {until} "
                "unless the role's cases or prompt or the model's request metadata change"
            )
    return smokes, stops


def prune(doc: dict, now: datetime, fp, hashes: dict) -> dict:
    """A copy of `doc` keeping only the smokes and stops that stand."""
    out = copy.deepcopy(doc)
    out["smokes"] = [e for e in out.get("smokes", []) if _stands_smoke(e, now, fp)]
    out["stops"] = [e for e in out.get("stops", []) if _stands_stop(e, now, fp, hashes)]
    return out
