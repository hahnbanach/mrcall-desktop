#!/usr/bin/env python3
"""Re-key tasks that were keyed to a notification relay, not to a person.

Until the notifier fix, ``task_creation_email`` stamped
``contact_email = <envelope From>`` on every task it created. For mail
delivered by a relay — a MrCall call notification arrives from
``notification@transactional.mrcall.ai`` — that address is the
platform, not the caller. Every call-back task on a profile therefore
collapsed into ONE identity, which is what let the dedup sweeps merge
unrelated leads.

This script repairs the existing rows. For each open-or-closed task
whose ``contact_email`` is a recognised notifier address, it reads the
source email and lifts the caller's identity out of the notification
template, then rewrites the row into the shape the fixed pipeline
produces:

    contact_email  -> "" or the caller's address
    contact_phone  -> "+39…" or NULL
    contact_name   -> the caller's name when the template carries one
    channel        -> "phone"
    sources.notifier_email    -> the relay address that was there
    sources.contact_identity  -> "backfill_notification_template"

Only the identity LINE of the template is read — the line right after
``New Message from`` / ``No message call from``, mirrored in the
subject. It has exactly two machine-generated shapes:

    +393482337255                                  (a phone call)
    <firebase-uid>:<email>:<Full Name>             (a web/app caller)

Reading those is template parsing, not free-text extraction. The prose
fields further down the body ("Nome proprio del CHIAMANTE: …") are NOT
guessed at — a task whose identity line yields nothing is reported and
left untouched.

Idempotent: a row that already carries ``contact_phone`` is skipped, so
re-running changes nothing.

Usage:
    # dry run against a profile (default — prints counts, writes nothing)
    python scripts/backfill_notifier_task_contacts.py --profile <UID>

    # dry run against an explicit database file (e.g. a copy)
    python scripts/backfill_notifier_task_contacts.py --db /path/zylch.db

    # actually write
    python scripts/backfill_notifier_task_contacts.py --db /path/zylch.db --apply
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Optional

# Import the engine's notifier table so the script and the runtime
# recognise exactly the same senders.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from zylch.utils.notifier_senders import is_notifier_sender  # noqa: E402

PROFILE_ROOT = Path.home() / ".zylch" / "profiles"

# Fixed positions in the MrCall notification template. The identity
# line is the line right after the "… from" header:
#   body:    "New Message\nNew Message from\n+393482337255\n…"
#            "No Message IT 2.0\nNo message call from\n<uid>:<mail>:<name>\n…"
#   subject: "MrCall. <emoji>+393482337255  for <assistant name>"
#            "MrCall. <emoji><uid>:<mail>:<name>  for <assistant name>"
# Emitted by the notification service, never typed by a human.
_BODY_IDENTITY = re.compile(r"(?:New Message from|No message call from)\s*\n\s*(.+)", re.IGNORECASE)
# Subject fallback: everything between the leading "MrCall. " marker and
# the trailing "  for <assistant>" / " for <assistant>" suffix.
_SUBJECT_IDENTITY = re.compile(r"^MrCall\.\s*\W*(.+?)\s+for\s+\S", re.IGNORECASE | re.DOTALL)
# <firebase-uid>:<email>:<display name>
_UID_TRIPLE = re.compile(r"^([A-Za-z0-9]{20,}):([^:\s]+@[^:\s]+):(.*)$")


def _normalise_phone(raw: str) -> Optional[str]:
    """``+39 348 233 7255`` → ``+393482337255``. None when implausible."""
    if not raw:
        return None
    digits = re.sub(r"[^\d+]", "", raw)
    if not digits.startswith("+"):
        return None
    if len(digits) < 8 or len(digits) > 17:
        return None
    return digits


def _parse_identity_line(line: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """``(phone, email, name)`` from one notification identity line."""
    line = (line or "").strip()
    if not line:
        return None, None, None
    phone = _normalise_phone(line)
    if phone:
        return phone, None, None
    m = _UID_TRIPLE.match(line)
    if m:
        return None, m.group(2).strip().lower(), m.group(3).strip() or None
    return None, None, None


def caller_identity_from_notification(
    subject: str, body: str
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Lift ``(phone, email, name)`` out of a notification template."""
    m = _BODY_IDENTITY.search(body or "")
    if m:
        parsed = _parse_identity_line(m.group(1))
        if any(parsed):
            return parsed
    m = _SUBJECT_IDENTITY.match((subject or "").strip())
    if m:
        return _parse_identity_line(m.group(1))
    return None, None, None


def _resolve_db(profile: Optional[str], db: Optional[str]) -> Path:
    if db:
        path = Path(db).expanduser()
        if not path.is_file():
            sys.exit(f"database not found: {path}")
        return path
    if profile:
        path = PROFILE_ROOT / profile / "zylch.db"
        if not path.is_file():
            sys.exit(f"profile database not found: {path}")
        return path
    sys.exit("pass --profile <UID> or --db <path>")


def run(db_path: Path, apply: bool) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    stats = {
        "candidates": 0,
        "already_keyed": 0,
        "repaired": 0,
        "no_source_email": 0,
        "identity_not_found": 0,
    }
    try:
        rows = conn.execute(
            "SELECT id, contact_email, contact_phone, contact_name, channel, sources "
            "FROM task_items WHERE contact_email IS NOT NULL AND contact_email != ''"
        ).fetchall()

        updates = []
        for row in rows:
            if not is_notifier_sender(row["contact_email"]):
                continue
            stats["candidates"] += 1
            if (row["contact_phone"] or "").strip():
                stats["already_keyed"] += 1
                continue

            try:
                sources = json.loads(row["sources"]) if row["sources"] else {}
            except (TypeError, ValueError):
                sources = {}
            if not isinstance(sources, dict):
                sources = {}
            email_ids = [e for e in (sources.get("emails") or []) if e]
            if not email_ids:
                stats["no_source_email"] += 1
                print(f"  SKIP {row['id']}: no source email in sources.emails")
                continue

            placeholders = ",".join("?" * len(email_ids))
            mails = conn.execute(
                f"SELECT subject, body_plain, snippet FROM emails WHERE id IN ({placeholders})",
                email_ids,
            ).fetchall()
            phone = email = name = None
            for mail in mails:
                phone, email, name = caller_identity_from_notification(
                    mail["subject"] or "", mail["body_plain"] or mail["snippet"] or ""
                )
                if phone or email:
                    break
            if not (phone or email):
                stats["identity_not_found"] += 1
                print(f"  SKIP {row['id']}: no caller identity in the notification template")
                continue

            sources["notifier_email"] = row["contact_email"]
            sources["contact_identity"] = "backfill_notification_template"
            # The previous contact_name was the relay's display name
            # ("MrCall Notification"). It belongs to the platform, not to
            # the caller — drop it rather than carry it forward.
            updates.append(
                (
                    email or "",
                    phone,
                    name or "",
                    json.dumps(sources, ensure_ascii=False),
                    row["id"],
                )
            )
            stats["repaired"] += 1
            print(
                f"  FIX  {row['id']}: contact_email={row['contact_email']} "
                f"contact_name={row['contact_name']} -> "
                f"contact_email={email or '(empty)'} contact_phone={phone} "
                f"contact_name={name or '(empty)'}"
            )

        if apply and updates:
            conn.executemany(
                "UPDATE task_items SET contact_email = ?, contact_phone = ?, "
                "contact_name = ?, channel = 'phone', sources = ? WHERE id = ?",
                updates,
            )
            conn.commit()
    finally:
        conn.close()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", help="profile UID under ~/.zylch/profiles")
    parser.add_argument("--db", help="explicit path to a zylch.db (e.g. a copy)")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the changes (default: dry run, prints what it would do)",
    )
    args = parser.parse_args()

    db_path = _resolve_db(args.profile, args.db)
    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"[{mode}] {db_path}")
    stats = run(db_path, apply=args.apply)
    print(
        f"\ncandidates={stats['candidates']} "
        f"already_keyed={stats['already_keyed']} "
        f"repaired={stats['repaired']} "
        f"no_source_email={stats['no_source_email']} "
        f"identity_not_found={stats['identity_not_found']}"
    )
    if not args.apply and stats["repaired"]:
        print("(dry run — nothing written; re-run with --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
