#!/usr/bin/env python3
"""Resolve each role's rankings per preset; write the snapshot and, once measured, the table.

Resolver v2 (milestone 10). Ported from `malemi/mrcall-ai-kit`
(`shared/scripts/resolve-models.py`, `c88b024`, MIT) as 10a was: the sources,
the fixture layout, the atomic write and the exit codes are the kit's; the
choosing lives in `zylch/llm/roles/` (`candidates.py`, `impute.py`,
`resolver.py`, `snapshot.py`, `gates.py`), which this script loads as a
package from its files, so it runs with the standard library alone, from any
directory, with or without the engine installed.

It reads OpenRouter's catalogue (`/models`, no key), its benchmarks
(`/benchmarks`, with the key read from `OPENROUTER_API_KEY` and from nowhere
else) and the endpoints of every catalogue entry a role may rank
(`/models/<id>/endpoints`, no key: tools, the minimum context, no variant,
no alias), and `zylch/llm/roles/measured.json` when it exists. It prints the
screen, the scores (an imputed one marked with its deviation, the unscored
listed) and per preset and role both rankings, or the roles the measurement
does not cover yet.

- no flag: print; nothing written.
- `--apply`: write `snapshot.json` (always, once it passes its gates) and
  `table.json` only when `measured.json` covers every role, no ceiling is
  raised, every role ranks a model and the table passes its gates;
  otherwise report what blocks the table.
- `--check`: compare the decision record (per preset the ceiling, per role
  both rankings in order) of the committed `table.json` with this read's.
  Prices, scores and stamps are not compared, so a refresh that moves no
  pick and no order is no drift.
- `--bootstrap`: print the measurement's arms (brief D7) as JSON on
  standard output, the report on standard error; nothing written.
- `--fixture DIR` reads saved payloads instead of the network; `--save DIR`
  saves what a run read, in the layout `--fixture` reads (`models.json`,
  `benchmarks.json`, `endpoints.json`, `read-at.txt`).

Exit codes: 0 normally (with `--apply`, also when the table only waits for
the measurement: the snapshot is written); 1 when a source cannot be read or
a role has no candidate at any price (nothing written), under `--check` on a
drifted or missing table, and under `--apply` when the snapshot fails its
gates (nothing written) or the table cannot be published for another reason
(a raised ceiling, a role no measured model qualifies for, a failed gate);
2 on a configuration error (`requirements.json` or `measured.json`).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib
import json
import os
import pathlib
import sys
import tempfile
import types
import urllib.error
import urllib.parse
import urllib.request

ENGINE = pathlib.Path(__file__).resolve().parents[1]
ROLES = ENGINE / "zylch" / "llm" / "roles"
REQUIREMENTS = ROLES / "requirements.json"
SNAPSHOT = ROLES / "snapshot.json"
TABLE = ROLES / "table.json"
MEASURED = ROLES / "measured.json"
PACKAGE = "mrcall_model_roles"


def _load_roles() -> tuple:
    """The role modules as a package read from their files: the engine's own
    package would import the LLM SDKs, which this script must not need."""
    if PACKAGE not in sys.modules:
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(ROLES)]
        sys.modules[PACKAGE] = package
    names = ("candidates", "gates", "resolver", "snapshot")
    return tuple(importlib.import_module(f"{PACKAGE}.{name}") for name in names)


candidates, gates, resolver, snapshot = _load_roles()

DEFAULT_API = "https://openrouter.ai/api/v1"
# The API base can be pointed elsewhere, which is how a test serves payloads.
API_ENV = "MRCALL_RESOLVER_OPENROUTER_API"
KEY_ENV = "OPENROUTER_API_KEY"
FIXTURE_CATALOGUE = "models.json"
FIXTURE_BENCHMARKS = "benchmarks.json"
FIXTURE_ENDPOINTS = "endpoints.json"
FIXTURE_READ_AT = "read-at.txt"
WAITING = "measured.json does not cover"


def fetch(url: str, key: str | None = None) -> bytes:
    """GET one endpoint; Refused on an HTTP error or an unreachable host."""
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "mrcall resolve_models"}
    )
    if key:
        request.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as err:
        raise candidates.Refused(f"cannot read {url}: HTTP {err.code}") from None
    except (urllib.error.URLError, OSError) as err:
        raise candidates.Refused(f"cannot read {url}: {getattr(err, 'reason', err)}") from None


def read_live(req: dict) -> dict:
    """The payloads from OpenRouter: the catalogue, the benchmarks (the key
    from the environment only) and the endpoints of the endpoint pool."""
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        raise candidates.Refused(f"cannot read the benchmarks: {KEY_ENV} is not set")
    api = os.environ.get(API_ENV, DEFAULT_API).rstrip("/")
    read_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    catalogue = fetch(f"{api}/models")
    benchmarks = fetch(f"{api}/benchmarks", key)
    data, doc = candidates.payload_list(catalogue, "catalogue")
    candidates.complete_catalogue(doc, data)
    endpoints = {}
    for model in candidates.endpoint_pool(data, req["common"]):
        url = f"{api}/models/{urllib.parse.quote(model, safe='/')}/endpoints"
        try:
            payload = json.loads(fetch(url))
        except (ValueError, UnicodeDecodeError):
            raise candidates.Refused(f"cannot read {url}: not JSON") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise candidates.Refused(f"cannot read {url}: its `data` object is missing")
        endpoints[model] = payload["data"]
    return {
        "catalogue": catalogue,
        "benchmarks": benchmarks,
        "endpoints": json.dumps({"data": endpoints}, ensure_ascii=False).encode("utf-8"),
        "read_at": read_at,
    }


def read_sources(fixture: pathlib.Path | None, req: dict) -> dict:
    """The raw payloads: from a fixture directory, or live. A missing file, a
    missing key or an endpoint that fails is Refused, never empty."""
    if fixture is None:
        return read_live(req)

    def load(name: str) -> bytes:
        path = fixture / name
        if not path.is_file():
            raise candidates.Refused(f"cannot read {path}: no such file")
        return path.read_bytes()

    return {
        "catalogue": load(FIXTURE_CATALOGUE),
        "benchmarks": load(FIXTURE_BENCHMARKS),
        "endpoints": load(FIXTURE_ENDPOINTS),
        "read_at": load(FIXTURE_READ_AT).decode("utf-8").strip(),
    }


def save_sources(raw: dict, where: pathlib.Path) -> None:
    """Write what a run read in the layout `--fixture` reads."""
    where.mkdir(parents=True, exist_ok=True)
    (where / FIXTURE_CATALOGUE).write_bytes(raw["catalogue"])
    (where / FIXTURE_BENCHMARKS).write_bytes(raw["benchmarks"])
    (where / FIXTURE_ENDPOINTS).write_bytes(raw["endpoints"])
    (where / FIXTURE_READ_AT).write_text(raw["read_at"] + "\n", encoding="utf-8")


def dollars(value) -> str:
    """A price as `$n`, or `$?` when there is none."""
    return "$?" if value is None else f"${snapshot.text(value)}"


def scored(candidate: dict, index: str) -> str:
    """A candidate's score on `index`, with its deviation when imputed."""
    value = f"{index} {candidate['scores'][index]:.1f}"
    if index in candidate["imputed"]:
        value += f" (imputed, sd {candidate['imputed'][index]:.2f})"
    return value


def report(req: dict, sources: dict, result: dict, ranked: dict) -> list[str]:
    """The printed resolution: the read, the screen, the scores, the rankings."""
    lines = [
        f"catalogue read {sources['read_at']}, "
        f"benchmarks as of {sources['benchmarks_as_of'] or 'an unrecorded date'}",
        f"{len(sources['catalogue'])} catalogue entries, {len(result['dropped'])} screened out, "
        f"{len(result['pool'])} candidates scored, {len(result['unscored'])} unscored",
    ]
    for index, line in result["fits"].items():
        if line:
            lines.append(
                f"{index} imputed from intelligence over {line['n']} records: "
                f"slope {line['slope']:.3f}, deviation {line['sd']:.2f}"
            )
    if result["unscored"]:
        lines.append("unscored (never ranked until scored):")
        lines += [f"  {model}: {why}" for model, why in result["unscored"].items()]
    if result["ambiguous"]:
        lines.append(
            "not scored, their benchmark records disagree: "
            + ", ".join(sorted(result["ambiguous"]))
        )
    if ranked["blocked"]:
        lines.append(f"no ranking yet for {', '.join(ranked['blocked'])}: {WAITING} them")
    for preset, body in ranked["presets"].items():
        head = f"{preset}: ceiling {dollars(body['ceiling'])}"
        if body["raised_to"] is not None:
            head += f", raised to {dollars(body['raised_to'])} for this run (never published)"
        lines += ["", head]
        for role, row in body["roles"].items():
            rule = req["roles"][role]
            lines.append(f"  {role} ({rule['rule']} {rule['index']}):")
            for column, label in (("ranking", "every vendor"), ("anthropic_ranking", "Anthropic")):
                ranks = [
                    f"{n}. {c['direct_id'] if label == 'Anthropic' else c['id']} "
                    f"{scored(c, rule['index'])} {dollars(c['price'])}"
                    for n, c in enumerate(row[column], 1)
                ]
                lines.append(f"    {label}: " + ("; ".join(ranks) or "none"))
    return lines


def arms_json(req: dict, sources: dict, arms: dict) -> dict:
    """The bootstrap arms as the measurement tooling reads them."""
    roles = {}
    for role, body in arms["roles"].items():
        index = body["index"]
        rows = []
        for arm in body["arms"]:
            c = arm["candidate"]
            row = {"id": arm["id"], "why": arm["why"]}
            if c is not None:
                row.update(direct_id=c["direct_id"], output_price=snapshot.text(c["price"]))
                row.update(
                    score=round(c["scores"][index], 2) if c["scores"][index] is not None else None
                )
                row.update(
                    imputed_sd=round(c["imputed"][index], 2) if index in c["imputed"] else None
                )
            rows.append(row)
        roles[role] = {"rule": body["rule"], "index": index, "arms": rows}
    return {
        "schema": 1,
        "read_at": sources["read_at"],
        "reference": arms["reference"],
        "roles": roles,
    }


def differences(committed: dict, fresh: dict) -> list[str]:
    """One line per preset ceiling and per ranking whose order differs."""
    lines = []
    for preset in sorted(set(committed) | set(fresh)):
        old, new = committed.get(preset) or {}, fresh.get(preset) or {}
        if old.get("ceiling") != new.get("ceiling"):
            lines.append(f"{preset}: ceiling {old.get('ceiling')} -> {new.get('ceiling')}")
        old_roles, new_roles = old.get("roles") or {}, new.get("roles") or {}
        for role in sorted(set(old_roles) | set(new_roles)):
            for column in ("ranking", "anthropic_ranking"):
                was = (old_roles.get(role) or {}).get(column) or []
                now = (new_roles.get(role) or {}).get(column) or []
                if was != now:
                    pick = "pick" if (was[:1] != now[:1]) else "order"
                    shown = [" > ".join(e[0] for e in ids) or "none" for ids in (was, now)]
                    lines.append(f"{preset} / {role} / {column} ({pick}): {shown[0]} -> {shown[1]}")
    return lines


def write_atomically(path: pathlib.Path, text: str) -> None:
    """Replace `path` in one step, with the mode any new file there gets."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(tmp, 0o666 & ~umask)
        os.replace(tmp, path)
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise


def main(
    argv: list[str] | None = None,
    *,
    requirements_path: pathlib.Path = REQUIREMENTS,
    snapshot_path: pathlib.Path = SNAPSHOT,
    table_path: pathlib.Path = TABLE,
    measured_path: pathlib.Path = MEASURED,
) -> int:
    """Run the resolver; see the module docstring for the flags and exit codes."""
    ap = argparse.ArgumentParser(description="Resolve each role's rankings per preset.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write snapshot.json (and table.json)")
    mode.add_argument("--check", action="store_true", help="exit 1 on a drifted table.json")
    mode.add_argument("--bootstrap", action="store_true", help="print the measurement's arms")
    ap.add_argument("--fixture", type=pathlib.Path, metavar="DIR", help="read payloads from DIR")
    ap.add_argument("--save", type=pathlib.Path, metavar="DIR", help="save the payloads to DIR")
    args = ap.parse_args(argv)
    try:
        req_bytes = requirements_path.read_bytes()
        req = resolver.validate_requirements(json.loads(req_bytes), requirements_path.name)
        measured_bytes = measured_path.read_bytes() if measured_path.is_file() else None
        measured = None
        if measured_bytes is not None:
            measured = resolver.validate_measured(
                json.loads(measured_bytes), req["roles"], measured_path.name
            )
    except (resolver.ConfigError, OSError, ValueError) as err:
        print(f"resolve_models: {err}", file=sys.stderr)
        return 2
    try:
        raw = read_sources(args.fixture, req)
        if args.save is not None:
            save_sources(raw, args.save)
        sources = resolver.read(req, raw)
        result = resolver.pool(req, sources)
    except candidates.Refused as err:
        print(f"resolve_models: {err}. Nothing written.", file=sys.stderr)
        return 1
    rules = candidates.policy(req)
    snap = snapshot.build(sources["catalogue"], sources["endpoints"], rules, sources["read_at"])
    ranked = resolver.rankings(req, result["pool"], measured)
    lines = report(req, sources, result, ranked)
    if args.bootstrap:
        print("\n".join(lines), file=sys.stderr)
        arms = resolver.bootstrap(req, result["pool"])
        print(json.dumps(arms_json(req, sources, arms), indent=2, ensure_ascii=False))
        return 0
    print("\n".join(lines))
    reasons = resolver.publishable(ranked)
    table = None
    if not reasons:
        stamps = {
            "resolved_at": datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "catalogue_read_at": sources["read_at"],
            "requirements_sha256": hashlib.sha256(req_bytes).hexdigest(),
            "measured_sha256": hashlib.sha256(measured_bytes).hexdigest(),
        }
        table = resolver.document(ranked, stamps)
    if args.check:
        return check(table, reasons, table_path)
    if args.apply:
        return apply(req, snap, table, reasons, snapshot_path, table_path)
    print(f"\nnothing written; run with --apply to write {snapshot_path.name}")
    return 0


def check(table: dict | None, reasons: list[str], table_path: pathlib.Path) -> int:
    """`--check`: the committed table's decision record against this read's."""
    if table is None:
        print("\nno table from this read: " + "; ".join(reasons))
        return 1
    if not table_path.is_file():
        print(f"\nno committed {table_path.name}: every ranking is new")
        return 1
    committed = json.loads(table_path.read_text(encoding="utf-8"))
    changes = differences(resolver.decision(committed), resolver.decision(table))
    print("\nagainst the committed table's decision record:")
    print("\n".join(f"  {line}" for line in changes) if changes else "  no change")
    return 1 if changes else 0


def apply(req, snap, table, reasons, snapshot_path, table_path) -> int:
    """`--apply`: the snapshot always, the table when it can be published."""
    try:
        gates.check_snapshot(snap)
    except gates.GateError as err:
        print(f"resolve_models: {err}. Nothing written.", file=sys.stderr)
        return 1
    write_atomically(snapshot_path, gates.dump(snap, 2) + "\n")
    print(f"\nwrote {snapshot_path.name} (version {snap['version']})")
    if table is None:
        print(f"{table_path.name} not written: " + "; ".join(reasons))
        return 0 if len(reasons) == 1 and reasons[0].startswith(WAITING) else 1
    try:
        gates.check_table(table, req, snap)
    except gates.GateError as err:
        print(f"{table_path.name} not written: {err}", file=sys.stderr)
        return 1
    write_atomically(table_path, gates.dump(table, 4) + "\n")
    print(f"wrote {table_path.name} (version {table['version']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
