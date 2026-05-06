#!/usr/bin/env python3
"""Backfill the email_blobs / calendar_blobs association tables.

Until 2026-05-06 the memory worker only stamped ``blob.events`` with
``"Extracted from email <id>"`` /
``"Extracted from calendar event '<summary>' (<start>)"`` strings. Fase
3.1 introduces a normalised index — ``email_blobs(email_id, blob_id)``
and ``calendar_blobs(event_id, blob_id)`` — that the F7 task-creation
path consults directly. This script reconstructs the index from the
historical ``blob.events`` strings.

Idempotent: every (email_id, blob_id) row is upserted via INSERT OR
IGNORE on the composite PK, so re-running on a partially-backfilled
DB is a no-op.

Usage:
    python -m zylch.scripts.backfill_email_blobs --profile <EMAIL_OR_UID>
    python -m zylch.scripts.backfill_email_blobs --profile <UID> --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple

PROFILE_ROOT = Path.home() / ".zylch" / "profiles"

# blob.events is a JSON list whose entries look like
# ``{"timestamp": "2026-…", "description": "Extracted from email <id>"}``
# for the email pipeline and
# ``{"timestamp": "…", "description": "Extracted from calendar event '<summary>' (<start>)"}``
# for the calendar pipeline. We anchor on the prefix and trust the
# id-shape (UUID for emails, free-form for calendar) — the patterns
# are stable strings written by the worker, not free-form prose.
EMAIL_PATTERN = re.compile(
    r"^Extracted from email\s+([^\s()]+)(?:\s*\(.*\))?\s*$", re.IGNORECASE
)
CALENDAR_PATTERN = re.compile(
    r"^Extracted from calendar event\s+'(.+?)'\s*\(.*\)\s*$", re.IGNORECASE
)


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
    print("multiple profiles found, pick one with --profile:", file=sys.stderr)
    for p in profiles:
        print(f"  {p.name}", file=sys.stderr)
    sys.exit(2)


def _parse_blob_events(events_field) -> Iterable[str]:
    """Yield each event description string from a blob.events column.

    SQLite stores JSON-typed columns as TEXT; SQLAlchemy round-trips
    them to a list. Reading via raw sqlite3 returns the raw JSON text.
    """
    if not events_field:
        return []
    if isinstance(events_field, list):
        items = events_field
    else:
        try:
            items = json.loads(events_field)
        except (TypeError, ValueError):
            return []
    out: List[str] = []
    for item in items or []:
        if isinstance(item, dict):
            desc = item.get("description")
        else:
            desc = item
        if isinstance(desc, str) and desc.strip():
            out.append(desc.strip())
    return out


def _backfill(con: sqlite3.Connection, dry_run: bool = False) -> Tuple[int, int]:
    read_cur = con.cursor()

    # Pre-fetch known email + calendar event ids so we can drop links
    # to deleted rows without raising FK errors on insert.
    email_ids: Set[str] = {
        str(r[0])
        for r in read_cur.execute("SELECT id FROM emails")
        if r[0] is not None
    }
    event_ids: Set[str] = {
        str(r[0])
        for r in read_cur.execute("SELECT id FROM calendar_events")
        if r[0] is not None
    }
    print(
        f"  emails on disk:           {len(email_ids):>6}",
        file=sys.stderr,
    )
    print(
        f"  calendar_events on disk:  {len(event_ids):>6}",
        file=sys.stderr,
    )

    # Resolve calendar event id from a summary string (calendar
    # extraction puts the summary in the description, not the id).
    # Multiple events can share a summary; we link the blob to ALL
    # matching ids.
    summary_to_events: dict[str, List[str]] = {}
    for row in read_cur.execute(
        "SELECT id, summary FROM calendar_events WHERE summary IS NOT NULL"
    ):
        eid, summary = str(row[0]), str(row[1] or "")
        summary_to_events.setdefault(summary, []).append(eid)

    # Materialise the blob rows BEFORE iterating — re-using a cursor
    # for INSERTs while it streams a SELECT silently truncates the
    # iteration on SQLite.
    blob_rows = list(
        read_cur.execute("SELECT id, owner_id, events FROM blobs")
    )

    write_cur = con.cursor()
    n_email = 0
    n_calendar = 0
    skipped_unknown_email = 0
    skipped_unknown_calendar = 0

    for blob_id, owner_id, events_field in blob_rows:
        if not blob_id or not owner_id:
            continue
        blob_id = str(blob_id)
        owner_id = str(owner_id)
        for desc in _parse_blob_events(events_field):
            m_email = EMAIL_PATTERN.match(desc)
            if m_email:
                email_id = m_email.group(1).strip()
                if email_id not in email_ids:
                    skipped_unknown_email += 1
                    continue
                if not dry_run:
                    write_cur.execute(
                        "INSERT OR IGNORE INTO email_blobs "
                        "(email_id, blob_id, owner_id) VALUES (?, ?, ?)",
                        (email_id, blob_id, owner_id),
                    )
                    if write_cur.rowcount > 0:
                        n_email += 1
                else:
                    n_email += 1
                continue
            m_cal = CALENDAR_PATTERN.match(desc)
            if m_cal:
                summary = m_cal.group(1).strip()
                target_events = summary_to_events.get(summary, [])
                if not target_events:
                    skipped_unknown_calendar += 1
                    continue
                for eid in target_events:
                    if not dry_run:
                        write_cur.execute(
                            "INSERT OR IGNORE INTO calendar_blobs "
                            "(event_id, blob_id, owner_id) VALUES (?, ?, ?)",
                            (eid, blob_id, owner_id),
                        )
                        if write_cur.rowcount > 0:
                            n_calendar += 1
                    else:
                        n_calendar += 1

    if not dry_run:
        con.commit()

    print(
        f"  inserted email_blobs:        {n_email:>6}",
        file=sys.stderr,
    )
    print(
        f"  inserted calendar_blobs:     {n_calendar:>6}",
        file=sys.stderr,
    )
    if skipped_unknown_email:
        print(
            f"  skipped email links to deleted emails:    {skipped_unknown_email}",
            file=sys.stderr,
        )
    if skipped_unknown_calendar:
        print(
            f"  skipped calendar links (unknown summary): {skipped_unknown_calendar}",
            file=sys.stderr,
        )
    return n_email, n_calendar


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", help="profile dir name (email or UID)")
    ap.add_argument("--dry-run", action="store_true", help="don't write, just count")
    args = ap.parse_args(argv)

    profile_dir = _resolve_profile(args.profile)
    db = profile_dir / "zylch.db"
    if not db.exists():
        sys.exit(f"no zylch.db at {db}")
    print(f"Profile: {profile_dir.name}", file=sys.stderr)
    print(f"DB:      {db}", file=sys.stderr)

    con = sqlite3.connect(str(db))
    try:
        # Verify the new tables exist; if not, the engine hasn't been
        # restarted post-3.1 yet — running init-db creates them.
        cur = con.cursor()
        for table in ("email_blobs", "calendar_blobs"):
            row = cur.execute(
                f"SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if row is None:
                sys.exit(
                    f"table {table!r} missing — start the engine once to "
                    f"create it (init_db calls Base.metadata.create_all), "
                    f"then re-run this script."
                )
        n_email, n_calendar = _backfill(con, dry_run=args.dry_run)
    finally:
        con.close()
    print(
        f"\nDone. {'Would insert' if args.dry_run else 'Inserted'} "
        f"{n_email} email_blobs row(s) + {n_calendar} calendar_blobs row(s).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
