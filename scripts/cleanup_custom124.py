"""Ripulisce i task Custom124 (merger) e prepara un re-processing pulito.

Cosa fa:
  1. Lista tutti i task aperti con contact_email = customer@example.com
     oppure contact_name contenente "custom124".
  2. (solo con --apply) li chiude con completed_at=now.
  3. (solo con --apply) resetta `task_processed_at=NULL` su tutte le email
     sorgenti che questi task riferivano nei loro `sources.emails`, così al
     prossimo `zylch update` — con la nuova USER_NOTES impostata in
     Settings — ogni lead viene ri-analizzato e ottiene un task dedicato.
  4. Stampa i blob "Custom124" in memoria (NON li tocca — li lascia lì,
     sono riusabili; se ti danno fastidio li elimini manualmente poi).

Uso:
  venv/bin/zylch -p <profile> run scripts/cleanup_custom124.py      # dry-run
  venv/bin/zylch -p <profile> run scripts/cleanup_custom124.py --apply

Oppure, se non c'è il subcomando `run` nel tuo CLI:
  ZYLCH_PROFILE=<profile> venv/bin/python scripts/cleanup_custom124.py --apply
"""
import argparse
import os
import sys
from datetime import datetime, timezone

# If the script is run directly with `python scripts/...`, activate the
# profile from env. The `zylch run` wrapper already sets it up.
if not os.environ.get("ZYLCH_PROFILE_DIR"):
    profile = os.environ.get("ZYLCH_PROFILE", "")
    if not profile:
        print("set ZYLCH_PROFILE or run via `zylch -p <email> run scripts/...`", file=sys.stderr)
        sys.exit(2)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from zylch.cli.profiles import activate_profile

    activate_profile(profile)

from zylch.storage.database import get_session  # noqa: E402
from zylch.storage.models import Blob, Email, TaskItem  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true", help="apply the changes (default: dry-run)")
    args = p.parse_args()

    with get_session() as s:
        tasks = (
            s.query(TaskItem)
            .filter(
                (TaskItem.contact_email == "customer@example.com")
                | (TaskItem.contact_name.ilike("%custom124%")),
                TaskItem.completed_at.is_(None),
            )
            .all()
        )
        print(f"=== Task Custom124 aperti: {len(tasks)} ===")
        email_ids_to_reset: set[str] = set()
        blob_ids_seen: set[str] = set()
        for t in tasks:
            src = t.sources or {}
            emails = src.get("emails", [])
            blobs = src.get("blobs", [])
            email_ids_to_reset.update(emails)
            blob_ids_seen.update(blobs)
            print(
                f"  {t.id[:8]}  urg={t.urgency:<8} emails={len(emails):<2} blobs={len(blobs):<2}"
                f"  reason={(t.reason or '')[:90]!r}"
            )

        if not tasks:
            print("Nothing to do.")
            return 0

        print()
        print(f"=== Email sorgenti referenziate: {len(email_ids_to_reset)} ===")
        if email_ids_to_reset:
            rows = s.query(Email).filter(Email.id.in_(email_ids_to_reset)).all()
            for e in rows[:50]:
                flag = "*" if e.task_processed_at else " "
                print(f"  {flag} {e.id[:8]} {e.date}  {(e.subject or '')[:70]!r}")
            if len(rows) > 50:
                print(f"  … +{len(rows) - 50} altre")

        print()
        print(f"=== Blob memoria referenziati: {len(blob_ids_seen)} ===")
        if blob_ids_seen:
            blobs = s.query(Blob).filter(Blob.id.in_(blob_ids_seen)).all()
            for b in blobs[:20]:
                summary = (getattr(b, "summary", None) or getattr(b, "content", None) or "")[:80]
                print(f"  {b.id[:8]}  {summary!r}")
            if len(blobs) > 20:
                print(f"  … +{len(blobs) - 20} altri")

        if not args.apply:
            print()
            print(">>> DRY-RUN. Aggiungi --apply per chiudere i task e resettare task_processed_at.")
            return 0

        # --- apply ---
        now = datetime.now(timezone.utc)
        for t in tasks:
            t.completed_at = now
        print()
        print(f"[apply] chiusi {len(tasks)} task")

        if email_ids_to_reset:
            affected = (
                s.query(Email)
                .filter(Email.id.in_(email_ids_to_reset))
                .update({Email.task_processed_at: None}, synchronize_session=False)
            )
            print(f"[apply] resettato task_processed_at su {affected} email")

        s.commit()
        print()
        print("Done. Ora:")
        print("  1. Vai in Settings e salva la USER_NOTES che specifica la regola Custom124.")
        print("  2. Torna in Task e clicca Update now.")
        print("  3. Verifica che ogni lead (KOUBS, Jungle, …) ora abbia un task distinto.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
