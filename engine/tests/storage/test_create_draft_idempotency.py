"""`create_draft` returns the identical draft instead of writing a second one.

A chat turn whose caller has gone away still runs to completion and still
commits its draft. When the re-run produces the same mail, the mailbox ended
up holding two approvable copies of it and approving the second one mailed the
customer twice.

What "identical" means is the whole design here. Recipients arrive in two
shapes — the chat `create_draft` tool hands over the model's raw `to` string,
`crm_tools` hands over a list — so they are normalized before comparison. And
subject, cc, bcc and attachments are part of the identity: the caller prints
its own subject and body next to the id it gets back, so returning a row that
differs in any of them would hand the operator an id pointing at a different
mail. So are `in_reply_to` and `references`, which decide where the mail
lands: on a fresh compose `thread_id` is NULL, and they are then the only
thing telling two same-bodied replies apart.

Runs against a real temp SQLite DB — no mocks at all.
"""

from datetime import datetime, timedelta, timezone

import pytest

OWNER = "owner-draft-idempotency-test"
OTHER_OWNER = "owner-draft-idempotency-other"

SUBJECT = "Re: your request"
BODY = "Hello,\n\nHere is the answer.\n\nBest regards"
TO = "customer@example.com"


@pytest.fixture
def storage(tmp_path, monkeypatch):
    db_path = tmp_path / "create_draft_idempotency.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))
    from zylch.storage import database as db_mod
    from zylch.storage.storage import Storage

    db_mod.dispose_engine()
    db_mod.init_db()
    yield Storage()
    db_mod.dispose_engine()


def _create(storage, **overrides):
    kwargs = {
        "owner_id": OWNER,
        "to": TO,
        "subject": SUBJECT,
        "body": BODY,
    }
    kwargs.update(overrides)
    return storage.create_draft(**kwargs)


def _rows(storage, owner_id=OWNER):
    return storage.list_drafts(owner_id)


# ------------------------------------------------------------- the same mail


def test_the_same_draft_twice_is_one_row(storage):
    first = _create(storage)
    second = _create(storage)

    assert second["id"] == first["id"]
    assert len(_rows(storage)) == 1


def test_a_reuse_stamps_updated_at(storage):
    """The only channel an out-of-process caller has for the reuse.

    `cs draft-reply` diffs the ids in `drafts.list` around the turn; a reused
    row adds no id, so without a moved `updated_at` a composed reply reads as
    "the engine composed nothing" and is never mirrored."""
    first = _create(storage)
    before = storage.get_draft(OWNER, first["id"])["updated_at"]

    second = _create(storage)
    after = storage.get_draft(OWNER, second["id"])["updated_at"]

    assert second["id"] == first["id"]
    assert after > before
    assert second["updated_at"] == after


def test_the_caller_is_told_which_of_the_two_happened(storage):
    """`cs draft-reply` diffs `drafts.list` around the turn: without this flag
    a reused id reads as "the engine composed no new draft — nothing to
    mirror", and a reply that was asked for is silently dropped."""
    first = _create(storage)
    second = _create(storage)

    assert first["created"] is True
    assert second["created"] is False


# ------------------------------------------ every field of the identity


@pytest.mark.parametrize(
    "field,value",
    [
        ("subject", "A different subject"),
        ("body", "A different body"),
        ("to", "someone.else@example.com"),
        ("thread_id", "thread-xyz"),
        ("cc", ["boss@example.com"]),
        ("bcc", ["archive@example.com"]),
        ("in_reply_to", "<other-message@example.com>"),
        ("references", ["<root@example.com>", "<other@example.com>"]),
    ],
)
def test_a_difference_in_any_identity_field_makes_a_new_draft(storage, field, value):
    first = _create(storage)
    second = _create(storage, **{field: value})

    assert second["id"] != first["id"], f"{field} must be part of the identity"
    assert second["created"] is True
    assert len(_rows(storage)) == 2


def test_a_difference_in_attachments_makes_a_new_draft(storage, tmp_path):
    attachment = tmp_path / "quote.pdf"
    attachment.write_bytes(b"%PDF-1.4\n")

    first = _create(storage)
    second = _create(storage, attachment_paths=[str(attachment)])

    assert second["id"] != first["id"]
    assert len(_rows(storage)) == 2

    # And the same attachment set still deduplicates.
    third = _create(storage, attachment_paths=[str(attachment)])
    assert third["id"] == second["id"]
    assert len(_rows(storage)) == 2


def test_two_replies_to_different_messages_of_one_thread_stay_apart(storage):
    """The threading headers decide WHERE the mail lands.

    A short body ("Grazie!", "Ricevuto") repeats naturally on a busy thread.
    Without `in_reply_to` in the identity the second reply gets the first
    one's id back, and the answer is then threaded under the wrong parent.
    """
    first = _create(
        storage,
        body="Ricevuto, grazie.",
        thread_id="thread-1",
        in_reply_to="<msg-1@example.com>",
        references=["<msg-1@example.com>"],
    )
    second = _create(
        storage,
        body="Ricevuto, grazie.",
        thread_id="thread-1",
        in_reply_to="<msg-2@example.com>",
        references=["<msg-1@example.com>", "<msg-2@example.com>"],
    )

    assert second["id"] != first["id"]
    assert len(_rows(storage)) == 2


def test_the_same_reply_recomposed_still_collapses(storage):
    """Nothing is lost by keying on the headers: an orphaned turn that
    re-runs re-derives the SAME `in_reply_to`, so the duplicate this whole
    mechanism exists to catch still collapses."""
    first = _create(
        storage,
        thread_id="thread-1",
        in_reply_to="<msg-1@example.com>",
        references=["<msg-1@example.com>"],
    )
    second = _create(
        storage,
        thread_id="thread-1",
        in_reply_to="<msg-1@example.com>",
        references=["<msg-1@example.com>"],
    )

    assert second["id"] == first["id"]
    assert second["created"] is False


def test_without_a_thread_the_headers_are_the_only_discriminator(storage):
    """`thread_id` is NULL on a fresh compose, which is the normal case."""
    first = _create(storage, in_reply_to="<msg-1@example.com>")
    second = _create(storage, in_reply_to="<msg-2@example.com>")

    assert second["id"] != first["id"]
    assert len(_rows(storage)) == 2


def test_another_owner_never_matches(storage):
    first = _create(storage)
    second = _create(storage, owner_id=OTHER_OWNER)

    assert second["id"] != first["id"]
    assert len(_rows(storage)) == 1
    assert len(_rows(storage, OTHER_OWNER)) == 1


# ---------------------------------------------------- recipient normalization


def test_the_string_and_the_list_shape_collapse_to_one_draft(storage):
    """`gmail_tools` passes the model's raw `to` string, `crm_tools` a list."""
    from_gmail_tools = _create(storage, to="Customer@Example.com")
    from_crm_tools = _create(storage, to=["customer@example.com"])

    assert from_crm_tools["id"] == from_gmail_tools["id"]
    assert len(_rows(storage)) == 1


def test_multiple_recipients_match_whatever_shape_they_arrive_in(storage):
    """One comma-joined string and the equivalent list are the same mail."""
    joined = _create(storage, to="a@example.com, b@example.com")
    listed = _create(storage, to=["B@example.com", "a@example.com"])

    assert listed["id"] == joined["id"]
    assert len(_rows(storage)) == 1


def test_cc_normalization_matches_the_recipient_rule(storage):
    joined = _create(storage, cc=["one@example.com, two@example.com"])
    listed = _create(storage, cc=["TWO@example.com", "one@example.com"])

    assert listed["id"] == joined["id"]
    assert len(_rows(storage)) == 1


# ----------------------------------------------------------- status and window


def test_a_sent_draft_never_matches(storage):
    """A deliberate second mail on an answered thread must get a NEW draft.
    Returning the earlier, now `sent` row hands back an id every send path
    refuses — an unsendable answer instead of a draft."""
    first = _create(storage)
    storage.mark_draft_sent(OWNER, first["id"], "message-id-1")

    second = _create(storage)

    assert second["id"] != first["id"]
    assert second["created"] is True
    assert storage.get_draft(OWNER, second["id"])["status"] == "draft"


def test_a_draft_being_sent_never_matches(storage):
    first = _create(storage)
    assert storage.claim_draft_for_send(OWNER, first["id"]) is True

    second = _create(storage)

    assert second["id"] != first["id"]


def test_an_older_identical_draft_is_outside_the_window(storage):
    from zylch.storage.storage import DRAFT_DEDUP_WINDOW_HOURS

    first = _create(storage)
    stale = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        hours=DRAFT_DEDUP_WINDOW_HOURS, minutes=1
    )
    storage.update_draft(OWNER, first["id"], {"created_at": stale})

    second = _create(storage)

    assert second["id"] != first["id"]
    assert len(_rows(storage)) == 2


def test_just_inside_the_window_still_deduplicates(storage):
    from zylch.storage.storage import DRAFT_DEDUP_WINDOW_HOURS

    first = _create(storage)
    recent = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        hours=DRAFT_DEDUP_WINDOW_HOURS, minutes=-1
    )
    storage.update_draft(OWNER, first["id"], {"created_at": recent})

    second = _create(storage)

    assert second["id"] == first["id"]
    assert len(_rows(storage)) == 1
