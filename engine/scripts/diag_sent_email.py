"""Quick diagnostic for the "user-sent emails are not seen" bug.

Run with the SAME profile env the Electron sidecar uses, e.g.:

    cd engine
    ZYLCH_DB_PATH=~/.zylch/profiles/<UID>/zylch.db \
    EMAIL_ADDRESS=$(grep ^EMAIL_ADDRESS ~/.zylch/profiles/<UID>/.env | cut -d= -f2- | tr -d '"') \
    venv/bin/python -m scripts.diag_sent_email

Or, easier — just run the active sidecar binary with ``rpc`` swapped out.

Outputs three sections:

 1. ENV — whether the sidecar's EMAIL_ADDRESS is what we expect.
 2. RECENT MAIL — last 20 emails with from/to/subject/thread_id/
    date/date_timestamp/task_processed_at + whether they look like a
    user-sent based on lower(from_email) == lower(EMAIL_ADDRESS).
 3. OPEN TASKS — for each open action_required task, the resolved
    thread_id (via sources.thread_id or sources.emails[0] → Email.thread_id)
    + whether ANY user-sent email exists on that thread (the close path
    in _analyze_recent_events.user_reply only fires when there is one).

Goal: prove or refute each of these mutually-exclusive scenarios:

  A. Sent mail not in DB  (IMAP Sent folder not synced).
  B. Sent mail in DB but `from_email` does not match EMAIL_ADDRESS
     (case / alias / wrong env).
  C. Sent mail in DB matching EMAIL_ADDRESS but thread_id ≠ task's
     thread (References header missing on send → thread split).
  D. Sent mail in DB matching, thread_id matches, but `task_processed_at
     IS NOT NULL` already (consumed in a previous run that didn't close).

No writes, read-only. Safe to run on production data.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone


def main() -> int:
    db_path = os.environ.get("ZYLCH_DB_PATH") or os.path.expanduser(
        "~/.zylch/zylch.db"
    )
    if not os.path.isfile(db_path):
        print(f"[diag] DB not found: {db_path}")
        print("[diag] Set ZYLCH_DB_PATH to the profile DB path.")
        return 2

    user_email = (os.environ.get("EMAIL_ADDRESS") or "").strip()
    print("=" * 70)
    print("ENV")
    print("=" * 70)
    print(f"  ZYLCH_DB_PATH    = {db_path}")
    print(f"  EMAIL_ADDRESS    = {user_email!r}")
    if not user_email:
        print(
            "  WARNING: EMAIL_ADDRESS is empty — the task worker treats "
            "every sent email as 'not user', so user_reply close logic "
            "never fires. This alone explains the symptom."
        )
    me = user_email.lower()

    import sqlite3
    import json

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    # ---- RECENT MAIL ----
    print()
    print("=" * 70)
    print("RECENT MAIL (last 20, newest first)")
    print("=" * 70)
    rows = conn.execute(
        """
        SELECT id, from_email, to_email, cc_email, subject, thread_id,
               date, date_timestamp, task_processed_at, message_id_header
        FROM emails
        WHERE owner_id = (SELECT owner_id FROM emails ORDER BY date_timestamp DESC LIMIT 1)
        ORDER BY date_timestamp DESC
        LIMIT 20
        """
    ).fetchall()
    for r in rows:
        from_e = (r["from_email"] or "").strip()
        is_user = bool(me) and from_e.lower() == me
        flag = "USER" if is_user else "    "
        ts = r["date_timestamp"]
        try:
            ts_iso = (
                datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")
                if ts
                else "(no ts)"
            )
        except Exception:
            ts_iso = f"(bad ts: {ts!r})"
        print(
            f"  [{flag}] id={r['id'][:8]} ts={ts} ({ts_iso}) "
            f"task_proc={'NULL' if r['task_processed_at'] is None else 'SET'} "
            f"thread={(r['thread_id'] or '')[:40]!r}"
        )
        print(
            f"         from={from_e!r:40s} to={(r['to_email'] or '')[:40]!r}"
        )
        print(
            f"         subj={(r['subject'] or '')[:60]!r}"
        )
        print(
            f"         msgid={(r['message_id_header'] or '')[:60]!r}"
        )
    if not rows:
        print("  (no rows)")

    # ---- OPEN TASKS ----
    print()
    print("=" * 70)
    print("OPEN TASKS (action_required, not completed)")
    print("=" * 70)
    tasks = conn.execute(
        """
        SELECT id, contact_email, contact_name, urgency, suggested_action,
               sources, analyzed_at, created_at, owner_id
        FROM task_items
        WHERE completed_at IS NULL AND action_required = 1
        ORDER BY analyzed_at DESC
        """
    ).fetchall()
    if not tasks:
        print("  (no open action_required tasks)")
    for t in tasks:
        try:
            sources = json.loads(t["sources"]) if t["sources"] else {}
        except Exception:
            sources = {}
        primary_thread = sources.get("thread_id")
        if not primary_thread:
            emails = sources.get("emails") or []
            if emails:
                row = conn.execute(
                    "SELECT thread_id FROM emails WHERE owner_id = ? AND id = ?",
                    (t["owner_id"], emails[0]),
                ).fetchone()
                if row:
                    primary_thread = row["thread_id"]
        primary_thread = primary_thread or ""
        sent_count = 0
        any_sent_subj = ""
        if primary_thread and me:
            sr = conn.execute(
                """
                SELECT COUNT(*) AS n,
                       MAX(subject) AS subj
                FROM emails
                WHERE owner_id = ?
                  AND thread_id = ?
                  AND lower(from_email) = ?
                """,
                (t["owner_id"], primary_thread, me),
            ).fetchone()
            sent_count = int(sr["n"] or 0)
            any_sent_subj = (sr["subj"] or "")[:60]
        print(
            f"  task={t['id'][:8]} contact={t['contact_email']!r:40s} "
            f"urgency={t['urgency']}"
        )
        print(
            f"        thread={primary_thread[:60]!r} "
            f"sent_in_thread={sent_count} ({any_sent_subj!r})"
        )
        print(
            f"        action={(t['suggested_action'] or '')[:80]!r}"
        )

    print()
    print("=" * 70)
    print("HOW TO READ THIS")
    print("=" * 70)
    print(
        "  - If 'EMAIL_ADDRESS' is empty/wrong  → fix the profile .env. "
        "Without it, NO sent mail is classified as user_reply.\n"
        "  - If a task has sent_in_thread=0 but you DID reply         → "
        "sent mail is missing OR is on a different thread_id (References "
        "header dropped by the MUA).\n"
        "  - If a task has sent_in_thread>0 but the task is still open → "
        "the user_reply close path didn't fire. Check the corresponding "
        "row in RECENT MAIL: it should have task_proc=NULL the first run "
        "and SET after the run that should have closed.\n"
        "  - If RECENT MAIL has no [USER] flagged row at all           → "
        "either the IMAP Sent folder isn't synced (check sidecar logs "
        "for '[IMAP] Found Sent folder') or from_email mismatches "
        "EMAIL_ADDRESS (case, alias)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
