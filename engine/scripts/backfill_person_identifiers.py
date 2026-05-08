#!/usr/bin/env python3
"""Backfill the person_identifiers index from existing PERSON blobs.

Phase 1a (whatsapp-pipeline-parity, 2026-05-07) introduces a structured
index of (kind, value) tuples — email / phone / lid — extracted from
each PERSON-blob's `#IDENTIFIERS` block. The memory worker writes new
rows on every upsert, but pre-existing blobs in production profiles
have NO entries until they're re-extracted.

This script reconstructs the index by parsing every blob.content with
the same `_parse_identifiers_block` function the live worker uses, so
the parsing rules are guaranteed identical.

Idempotent — every row is upserted via the UNIQUE
(owner_id, kind, value, blob_id) constraint, so re-running on a
partially-backfilled DB is a no-op.

Usage:
    python -m zylch.scripts.backfill_person_identifiers --profile <UID>
    python -m zylch.scripts.backfill_person_identifiers --profile <UID> --dry-run
    python -m zylch.scripts.backfill_person_identifiers --all
    python -m zylch.scripts.backfill_person_identifiers --all --dry-run

The --all flag iterates every directory under ~/.zylch/profiles/.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import uuid as _uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

PROFILE_ROOT = Path.home() / ".zylch" / "profiles"


def _ensure_zylch_on_path() -> None:
    """Make `zylch.workers.memory` importable when run as a standalone
    script (without `python -m`). Walks up looking for the package root."""
    here = Path(__file__).resolve().parent
    candidates = [here.parent, here.parent.parent]
    for c in candidates:
        if (c / "zylch" / "__init__.py").exists():
            sys.path.insert(0, str(c))
            return


_ensure_zylch_on_path()

from zylch.workers.memory import _parse_identifiers_block  # noqa: E402


def _resolve_profile(name: Optional[str]) -> Path:
    if not name:
        sys.exit("--profile or --all required")
    candidate = PROFILE_ROOT / name
    if not candidate.is_dir():
        sys.exit(f"profile dir not found: {candidate}")
    return candidate


def _all_profiles() -> List[Path]:
    if not PROFILE_ROOT.is_dir():
        sys.exit(f"no profile root at {PROFILE_ROOT}")
    return sorted(p for p in PROFILE_ROOT.iterdir() if p.is_dir())


def _backfill(
    con: sqlite3.Connection,
    dry_run: bool,
) -> Tuple[int, int, Counter]:
    """Return (blobs_processed, rows_inserted, kind_counter)."""
    cur = con.cursor()

    # Confirm the target table exists (will fail loud if the engine
    # hasn't been restarted since Phase 1a landed).
    row = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        ("person_identifiers",),
    ).fetchone()
    if row is None:
        sys.exit(
            "table 'person_identifiers' missing — start the engine once "
            "to create it (init_db calls Base.metadata.create_all), then "
            "re-run this script."
        )

    # Fetch every blob; the parser will return [] for non-PERSON blobs
    # whose IDENTIFIERS block doesn't include any of our recognised
    # labels (Email/Phone/LID). This is wasteful for COMPANY/TEMPLATE
    # blobs but keeps the script free of duplicate filter logic that
    # could drift from the worker.
    blob_rows = list(cur.execute("SELECT id, owner_id, content FROM blobs"))

    # Pre-fetch existing (owner_id, blob_id, kind, value) so we know
    # what to skip without round-tripping per-row inserts.
    existing = set()
    for r in cur.execute("SELECT owner_id, blob_id, kind, value FROM person_identifiers"):
        existing.add((str(r[0]), str(r[1]), str(r[2]), str(r[3])))

    n_blobs = 0
    n_rows = 0
    kind_counter: Counter = Counter()

    write_cur = con.cursor()
    for blob_id, owner_id, content in blob_rows:
        if not blob_id or not owner_id or not content:
            continue
        blob_id = str(blob_id)
        owner_id = str(owner_id)

        identifiers = _parse_identifiers_block(content)
        if not identifiers:
            continue
        n_blobs += 1

        for kind, value in identifiers:
            k = str(kind).strip().lower()
            v = str(value).strip()
            if not k or not v:
                continue
            if (owner_id, blob_id, k, v) in existing:
                continue
            kind_counter[k] += 1
            n_rows += 1
            if not dry_run:
                write_cur.execute(
                    "INSERT INTO person_identifiers "
                    "(id, owner_id, blob_id, kind, value, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        str(_uuid.uuid4()),
                        owner_id,
                        blob_id,
                        k,
                        v,
                        datetime.utcnow().isoformat(sep=" ", timespec="microseconds"),
                    ),
                )
                existing.add((owner_id, blob_id, k, v))

    if not dry_run:
        con.commit()
    return n_blobs, n_rows, kind_counter


def _backfill_one(profile_dir: Path, dry_run: bool) -> Tuple[int, int]:
    db = profile_dir / "zylch.db"
    if not db.exists():
        print(f"  no zylch.db at {db} — skipping", file=sys.stderr)
        return 0, 0
    print(f"\nProfile: {profile_dir.name}", file=sys.stderr)
    print(f"DB:      {db}", file=sys.stderr)

    con = sqlite3.connect(str(db))
    try:
        n_blobs, n_rows, kinds = _backfill(con, dry_run=dry_run)
    finally:
        con.close()

    verb = "Would insert" if dry_run else "Inserted"
    print(
        f"  blobs with identifiers parsed: {n_blobs:>6}",
        file=sys.stderr,
    )
    print(f"  {verb} rows:                  {n_rows:>6}", file=sys.stderr)
    if kinds:
        print(
            f"  kinds: {dict(sorted(kinds.items()))}",
            file=sys.stderr,
        )
    return n_blobs, n_rows


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--profile", help="profile dir name (email or UID)")
    grp.add_argument(
        "--all",
        action="store_true",
        help=f"iterate every profile under {PROFILE_ROOT}",
    )
    ap.add_argument("--dry-run", action="store_true", help="parse but don't write")
    args = ap.parse_args(argv)

    if args.all:
        profiles = _all_profiles()
    else:
        profiles = [_resolve_profile(args.profile)]

    total_blobs = 0
    total_rows = 0
    for p in profiles:
        b, r = _backfill_one(p, dry_run=args.dry_run)
        total_blobs += b
        total_rows += r

    if len(profiles) > 1:
        print(
            f"\n=== TOTAL across {len(profiles)} profile(s): "
            f"{total_blobs} blob(s) parsed, "
            f"{'would insert' if args.dry_run else 'inserted'} "
            f"{total_rows} row(s). ===",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
