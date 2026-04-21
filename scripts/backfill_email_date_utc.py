"""Backfill `emails.date` from `emails.date_timestamp`.

Historical bug (fixed in 0.1.24): the RFC2822 parser stripped the tz offset
instead of converting to UTC, so the `date` column stored the sender-timezone
wall-clock as if it were UTC. The companion column `date_timestamp` is a
correct UTC epoch (computed via `datetime.timestamp()` which honors tzinfo),
so we can rebuild `date` from it without touching IMAP.

Usage:
    # Single profile, dry-run (default):
    ZYLCH_PROFILE=support@mrcall.ai venv/bin/python scripts/backfill_email_date_utc.py

    # Single profile, apply changes:
    ZYLCH_PROFILE=support@mrcall.ai venv/bin/python scripts/backfill_email_date_utc.py --apply

    # All profiles found under ~/.zylch/profiles/:
    venv/bin/python scripts/backfill_email_date_utc.py --all
    venv/bin/python scripts/backfill_email_date_utc.py --all --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _activate(profile: str) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from zylch.cli.profiles import activate_profile  # noqa: E402

    activate_profile(profile)


def _backfill_current_profile(apply: bool) -> dict:
    """Run the backfill against the currently-activated profile DB.

    Returns:
        Dict with keys: total, already_correct, would_fix, sample (list of
        (gmail_id, old_date, new_date) tuples for the first 5 changes).
    """
    from zylch.storage.database import get_session  # noqa: E402
    from zylch.storage.models import Email  # noqa: E402

    sample: list[tuple[str, str, str]] = []
    total = 0
    already_correct = 0
    would_fix = 0

    with get_session() as session:
        rows = session.query(Email).filter(Email.date_timestamp.isnot(None)).all()
        for row in rows:
            total += 1
            correct = datetime.fromtimestamp(row.date_timestamp, tz=timezone.utc).replace(
                tzinfo=None
            )
            current = row.date
            if current is not None and current.replace(microsecond=0) == correct.replace(
                microsecond=0
            ):
                already_correct += 1
                continue
            would_fix += 1
            if len(sample) < 5:
                sample.append(
                    (
                        row.gmail_id,
                        current.isoformat() if current else "NULL",
                        correct.isoformat(),
                    )
                )
            if apply:
                row.date = correct

        if apply:
            session.commit()

    return {
        "total": total,
        "already_correct": already_correct,
        "would_fix": would_fix,
        "sample": sample,
    }


def _list_profiles() -> list[str]:
    profiles_dir = Path.home() / ".zylch" / "profiles"
    if not profiles_dir.exists():
        return []
    return sorted(p.name for p in profiles_dir.iterdir() if p.is_dir())


def _run(profile: str, apply: bool) -> None:
    _activate(profile)
    result = _backfill_current_profile(apply=apply)
    verb = "FIXED" if apply else "would fix"
    print(f"--- profile: {profile} ---")
    print(f"  total rows with date_timestamp: {result['total']}")
    print(f"  already correct:                {result['already_correct']}")
    print(f"  {verb}:                         {result['would_fix']}")
    if result["sample"]:
        label = "changes (showing up to 5)" if apply else "preview (showing up to 5)"
        print(f"  {label}:")
        for gmail_id, old, new in result["sample"]:
            print(f"    {gmail_id}")
            print(f"      before: {old}")
            print(f"      after:  {new}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    ap.add_argument(
        "--all", action="store_true", help="Iterate every profile under ~/.zylch/profiles/"
    )
    args = ap.parse_args()

    if args.all:
        # Spawn a subprocess per profile — activate_profile mutates process-global
        # SQLAlchemy engine state, so multiple profiles in one process read the
        # same DB after the first activation.
        import subprocess

        profiles = _list_profiles()
        if not profiles:
            print("No profiles found in ~/.zylch/profiles/", file=sys.stderr)
            return 1
        cmd_tail = ["--apply"] if args.apply else []
        for profile in profiles:
            env = {**os.environ, "ZYLCH_PROFILE": profile}
            subprocess.run([sys.executable, __file__, *cmd_tail], env=env, check=True)
        if not args.apply:
            print("DRY-RUN. Re-run with --apply to write changes.")
        return 0

    env_profile = os.environ.get("ZYLCH_PROFILE", "")
    if not env_profile:
        print(
            "Set ZYLCH_PROFILE=<email> or pass --all",
            file=sys.stderr,
        )
        return 2

    _run(env_profile, apply=args.apply)
    print()
    if not args.apply:
        print("DRY-RUN. Re-run with --apply to write changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
