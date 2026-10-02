#!/usr/bin/env python3
"""Capture each role's measurement requests with today's prompts (milestone 10, plan S4b).

For every role with a case set (``tests/fixtures/measurement/<ROLE>/``) this
runs the role's ``capture.py`` harness on its ``cases.json`` — the engine's own
code path, a recording client, a throwaway profile, no network and no key —
and writes ``<ROLE>/requests.json``: ``{"schema": 1, "role",
"prompt_sha256", "case_set_sha256", "requests": [{"case_id", "request",
"capture_now"}]}``. ``measurement_common.py`` documents exactly what each hash
covers. A harness that yields no request or more than one for a case is
refused and nothing is written for its role.

    python scripts/build_measurement_requests.py                 # every role
    python scripts/build_measurement_requests.py --roles CHAT,INTENT
    python scripts/build_measurement_requests.py --check         # compare, write nothing

``--check`` exits 1 when a committed ``requests.json`` is missing, names other
cases, or carries other hashes than a fresh capture: a prompt or a case set
changed and the requests (and any measurement taken on them) are stale.
Captures follow the engine's code: re-run this after any prompt change.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import measurement_common as common  # noqa: E402

logger = logging.getLogger("build_measurement_requests")


def build(role: str) -> dict:
    """The fresh ``requests.json`` document of ``role``, from its committed case set."""
    cases_bytes = common.cases_path(role).read_bytes()
    document = common.load_document(role)
    entries = common.capture(role, document)
    built = common.requests_document(role, document, entries, cases_bytes)
    logger.debug(f"[build] {role}: {len(entries)} requests prompt={built['prompt_sha256']}")
    return built


def drift(role: str, fresh: dict) -> list[str]:
    """How the committed ``requests.json`` differs from ``fresh`` (empty when it does not)."""
    path = common.requests_path(role)
    if not path.is_file():
        return [f"{role}: no {path.name}"]
    committed = common.load_requests(role)
    found = []
    for field in ("schema", "role", "prompt_sha256", "case_set_sha256"):
        if committed.get(field) != fresh[field]:
            found.append(f"{role}: {field} {committed.get(field)} != {fresh[field]}")
    ids = [entry["case_id"] for entry in committed.get("requests", [])]
    if ids != [entry["case_id"] for entry in fresh["requests"]]:
        found.append(f"{role}: committed requests name other cases")
    return found


def parse_roles(text: str | None) -> list[str]:
    if not text:
        return list(common.HARNESS_ROLES)
    roles = [part.strip() for part in text.split(",") if part.strip()]
    unknown = [role for role in roles if role not in common.HARNESS_ROLES]
    if unknown:
        raise SystemExit(
            f"unknown role(s) {unknown}; roles with a case set: {common.HARNESS_ROLES}"
        )
    return roles


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture each role's measurement requests.")
    parser.add_argument("--roles", help="comma-separated roles (default: every role with cases)")
    parser.add_argument("--check", action="store_true", help="compare with the committed files")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    problems = []
    for role in parse_roles(args.roles):
        try:
            fresh = build(role)
        except common.CaptureRefused as refused:
            print(f"refused: {refused}", file=sys.stderr)
            return 1
        if args.check:
            problems += drift(role, fresh)
            continue
        common.requests_path(role).write_text(common.dump(fresh), encoding="utf-8")
        print(
            f"{role}: {len(fresh['requests'])} requests, prompt {fresh['prompt_sha256']}, "
            f"case set {fresh['case_set_sha256']}"
        )
    if problems:
        print("\n".join(problems))
        return 1
    if args.check:
        print("every requests.json matches a fresh capture")
    return 0


if __name__ == "__main__":
    sys.exit(main())
