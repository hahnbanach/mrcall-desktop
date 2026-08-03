"""Who does a task belong to when the mail came through a relay?

A MrCall call notification arrives from
``notification@transactional.mrcall.ai``. That address is the platform,
not the person who needs a call back. Before the notifier fix every
call-back task on a profile carried it as ``contact_email``, so N
distinct callers collapsed into ONE identity — and an identity is
exactly what the dedup sweeps use to decide two tasks may be merged.

This locks the two halves of the repair, on a real tmp SQLite store:

- creation time: :func:`resolve_contact_identity` re-keys the task to
  the caller the detector read out of the body, and records the relay in
  ``sources`` so the substitution is never silent;
- dedup time: :func:`task_identity_key` refuses to identify a task whose
  only handle is a notifier address, so two unrelated leads can never be
  proven to be "the same party".

Expected shape mirrors ``scripts/backfill_notifier_task_contacts.py``,
which repairs the rows written before the fix.
"""

import pytest

from zylch.utils.notifier_senders import is_notifier_sender
from zylch.workers.task_contact_identity import (
    resolve_contact_identity,
    task_identity_key,
)

NOTIFIER = "notification@transactional.mrcall.ai"
OWNER = "owner-uid-notifier"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "notifier.db"))
    from zylch.storage import database as db_mod
    from zylch.storage.storage import Storage

    db_mod.dispose_engine()
    db_mod.init_db()
    yield Storage()
    db_mod.dispose_engine()


def _task(event_id: str, identity) -> dict:
    """A stored task in the shape the fixed pipeline writes."""
    return {
        "event_type": "email",
        "event_id": event_id,
        "contact_email": identity.email,
        "contact_phone": identity.phone,
        "contact_name": identity.name,
        "title": "Richiamare il cliente",
        "action_required": True,
        "urgency": "high",
        "sources": identity.apply_to_sources({"emails": [event_id]}),
    }


def test_notifier_task_is_rekeyed_to_the_caller_and_keeps_the_relay_on_record(store):
    """The task belongs to the caller; the relay survives only as provenance."""
    identity = resolve_contact_identity(
        from_email=NOTIFIER,
        from_name="MrCall Notification",
        decision={"contact_phone": "+393482337255", "contact_name": "Giulia Bianchi"},
    )

    assert identity.phone == "+393482337255"
    assert identity.name == "Giulia Bianchi"
    assert identity.notifier_email == NOTIFIER
    assert identity.resolved_from_body is True

    assert store.store_task_item(OWNER, _task("<call-1@mrcall>", identity)) is True
    row = store.get_task_by_event(owner_id=OWNER, event_type="email", event_id="<call-1@mrcall>")

    assert row["contact_phone"] == "+393482337255"
    assert not is_notifier_sender(row["contact_email"])
    assert row["sources"]["notifier_email"] == NOTIFIER
    assert row["sources"]["contact_identity"] == "extracted_from_body"
    # The relay is a phone-call notification, so the task is a phone task.
    assert row["channel"] == "phone"
    assert task_identity_key(row) == "phone:+393482337255"


def test_two_callers_behind_the_same_relay_are_two_identities(store):
    """The collapse that let dedup merge unrelated leads must be impossible."""
    rows = []
    for event_id, phone, name in (
        ("<call-a@mrcall>", "+393482337255", "Giulia Bianchi"),
        ("<call-b@mrcall>", "+393480000002", "Luca Verdi"),
    ):
        identity = resolve_contact_identity(
            from_email=NOTIFIER,
            from_name="MrCall Notification",
            decision={"contact_phone": phone, "contact_name": name},
        )
        store.store_task_item(OWNER, _task(event_id, identity))
        rows.append(store.get_task_by_event(owner_id=OWNER, event_type="email", event_id=event_id))

    keys = {task_identity_key(row) for row in rows}
    assert keys == {"phone:+393482337255", "phone:+393480000002"}


def test_a_task_left_on_the_relay_address_reports_no_identity_at_all(store):
    """No caller in the body: keep a handle, but never claim to know who it is."""
    identity = resolve_contact_identity(
        from_email=NOTIFIER, from_name="MrCall Notification", decision={}
    )

    assert identity.email == NOTIFIER, "the task still needs a handle"
    assert identity.resolved_from_body is False

    store.store_task_item(OWNER, _task("<call-unknown@mrcall>", identity))
    row = store.get_task_by_event(
        owner_id=OWNER, event_type="email", event_id="<call-unknown@mrcall>"
    )

    assert row["sources"]["contact_identity"] == "notifier_envelope_fallback"
    assert task_identity_key(row) is None, "a relay address is not an identity"


def test_an_ordinary_correspondent_is_never_repointed_by_the_detector(store):
    """The envelope wins outside the relay case — the model cannot redirect a task."""
    identity = resolve_contact_identity(
        from_email="Cliente@Example.com",
        from_name="Mario Rossi",
        decision={"contact_email": "attacker@example.net", "contact_phone": "+390000000000"},
    )

    assert identity.email == "cliente@example.com"
    assert identity.phone is None
    assert identity.notifier_email is None

    store.store_task_item(OWNER, _task("<plain-1@example.com>", identity))
    row = store.get_task_by_event(
        owner_id=OWNER, event_type="email", event_id="<plain-1@example.com>"
    )

    assert row["contact_email"] == "cliente@example.com"
    assert "notifier_email" not in row["sources"]
    assert task_identity_key(row) == "email:cliente@example.com"
