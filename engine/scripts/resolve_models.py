#!/usr/bin/env python3
"""Resolve each engine role's model per preset; print the table and its diff.

Ported from `malemi/mrcall-ai-kit` (`shared/scripts/resolve-models.py`,
`c88b024`, MIT): the sources, the fixture layout, the atomic write and the
exit codes are the kit's; the choosing lives in `zylch/llm/roles/resolver.py`,
which this script loads by file path, so it runs with the standard library
alone, from any directory, with or without the engine installed.

It reads OpenRouter's catalogue (`/models`, no key) and its benchmarks
(`/benchmarks`, with the key read from `OPENROUTER_API_KEY` and from nowhere
else), resolves every preset and role of `zylch/llm/roles/requirements.json`,
and prints, per preset and role, the pick, its price, whether it is below the
floor, the Anthropic fallback and the MrCall id; then the diff against the committed
`zylch/llm/roles/resolved.json`. It writes that table only with `--apply`.

Extended over the kit: `--check` exits 1 when the committed table differs from
what the sources give (the CI drift job; the `as_of` stamps are not compared,
since a live read is always newer); the report is per role, not per agent file.

Exit codes: 0 normally; 1 when a source cannot be read or the data cannot
resolve a role (the table untouched), or under `--check` on a drifted table;
2 on a configuration error. `--fixture DIR` reads saved payloads instead of
the network; `--save DIR` saves what a run read, in the layout `--fixture`
reads (`models.json`, `benchmarks.json`, `read-at.txt`).
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import urllib.error
import urllib.request

ENGINE = pathlib.Path(__file__).resolve().parents[1]
ROLES = ENGINE / "zylch" / "llm" / "roles"
REQUIREMENTS = ROLES / "requirements.json"
RESOLVED = ROLES / "resolved.json"

_spec = importlib.util.spec_from_file_location("roles_resolver", ROLES / "resolver.py")
resolver = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(resolver)

DEFAULT_API = "https://openrouter.ai/api/v1"
# The API base can be pointed elsewhere, which is how a test serves payloads.
API_ENV = "MRCALL_RESOLVER_OPENROUTER_API"
KEY_ENV = "OPENROUTER_API_KEY"
FIXTURE_CATALOGUE = "models.json"
FIXTURE_BENCHMARKS = "benchmarks.json"
FIXTURE_READ_AT = "read-at.txt"
RAISES = {"raised_to": "", "anthropic_raised_to": "fallback ", "mrcall_raised_to": "mrcall "}


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
        raise resolver.Refused(f"cannot read {url}: HTTP {err.code}") from None
    except (urllib.error.URLError, OSError) as err:
        raise resolver.Refused(f"cannot read {url}: {getattr(err, 'reason', err)}") from None


def read_sources(fixture: pathlib.Path | None) -> dict:
    """The raw payloads: from a fixture directory, or live. A missing fixture
    file, a missing key or an endpoint that fails is Refused, never empty."""
    if fixture is not None:

        def load(name: str) -> bytes:
            path = fixture / name
            if not path.is_file():
                raise resolver.Refused(f"cannot read {path}: no such file")
            return path.read_bytes()

        read_at = fixture / FIXTURE_READ_AT
        return {
            "catalogue": load(FIXTURE_CATALOGUE),
            "benchmarks": load(FIXTURE_BENCHMARKS),
            "read_at": read_at.read_text(encoding="utf-8").strip() if read_at.is_file() else None,
        }
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        raise resolver.Refused(f"cannot read the benchmarks: {KEY_ENV} is not set")
    api = os.environ.get(API_ENV, DEFAULT_API).rstrip("/")
    read_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "catalogue": fetch(f"{api}/models"),
        "benchmarks": fetch(f"{api}/benchmarks", key),
        "read_at": read_at,
    }


def save_sources(raw: dict, where: pathlib.Path) -> None:
    """Write what a run read in the layout `--fixture` reads."""
    where.mkdir(parents=True, exist_ok=True)
    (where / FIXTURE_CATALOGUE).write_bytes(raw["catalogue"])
    (where / FIXTURE_BENCHMARKS).write_bytes(raw["benchmarks"])
    if raw["read_at"]:
        (where / FIXTURE_READ_AT).write_text(raw["read_at"] + "\n", encoding="utf-8")


def dollars(value) -> str:
    """A price as `$n`, or `$?` when there is none."""
    return "$?" if value is None else f"${value:g}"


def differences(committed: dict | bool, table: dict) -> list[str]:
    """What changes between the committed table (False when there is none) and
    this run's, `as_of` aside: one line per preset field and per role whose
    entry differs."""
    if not committed:
        return ["no committed table: every row is new"]
    lines = []
    old_presets = committed.get("presets") if isinstance(committed, dict) else None
    old_presets = old_presets if isinstance(old_presets, dict) else {}
    for preset in sorted(set(old_presets) | set(table["presets"])):
        old, new = old_presets.get(preset) or {}, table["presets"].get(preset) or {}
        for field in ("ceiling", *RAISES):
            if old.get(field) != new.get(field):
                lines.append(f"{preset}: {field} {old.get(field)} -> {new.get(field)}")
        old_roles, new_roles = old.get("roles") or {}, new.get("roles") or {}
        for role in sorted(set(old_roles) | set(new_roles)):
            before, after = old_roles.get(role), new_roles.get(role)
            if before != after:
                was = (before or {}).get("catalogue_id", "-")
                now = (after or {}).get("catalogue_id", "-")
                lines.append(
                    f"{preset} / {role}: {was} -> {now}"
                    + ("" if was != now else " (scores, price, fallback or mrcall changed)")
                )
    return lines


def report(req: dict, result: dict, table: dict) -> list[str]:
    """The printed refresh: per preset and role, the pick and its price, the
    floor, the Anthropic fallback with its price, and the MrCall id."""
    lines = [
        f"catalogue read {result['read_at'] or 'at an unrecorded time'}, "
        f"benchmarks as of {result['benchmarks_as_of'] or 'an unrecorded date'}",
        f"{len(result['pool'])} catalogue entries meet every role's common requirements",
    ]
    if result["ambiguous"]:
        lines.append(
            "not scored, their benchmark records disagree: "
            + ", ".join(sorted(result["ambiguous"]))
        )
    for preset, outcome in table["presets"].items():
        ceiling = outcome["ceiling"]
        head = f"{preset}: " + ("no ceiling" if ceiling is None else f"ceiling {dollars(ceiling)}")
        for key, who in RAISES.items():
            head += f", {who}raised to {dollars(outcome[key])}" * (outcome[key] is not None)
        rows = []
        for role, row in outcome["roles"].items():
            note = f"{row['index']} {row['score']:g}"
            if row["below_floor"]:
                note += f", below the floor of {req['roles'][role]['floor']:g}"
            fb = row["anthropic_fallback"]
            pick = f"{row['catalogue_id']} ({dollars(row['price']['output'])})"
            fallback = f"fallback {fb['direct_id']} ({dollars(fb['price']['output'])})"
            fallback += " below floor" * fb["below_floor"]
            mc = row["mrcall"] or {}
            mrcall = f"mrcall {mc['id']} ({dollars(mc['price']['output'])})" if mc else ""
            mrcall = (mrcall + " below floor" * mc.get("below_floor", 0)) or "not served by credits"
            rows.append((role, pick, note, f"{fallback}  {mrcall}"))
        widths = [max(len(r[i]) for r in rows) for i in range(3)]
        lines += ["", head]
        lines += [
            "  " + "  ".join(r[i].ljust(widths[i]) for i in range(3)) + "  " + r[3] for r in rows
        ]
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
    resolved_path: pathlib.Path = RESOLVED,
) -> int:
    """Run the resolver; see the module docstring for the flags and exit codes."""
    ap = argparse.ArgumentParser(description="Resolve each role's model per preset.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write resolved.json")
    mode.add_argument("--check", action="store_true", help="exit 1 on a drifted resolved.json")
    ap.add_argument("--fixture", type=pathlib.Path, metavar="DIR", help="read payloads from DIR")
    ap.add_argument("--save", type=pathlib.Path, metavar="DIR", help="save the payloads to DIR")
    args = ap.parse_args(argv)
    try:
        req = resolver.validate_requirements(
            json.loads(requirements_path.read_text(encoding="utf-8")), requirements_path.name
        )
        committed = resolved_path.is_file() and json.loads(resolved_path.read_text("utf-8"))
    except (resolver.ConfigError, OSError, ValueError, KeyError, AttributeError) as err:
        print(f"resolve_models: {err}", file=sys.stderr)
        return 2
    try:
        raw = read_sources(args.fixture)
        if args.save is not None:
            save_sources(raw, args.save)
        result = resolver.resolve(req, raw)
    except resolver.Refused as err:
        print(f"resolve_models: {err}. {resolved_path.name} is unchanged.", file=sys.stderr)
        return 1
    table = resolver.document(req, result)
    changes = differences(committed, table)
    print("\n".join(report(req, result, table)))
    print("\nagainst the committed table:")
    print("\n".join(f"  {line}" for line in changes) if changes else "  no change")
    if args.check:
        return 1 if changes else 0
    if args.apply:
        write_atomically(resolved_path, json.dumps(table, indent=2) + "\n")
        print(f"wrote {resolved_path.name}")
    else:
        print(f"nothing written; run with --apply to write {resolved_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
