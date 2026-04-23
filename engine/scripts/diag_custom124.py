"""Diagnostic: cosa c'è nel DB per Custom124 DOPO cleanup + update.

Uso:
  ZYLCH_PROFILE=mario.alemi@cafe124.it venv/bin/python scripts/diag_custom124.py

Non modifica nulla, solo stampa.
"""
import os
import sys

if not os.environ.get("ZYLCH_PROFILE_DIR"):
    profile = os.environ.get("ZYLCH_PROFILE", "")
    if not profile:
        print("set ZYLCH_PROFILE", file=sys.stderr)
        sys.exit(2)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from zylch.cli.profiles import activate_profile

    activate_profile(profile)

from zylch.storage.database import get_session  # noqa: E402
from zylch.storage.models import Email, TaskItem  # noqa: E402


def main() -> int:
    with get_session() as s:
        total = s.query(Email).count()
        unproc_all = s.query(Email).filter(Email.task_processed_at.is_(None)).count()
        unproc_c124 = (
            s.query(Email)
            .filter(
                Email.task_processed_at.is_(None),
                Email.from_email == "production@custom124.com",
            )
            .count()
        )
        proc_c124 = (
            s.query(Email)
            .filter(
                Email.task_processed_at.isnot(None),
                Email.from_email == "production@custom124.com",
            )
            .count()
        )
        closed = (
            s.query(TaskItem)
            .filter(
                TaskItem.contact_email == "production@custom124.com",
                TaskItem.completed_at.isnot(None),
            )
            .count()
        )
        open_ = (
            s.query(TaskItem)
            .filter(
                TaskItem.contact_email == "production@custom124.com",
                TaskItem.completed_at.is_(None),
            )
            .count()
        )

        print("=== EMAILS ===")
        print(f"  total:                    {total}")
        print(f"  unprocessed (all):        {unproc_all}")
        print(f"  unprocessed (Custom124):  {unproc_c124}")
        print(f"  processed   (Custom124):  {proc_c124}")
        print()
        print("=== TASKS Custom124 ===")
        print(f"  open:   {open_}")
        print(f"  closed: {closed}")
        print()
        print("=== Sample Custom124 emails (any state) ===")
        rows = (
            s.query(Email)
            .filter(Email.from_email == "production@custom124.com")
            .order_by(Email.date.desc())
            .limit(15)
            .all()
        )
        for e in rows:
            tp = "PROC" if e.task_processed_at else "NEW "
            print(f"  [{tp}] {e.id[:8]} {e.date}  {(e.subject or '')[:70]}")
        print()
        print("=== Most recent open tasks (top 10) ===")
        for t in (
            s.query(TaskItem)
            .filter(TaskItem.completed_at.is_(None))
            .order_by(TaskItem.created_at.desc())
            .limit(10)
            .all()
        ):
            print(
                f"  {t.id[:8]} {t.urgency:<8} {t.contact_email or '—':<40}"
                f" {(t.reason or '')[:60]!r}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
