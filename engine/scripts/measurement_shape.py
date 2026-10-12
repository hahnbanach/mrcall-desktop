"""Is a recorded answer's request the one the arm receives today, after the shape? (M10, S4b7)

``measurement_rescore`` compares the *captured* request (``requests.json``,
before the engine shapes it) case by case. The engine then shapes every
request for its model (``zylch/llm/request_shape.py``) from the snapshot's
metadata: sampling fields dropped, reasoning set, ``strict`` tools,
``REASONING_HEADROOM`` added to ``max_tokens``. A change to that code or to
the snapshot changes what a model receives without moving a captured byte.
The headroom fix (``bf9b520d``/``ced704cb``) is one: MiMo v2.6, which reasons
by default and publishes a ``reasoning`` parameter, now gets
``max_tokens + 1024`` on every role.

``mark_stale`` (``derive_thresholds.py --shape-check``) therefore shapes each
row's request twice:

- as it was sent: ``request_shape.py`` as committed at the row's run commit
  (``run_commit``), with the metadata of the snapshot whose ``version`` the
  row records (found among the committed ``snapshot.json``);
- as it would be sent today: this checkout's ``request_shape.py`` with the
  build snapshot (``roles/snapshot.json``).

A harness role is compared on each case's captured request with the arm's
model (``measurement_runtime.replay_kwargs``). A corpus role's requests are
built inside the engine, so it is compared on a probe of the decision call's
shape (system, one user turn, ``MNEMONIC_MAX_TOKENS``, no tools). A row
whose two shaped requests differ gets status ``stale_request``: the arm is
incomplete in that run, never failed. ``shape_refused`` in the document names
the cases per role, run and arm.

What this does not cover: the transport's own conversion (the OpenRouter body,
the provider object with ``max_price`` and ``only``), which routes and caps
the request but does not change what the model is asked; and the later turns
of an agent loop, whose shape follows from the same metadata as the first.
"""

from __future__ import annotations

import json
import subprocess
import types
from functools import lru_cache

import measurement_common as common

SHAPE_REL = "zylch/llm/request_shape.py"
SNAPSHOT_REL = "zylch/llm/roles/snapshot.json"
PROBE_MAX_TOKENS = 2048  # zylch/memory/mnemonic/agent.py: MNEMONIC_MAX_TOKENS


class ShapeRefused(RuntimeError):
    """A row whose sent request cannot be reconstructed (no commit, an unknown snapshot)."""


def _source(commit: str | None, rel: str) -> bytes:
    if commit is None:
        return (common.ENGINE / rel).read_bytes()
    shown = subprocess.run(
        ["git", "-C", str(common.ENGINE), "show", f"{commit}:./{rel}"], capture_output=True
    )
    if shown.returncode:
        raise ShapeRefused(f"{rel} is not committed at {commit}")
    return shown.stdout


@lru_cache(maxsize=None)
def snapshot(version: str | None) -> dict:
    """The committed snapshot of ``version``; ``None``: the build snapshot of this checkout."""
    if version is None:
        return json.loads(_source(None, SNAPSHOT_REL))
    import measurement_rescore as rescore

    def wanted(data: bytes) -> bool:
        try:
            return json.loads(data).get("version") == version
        except ValueError:
            return False

    data = rescore.committed_version(SNAPSHOT_REL, wanted)
    if data is None:
        raise ShapeRefused(f"no committed snapshot.json of version {version}")
    return json.loads(data)


@lru_cache(maxsize=None)
def shaper(commit: str | None, version: str | None):
    """``request_shape`` as committed at ``commit`` (None: this checkout), reading ``version``."""
    common.importable()
    module = types.ModuleType(f"request_shape_{commit or 'today'}")
    module.__package__ = "zylch.llm"  # its lazy relative imports resolve to today's package
    exec(compile(_source(commit, SHAPE_REL), f"{commit}:{SHAPE_REL}", "exec"), module.__dict__)
    models = snapshot(version)["models"]
    module._metadata = lambda model: (models.get(model) or {}).get("metadata")
    return module


def requests_for(role: str, arm: str) -> dict:
    """``{case_id: request}``: what the arm is asked, before the shape."""
    if role in common.CORPUS_ROLES:
        probe = {
            "model": arm,
            "system": "probe",
            "messages": [{"role": "user", "content": "probe"}],
            "max_tokens": PROBE_MAX_TOKENS,
        }
        return {"*": probe}
    out = {}
    for entry in common.load_requests(role)["requests"]:
        request = {k: v for k, v in entry["request"].items() if k != "model"}
        out[entry["case_id"]] = {**request, "model": arm}
    return out


@lru_cache(maxsize=None)
def stale_cases(role: str, arm: str, commit: str, version: str) -> tuple[str, ...]:
    """The cases whose shaped request at ``commit``/``version`` is not today's."""
    sent, today = shaper(commit, version), shaper(None, None)
    stale = []
    for case_id, request in requests_for(role, arm).items():
        before = common.canonical(sent.shaped(json.loads(json.dumps(request))))
        now = common.canonical(today.shaped(json.loads(json.dumps(request))))
        if before != now:
            stale.append(case_id)
    return tuple(sorted(stale))


def mark_stale(rows: list[dict], record: dict) -> list[dict]:
    """``rows`` with those whose shaped request is not today's as ``stale_request``."""
    out = []
    for row in rows:
        commit, version = row.get("run_commit"), row.get("snapshot_version")
        if not commit or not version:
            raise ShapeRefused(
                f"{row['role']} {row['arm']} {row['case_id']}: no run commit or snapshot version"
            )
        stale = stale_cases(row["role"], row["arm"], commit, version)
        if stale and (stale == ("*",) or row["case_id"] in stale):
            key = f"{row.get('run', '')}|{row['arm']}"
            cases = record.setdefault(row["role"], {}).setdefault(key, [])
            cases.append(row["case_id"])
            row = {**row, "status": "stale_request"}
        out.append(row)
    for role in record.values():
        for key in role:
            role[key] = sorted(set(role[key]))
    return out
