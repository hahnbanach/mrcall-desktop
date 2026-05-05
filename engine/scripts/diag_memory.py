#!/usr/bin/env python3
"""Memory pipeline diagnostic for a desktop profile.

Prints, for the active profile (or one named on the command line):

  * total emails / processed / unprocessed by the memory worker
  * total blobs and a per-namespace breakdown
  * full-text hits for an arbitrary needle across both stores

Run after a complaint like "the assistant didn't find Carmine Salomone"
to know quickly whether the answer is "memory pipeline never ran on
those emails", "ran but extracted nothing", or "person genuinely not
in the data".

Usage:
    python -m zylch.scripts.diag_memory [--profile EMAIL_OR_UID] [--needle SUBSTRING]

Defaults to the only profile dir under ``~/.zylch/profiles/`` if there is
exactly one; otherwise lists them and exits.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import List, Optional

PROFILE_ROOT = Path.home() / ".zylch" / "profiles"


def _resolve_profile(name: Optional[str]) -> Path:
    if name:
        candidate = PROFILE_ROOT / name
        if not candidate.is_dir():
            sys.exit(f"profile dir not found: {candidate}")
        return candidate
    profiles = [p for p in PROFILE_ROOT.iterdir() if p.is_dir()]
    if not profiles:
        sys.exit(f"no profiles under {PROFILE_ROOT}")
    if len(profiles) == 1:
        return profiles[0]
    print("multiple profiles found, pick one with --profile:")
    for p in profiles:
        print(f"  {p.name}")
    sys.exit(2)


def _print_section(title: str) -> None:
    bar = "─" * (len(title) + 2)
    print(f"\n{bar}\n {title}\n{bar}")


def _scalar(c: sqlite3.Cursor, sql: str, args: tuple = ()) -> int:
    return int(c.execute(sql, args).fetchone()[0])


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", help="Profile dir name (email or Firebase UID)")
    ap.add_argument(
        "--needle",
        action="append",
        default=[],
        help="Substring to grep across emails+blobs. Repeatable.",
    )
    args = ap.parse_args(argv)

    profile_dir = _resolve_profile(args.profile)
    db = profile_dir / "zylch.db"
    if not db.exists():
        sys.exit(f"db not found: {db}")

    print(f"profile  : {profile_dir.name}")
    print(f"db file  : {db}")
    print(f"db bytes : {db.stat().st_size}")

    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    c = con.cursor()

    _print_section("emails")
    print(f"  total              : {_scalar(c, 'SELECT COUNT(*) FROM emails')}")
    print(
        f"  memory_processed   : "
        f"{_scalar(c, 'SELECT COUNT(*) FROM emails WHERE memory_processed_at IS NOT NULL')}"
    )
    print(
        f"  memory_unprocessed : "
        f"{_scalar(c, 'SELECT COUNT(*) FROM emails WHERE memory_processed_at IS NULL')}"
    )
    print(
        f"  task_processed     : "
        f"{_scalar(c, 'SELECT COUNT(*) FROM emails WHERE task_processed_at IS NOT NULL')}"
    )
    print(
        f"  archived (local)   : "
        f"{_scalar(c, 'SELECT COUNT(*) FROM emails WHERE archived_at IS NOT NULL')}"
    )
    print(
        f"  deleted (local)    : "
        f"{_scalar(c, 'SELECT COUNT(*) FROM emails WHERE deleted_at IS NOT NULL')}"
    )

    _print_section("blobs (memory)")
    print(f"  total : {_scalar(c, 'SELECT COUNT(*) FROM blobs')}")
    rows = c.execute(
        "SELECT namespace, COUNT(*) AS n FROM blobs "
        "GROUP BY namespace ORDER BY n DESC"
    ).fetchall()
    for row in rows:
        print(f"  {row['namespace'] or '(null)'}: {row['n']}")

    if args.needle:
        for n in args.needle:
            _print_section(f"needle: {n!r}")
            email_hits = c.execute(
                """
                SELECT id, date, from_email, from_name, to_email, subject
                FROM emails
                WHERE LOWER(
                    COALESCE(from_email,'') || ' ' ||
                    COALESCE(from_name,'')  || ' ' ||
                    COALESCE(to_email,'')   || ' ' ||
                    COALESCE(cc_email,'')   || ' ' ||
                    COALESCE(subject,'')    || ' ' ||
                    COALESCE(body_plain,'')
                ) LIKE ?
                ORDER BY date_timestamp DESC
                """,
                (f"%{n.lower()}%",),
            ).fetchall()
            print(f"  emails matching: {len(email_hits)}")
            for row in email_hits:
                print(
                    "   ",
                    row["date"],
                    "|",
                    row["from_name"] or row["from_email"],
                    "→",
                    row["to_email"] or "?",
                    "|",
                    row["subject"],
                )
            blob_hits = c.execute(
                "SELECT id, namespace, substr(content, 1, 200) AS preview "
                "FROM blobs WHERE LOWER(content) LIKE ?",
                (f"%{n.lower()}%",),
            ).fetchall()
            print(f"  blobs matching : {len(blob_hits)}")
            for row in blob_hits:
                print(f"    [{row['namespace']}] {row['id']}")
                print(f"      {row['preview']!r}")

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
