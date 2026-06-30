"""Semantic verification of the task-creation SPAM / export-scam filter.

After deploying the meta-prompt patch (``agents/trainers/task_email.py``) AND
retraining the profile (``cs rpc agents.train_all`` / the "Train assistant"
button), run this ON THE HOST with the profile's env to prove the trained task
agent now:

  - rejects unsolicited "send your catalogue" / vague import scams  -> NO_ACTION
  - STILL creates tasks for real B2B leads + real support issues    -> action

It calls the REAL analyzer (``TaskWorker._analyze_event``), so it exercises the
profile's actual trained ``task_email`` prompt (and uses LLM credit). Read-only:
the emails are SYNTHETIC and are never written to the DB.

Run (engine venv + profile env), e.g.:

    cd engine
    ZYLCH_DB_PATH=~/.zylch/profiles/<UID>/zylch.db \
    EMAIL_ADDRESS=$(grep ^EMAIL_ADDRESS ~/.zylch/profiles/<UID>/.env | cut -d= -f2- | tr -d '"') \
    ZYLCH_OWNER_ID=<UID> \
    venv/bin/python -m scripts.verify_task_spam_filter

Exit 0 = all cases passed; 1 = at least one regression; 2 = setup problem
(no trained prompt / owner_id unresolved).
"""

from __future__ import annotations

import asyncio
import os
import sys

# Each case = a synthetic FIRST-CONTACT email + the expected outcome.
# kind="bait"  -> the agent must NOT create a task (export/advance-fee scam).
# kind="legit" -> the agent MUST create/update a task (don't break real leads).
CASES = [
    {
        "label": "vague 'send catalogue', unknown gmail, no specifics",
        "kind": "bait",
        "email": {
            "from_email": "folson.terfah@gmail.com",
            "from_name": "Folson Terfah",
            "subject": "Catalog Request",
            "body": (
                "Dear Sir/Madam, We are interested in your products. Kindly send "
                "us your catalogue and price list. We look forward to doing "
                "business with you. Best regards, Folson Terfah."
            ),
        },
    },
    {
        "label": "generic 'we want to import/distribute', yahoo",
        "kind": "bait",
        "email": {
            "from_email": "almaar.export@yahoo.com",
            "from_name": "William Paul",
            "subject": "Import inquiry",
            "body": (
                "Hello, We want to import and distribute your beverages in our "
                "country. Please send your company profile and FOB prices. "
                "Regards, William Paul, Almaar Export."
            ),
        },
    },
    {
        "label": "'send proforma + bank details', hotmail",
        "kind": "bait",
        "email": {
            "from_email": "buyer2026@hotmail.com",
            "from_name": "Buyer",
            "subject": "Purchase order",
            "body": (
                "Good day, We wish to purchase your products. Please send your "
                "proforma invoice and bank account details so we can proceed "
                "with payment. Thanks."
            ),
        },
    },
    {
        "label": "named company + product + quantity (real B2B lead)",
        "kind": "legit",
        "email": {
            "from_email": "acquisti@bericacaffe.com",
            "from_name": "Alessandro Berica",
            "subject": "Richiesta preventivo cold brew private label",
            "body": (
                "Buongiorno, siamo Berica Caffe Srl, distributori per il vending "
                "in Veneto. Vorremmo un preventivo per 20 casse da 24 lattine di "
                "cold brew 250ml a nostro marchio. Possiamo sentirci per i "
                "dettagli? Grazie, Alessandro."
            ),
        },
    },
    {
        "label": "real support issue (incomplete order)",
        "kind": "legit",
        "email": {
            "from_email": "marco.cliente@gmail.com",
            "from_name": "Marco",
            "subject": "Ordine incompleto",
            "body": (
                "Salve, ho ordinato 3 confezioni sul vostro sito (ordine #1234) "
                "ma me ne e arrivata solo una. Come possiamo risolvere? Grazie, Marco."
            ),
        },
    },
]


def _resolve_owner_id() -> str:
    oid = os.environ.get("ZYLCH_OWNER_ID")
    if oid:
        return oid
    try:
        from zylch.cli.utils import get_owner_id

        return get_owner_id()
    except Exception as e:  # pragma: no cover - host setup
        print(
            f"[verify] cannot resolve owner_id ({e}). Set ZYLCH_OWNER_ID=<profile uid>.",
            file=sys.stderr,
        )
        raise SystemExit(2)


async def _run() -> int:
    from zylch.storage import Storage
    from zylch.workers.task_creation import TaskWorker

    owner_id = _resolve_owner_id()
    user_email = (os.environ.get("EMAIL_ADDRESS") or "").strip()
    worker = TaskWorker(Storage(), owner_id, user_email)

    if not worker.has_task_prompt():
        print(
            "[verify] no trained task_email prompt for this profile — run "
            "`cs rpc agents.train_all` (or the 'Train assistant' button) first.",
            file=sys.stderr,
        )
        return 2

    print("=" * 78)
    print(f"VERIFY task spam-filter — owner={owner_id} user={user_email!r}")
    print("=" * 78)

    failures = 0
    for c in CASES:
        em = c["email"]
        event_data = {
            "id": "verify-synthetic",
            "from_email": em["from_email"],
            "from_name": em.get("from_name", ""),
            "to_email": user_email or "production@cafe124.it",
            "subject": em["subject"],
            "date": os.environ.get("VERIFY_DATE", ""),
            "body": em["body"],
            "thread_id": None,
        }
        result = await worker._analyze_event("email", event_data, "(no prior context)", "")
        action = (result or {}).get("task_action", "none")
        req = bool((result or {}).get("action_required", False))
        creates = action in ("create", "update") and req
        ok = (not creates) if c["kind"] == "bait" else creates
        failures += 0 if ok else 1

        print(f"\n[{'PASS' if ok else 'FAIL'}] {c['kind'].upper():5} — {c['label']}")
        print(f"       from={em['from_email']}  subj={em['subject']!r}")
        print(
            f"       -> task_action={action!r} action_required={req} "
            f"urgency={(result or {}).get('urgency')!r}"
        )
        reason = (result or {}).get("reason", "")
        if reason:
            print(f"       reason: {reason[:160]}")

    print("\n" + "=" * 78)
    print(
        f"RESULT: {'ALL PASS' if failures == 0 else str(failures) + ' FAILURE(S)'} "
        f"({len(CASES)} cases)"
    )
    print("=" * 78)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
