"""Tests for the person_identifiers index (whatsapp-pipeline-parity Phase 1a).

Phase 1a is additive: rows are written by the memory worker on every
upsert, but no read path consults them yet. These tests cover:

- `_normalise_phone` — canonicalisation of phone strings, with the same
  formats observed in real Mario blobs.
- `_parse_identifiers_block` — extraction of (kind, value) tuples from
  the structured `#IDENTIFIERS` header. Only structured input is parsed;
  prose in #ABOUT / #HISTORY is never consulted.
- Storage helpers `add_person_identifiers`, `find_blobs_by_identifiers`,
  `get_identifiers_for_blob` — idempotency, owner isolation, lookup.
"""

import uuid
from unittest.mock import MagicMock

import pytest

from zylch.workers.memory import _normalise_phone, _parse_identifiers_block

# ---------------------------------------------------------------------
# _normalise_phone — pure function, no DB
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Italian mobile in various formats — all collide on the
        # canonical "+39<digits>" form when a leading + is present.
        ("+39 339 6584014", "+393396584014"),
        ("+393925358412", "+393925358412"),
        ("+39 347 4636 824", "+393474636824"),
        ("+39.339.6584014", "+393396584014"),
        ("+39-339-6584014", "+393396584014"),
        # 00 prefix maps to +
        ("00393395040816", "+393395040816"),
        # Bare 10-digit form (Italian local) — kept as-is. We don't
        # invent a country code (that would be a heuristic that mis-fires
        # on non-Italian numbers).
        ("3296813937", "3296813937"),
        # International number with parens (US format)
        ("  +1 (415) 555-1234 ", "+14155551234"),
        # Embedded narrative tail — clipped at first non-numeric char.
        ("+39 339 6584014 (cell)", "+393396584014"),
        # Placeholders / noise — None
        ("(none)", None),
        ("unknown", None),
        ("", None),
        ("   ", None),
        ("123", None),  # too short
    ],
)
def test_normalise_phone(raw, expected):
    assert _normalise_phone(raw) == expected


# ---------------------------------------------------------------------
# _parse_identifiers_block — pure function, no DB
# ---------------------------------------------------------------------


def test_parse_real_block_support_profile():
    """Real shape from support@mrcall.ai blob ca832b39-…"""
    content = """
#IDENTIFIERS
Entity type: PERSON
Name: Caterina
Email: info@mrbrownsuite.it
Phone: 3296813937
Company: Mr. Brown Suite
Role: Front Office / Receptionist

#ABOUT
Caterina is a Front Office / Receptionist at Mr. Brown Suite ...
"""
    assert _parse_identifiers_block(content) == [
        ("email", "info@mrbrownsuite.it"),
        ("phone", "3296813937"),
    ]


def test_parse_multi_value_phone():
    """Real shape from cafe124 blob 085bfe05-…"""
    content = """
#IDENTIFIERS
Entity type: PERSON
Name: Carlos Eduardo Bitencourt
Email: carlos@cafezal.it
Phone: +39 347 4636 824, +393925358412
Company: Cafezal srl Società Benefit
"""
    assert _parse_identifiers_block(content) == [
        ("email", "carlos@cafezal.it"),
        ("phone", "+393474636824"),
        ("phone", "+393925358412"),
    ]


def test_parse_with_bullet_markers():
    content = """
#IDENTIFIERS
- Email: alice@example.com
- Phone: +393331234567
- Tel.: +39 02 1234567
"""
    assert _parse_identifiers_block(content) == [
        ("email", "alice@example.com"),
        ("phone", "+393331234567"),
        ("phone", "+39021234567"),
    ]


def test_parse_with_lid_identifier():
    """Mixed phone + LID — the WA case where a contact has both a
    resolved phone (from the LID-map) and the original LID jid."""
    content = """
#IDENTIFIERS
Entity type: PERSON
Name: Alessandro Simonetti
Phone: +393395040816
LID: 19095575629933@lid
"""
    assert _parse_identifiers_block(content) == [
        ("phone", "+393395040816"),
        ("lid", "19095575629933@lid"),
    ]


def test_parse_skips_placeholder_values():
    content = """
#IDENTIFIERS
Entity type: PERSON
Name: Anonymous
Email: (none)
Phone: unknown
"""
    assert _parse_identifiers_block(content) == []


def test_parse_returns_empty_when_no_identifiers_block():
    content = "Just some prose with no header."
    assert _parse_identifiers_block(content) == []


def test_parse_stops_at_next_section():
    """Content after the next `#` header must NOT be parsed even if it
    contains a Phone: line — that would be prose, not structured input."""
    content = """
#IDENTIFIERS
Entity type: PERSON
Name: Carmine
Email: c.salamone@cnit.it

#ABOUT
You can reach Carmine at Phone: +393331234567 (this MUST NOT be picked up).
"""
    parsed = _parse_identifiers_block(content)
    assert parsed == [("email", "c.salamone@cnit.it")]
    # Verify the prose phone was NOT extracted
    assert ("phone", "+393331234567") not in parsed


def test_parse_dedups_repeated_identifiers():
    """The merge prompt occasionally re-emits the same value; dedup."""
    content = """
#IDENTIFIERS
Entity type: PERSON
Email: foo@bar.com
Email: foo@bar.com, foo@bar.com
Phone: +393311111111
Phone: +393311111111
"""
    assert _parse_identifiers_block(content) == [
        ("email", "foo@bar.com"),
        ("phone", "+393311111111"),
    ]


def test_parse_lowercases_email_addresses():
    """The same address in different cases must collide on lookup."""
    content = """
#IDENTIFIERS
Entity type: PERSON
Email: Foo@Bar.COM
"""
    assert _parse_identifiers_block(content) == [("email", "foo@bar.com")]


# ---------------------------------------------------------------------
# Storage helpers — real SQLite under tmp_path
# ---------------------------------------------------------------------


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Per-test SQLite DB. Disposes the engine on teardown."""
    db_path = tmp_path / "person_id_test.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))

    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield db_path
    db_mod.dispose_engine()


def _make_blob(owner_id: str, content: str = "dummy") -> str:
    """Insert a real Blob row so person_identifiers FK is satisfied.
    Returns the blob_id."""
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob

    blob_id = str(uuid.uuid4())
    with get_session() as s:
        s.add(
            Blob(
                id=blob_id,
                owner_id=owner_id,
                namespace=f"user:{owner_id}",
                content=content,
            )
        )
    return blob_id


def test_add_identifiers_inserts_new_rows(fresh_db):
    from zylch.storage.storage import Storage

    storage = Storage()
    blob_id = _make_blob("alice@example.com")

    n = storage.add_person_identifiers(
        owner_id="alice@example.com",
        blob_id=blob_id,
        identifiers=[("email", "carmine@cnit.it"), ("phone", "+393395040816")],
    )
    assert n == 2

    rows = storage.get_identifiers_for_blob("alice@example.com", blob_id)
    assert {(r["kind"], r["value"]) for r in rows} == {
        ("email", "carmine@cnit.it"),
        ("phone", "+393395040816"),
    }


def test_add_identifiers_is_idempotent(fresh_db):
    from zylch.storage.storage import Storage

    storage = Storage()
    blob_id = _make_blob("alice@example.com")

    first = storage.add_person_identifiers(
        owner_id="alice@example.com",
        blob_id=blob_id,
        identifiers=[("email", "x@y.com"), ("phone", "+393311111111")],
    )
    assert first == 2

    # Re-run with same input + one new entry
    second = storage.add_person_identifiers(
        owner_id="alice@example.com",
        blob_id=blob_id,
        identifiers=[
            ("email", "x@y.com"),
            ("phone", "+393311111111"),
            ("phone", "+393322222222"),
        ],
    )
    assert second == 1, "only the new phone should insert"

    rows = storage.get_identifiers_for_blob("alice@example.com", blob_id)
    assert len(rows) == 3


def test_add_identifiers_skips_empty_inputs(fresh_db):
    from zylch.storage.storage import Storage

    storage = Storage()
    blob_id = _make_blob("alice@example.com")

    assert storage.add_person_identifiers("", blob_id, [("email", "a@b.c")]) == 0
    assert storage.add_person_identifiers("alice@example.com", "", [("email", "a@b.c")]) == 0
    assert storage.add_person_identifiers("alice@example.com", blob_id, []) == 0
    # Empty / None tuple values are silently skipped, not raising
    n = storage.add_person_identifiers(
        owner_id="alice@example.com",
        blob_id=blob_id,
        identifiers=[("email", ""), ("", "value"), ("email", "real@test.com")],
    )
    assert n == 1


def test_find_blobs_by_identifiers_finds_match(fresh_db):
    from zylch.storage.storage import Storage

    storage = Storage()
    blob1 = _make_blob("alice@example.com")
    blob2 = _make_blob("alice@example.com")

    storage.add_person_identifiers(
        "alice@example.com",
        blob1,
        [("phone", "+393395040816"), ("email", "carmine@cnit.it")],
    )
    storage.add_person_identifiers("alice@example.com", blob2, [("phone", "+393925358412")])

    # Match by phone — finds blob1 only
    hits = storage.find_blobs_by_identifiers("alice@example.com", [("phone", "+393395040816")])
    assert hits == [blob1]

    # OR semantics: ANY of the tuples matches
    hits = storage.find_blobs_by_identifiers(
        "alice@example.com",
        [("phone", "+393395040816"), ("phone", "+393925358412")],
    )
    assert set(hits) == {blob1, blob2}

    # No match
    assert (
        storage.find_blobs_by_identifiers("alice@example.com", [("phone", "+393999999999")]) == []
    )


def test_find_blobs_by_identifiers_isolates_owners(fresh_db):
    """An identifier value used by user A must NOT match for user B."""
    from zylch.storage.storage import Storage

    storage = Storage()
    blob_a = _make_blob("alice@example.com")
    blob_b = _make_blob("bob@example.com")

    storage.add_person_identifiers("alice@example.com", blob_a, [("phone", "+393395040816")])
    storage.add_person_identifiers("bob@example.com", blob_b, [("phone", "+393395040816")])

    hits_a = storage.find_blobs_by_identifiers("alice@example.com", [("phone", "+393395040816")])
    hits_b = storage.find_blobs_by_identifiers("bob@example.com", [("phone", "+393395040816")])
    assert hits_a == [blob_a]
    assert hits_b == [blob_b]


def test_find_blobs_normalises_input_kind_and_value(fresh_db):
    """`Email: Foo@Bar.com` was stored lowercased; `find` should match
    the same value regardless of how the caller wrote it."""
    from zylch.storage.storage import Storage

    storage = Storage()
    blob = _make_blob("alice@example.com")
    storage.add_person_identifiers("alice@example.com", blob, [("email", "stored@test.com")])

    # Caller passes upper-case kind and value with whitespace
    hits = storage.find_blobs_by_identifiers(
        "alice@example.com", [("  EMAIL ", " stored@test.com  ")]
    )
    assert hits == [blob]


def test_get_identifiers_for_unknown_blob_returns_empty(fresh_db):
    from zylch.storage.storage import Storage

    storage = Storage()
    # No blob created, no identifiers inserted
    rows = storage.get_identifiers_for_blob(
        "alice@example.com", "11111111-1111-1111-1111-111111111111"
    )
    assert rows == []


def test_cascade_delete_blob_removes_identifiers(fresh_db):
    """FK ondelete=CASCADE: deleting the blob must remove its rows."""
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob, PersonIdentifier
    from zylch.storage.storage import Storage

    storage = Storage()
    blob_id = _make_blob("alice@example.com")
    storage.add_person_identifiers("alice@example.com", blob_id, [("email", "x@y.com")])

    with get_session() as s:
        s.query(Blob).filter(Blob.id == blob_id).delete()

    with get_session() as s:
        rows = s.query(PersonIdentifier).filter(PersonIdentifier.blob_id == blob_id).all()
    assert rows == [], "ON DELETE CASCADE should have removed the identifier rows"


# ---------------------------------------------------------------------
# _upsert_entity — Phase 1b: identifier-first match precedence
# ---------------------------------------------------------------------
#
# These tests verify the matching ORDER inside `_upsert_entity` without
# making real LLM calls. We instantiate a real MemoryWorker with all
# external collaborators (LLMClient, LLMMergeService, HybridSearchEngine,
# BlobStorage) replaced by mocks. The Storage / person_identifiers
# index is real (uses fresh_db).
#
# The interesting case is "Carmine Salamone, 8 duplicate blobs": the
# new entity carries `Email: carmine@cnit.it` which was indexed for
# blob A. Cosine-search returns blob B (a different, lower-quality
# match) because A's content has drifted past the threshold. We assert
# that A is tried FIRST as a merge candidate, before B.


def _make_worker_with_mocks(owner_id: str, llm_merge_returns: list):
    """Build a MemoryWorker whose external dependencies are mocked.

    `llm_merge_returns` is a list of strings the mocked `llm_merge.merge`
    will return on successive calls (first call -> first item, etc.).
    Returning the literal "INSERT" simulates "entities don't match";
    any other string is treated as a successful merge and is written
    via blob_storage.update_blob.
    """
    from unittest.mock import MagicMock, patch

    from zylch.workers import memory as mem_mod

    # `make_llm_client()` would try to construct a real Anthropic /
    # MrCallProxyClient — neither of which is available in tests. Patch
    # at module import time so MemoryWorker.__init__ uses the mock.
    fake_client = MagicMock()
    with patch.object(mem_mod, "make_llm_client", return_value=fake_client):
        worker = mem_mod.MemoryWorker(
            storage=__import__("zylch.storage", fromlist=["Storage"]).Storage(),
            owner_id=owner_id,
        )

    # Replace heavy collaborators with mocks. The merge mock is a
    # side_effect iterable so successive calls return distinct values.
    worker.llm_merge = MagicMock()
    worker.llm_merge.merge = MagicMock(side_effect=list(llm_merge_returns))
    worker.hybrid_search = MagicMock()
    # Default: no cosine candidates and no debug-search results unless
    # the test overrides these explicitly.
    worker.hybrid_search.find_candidates_for_reconsolidation = MagicMock(return_value=[])
    worker.hybrid_search.search = MagicMock(return_value=[])
    # blob_storage: provide get_blob that reads from a per-test dict,
    # update_blob / store_blob that record calls.
    worker.blob_storage = MagicMock()
    worker.blob_storage._registry = {}  # blob_id -> {'content': ...}
    worker.blob_storage.get_blob = MagicMock(
        side_effect=lambda bid, oid: worker.blob_storage._registry.get(bid)
    )
    worker.blob_storage.update_blob = MagicMock()
    worker.blob_storage.store_blob = MagicMock(
        return_value={"id": "00000000-0000-0000-0000-NEWLY_CREATED0"}
    )
    return worker


@pytest.mark.asyncio
async def test_upsert_entity_prefers_identifier_match_over_cosine(fresh_db):
    """Two existing blobs about Carmine Salamone:
      - blob A is in the identifier index (kind=email, value=carmine@cnit.it)
      - blob B is NOT in the index but is the only cosine-match.

    A new entity arrives with the same email. Phase 1b must try A first
    (the LLM merge accepts), so the merge happens on A — not B.
    """
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "owner@test.com"

    blob_a = _make_blob(owner, content="A_OLD_CONTENT")
    blob_b = _make_blob(owner, content="B_OLD_CONTENT")

    storage.add_person_identifiers(owner, blob_a, [("email", "carmine@cnit.it")])
    # blob_b deliberately has NO identifier rows

    worker = _make_worker_with_mocks(
        owner_id=owner,
        # First merge call (against blob A) succeeds: returns merged content.
        llm_merge_returns=["A_MERGED_CONTENT"],
    )
    # blob_storage.get_blob lookup table
    worker.blob_storage._registry = {
        blob_a: {"content": "A_OLD_CONTENT"},
        blob_b: {"content": "B_OLD_CONTENT"},
    }
    # Cosine returns blob B (the OTHER duplicate), not A.
    cosine_match = MagicMock_namespace(blob_id=blob_b, content="B_OLD_CONTENT", hybrid_score=0.78)
    worker.hybrid_search.find_candidates_for_reconsolidation.return_value = [cosine_match]

    new_entity = """
#IDENTIFIERS
Entity type: PERSON
Name: Carmine Salamone
Email: carmine@cnit.it
"""
    await worker._upsert_entity(
        entity_content=new_entity,
        event_desc="Extracted from email TEST123",
        email_id="TEST123",
        entity_num=1,
        total_entities=1,
    )

    # llm_merge.merge must have been called exactly ONCE (matched on A,
    # accepted, no need to try B).
    assert worker.llm_merge.merge.call_count == 1
    first_call_args = worker.llm_merge.merge.call_args_list[0].args
    assert first_call_args[0] == "A_OLD_CONTENT", (
        f"identifier-match A should be first merge candidate, "
        f"got first call against {first_call_args[0]!r}"
    )

    # update_blob must have been called on A, NOT on B.
    worker.blob_storage.update_blob.assert_called_once()
    assert worker.blob_storage.update_blob.call_args.kwargs["blob_id"] == blob_a
    worker.blob_storage.store_blob.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_entity_falls_back_to_cosine_on_identifier_reject(fresh_db):
    """If the identifier-matched blob's LLM merge says INSERT (entities
    don't actually match — e.g. shared switchboard phone), the cosine
    fallback must still run."""
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "owner@test.com"

    blob_a = _make_blob(owner, content="A_SHARED_PHONE_BUT_DIFF_PERSON")
    blob_c = _make_blob(owner, content="C_RIGHT_PERSON")

    # blob_a is identifier-matched (shared switchboard)
    storage.add_person_identifiers(owner, blob_a, [("phone", "+390212345678")])

    worker = _make_worker_with_mocks(
        owner_id=owner,
        # First call (A) → INSERT (rejected); second call (C) → merged
        llm_merge_returns=["INSERT", "C_MERGED"],
    )
    worker.blob_storage._registry = {
        blob_a: {"content": "A_SHARED_PHONE_BUT_DIFF_PERSON"},
        blob_c: {"content": "C_RIGHT_PERSON"},
    }
    # Cosine returns C (the actual right person)
    cosine_match = MagicMock_namespace(blob_id=blob_c, content="C_RIGHT_PERSON", hybrid_score=0.81)
    worker.hybrid_search.find_candidates_for_reconsolidation.return_value = [cosine_match]

    new_entity = """
#IDENTIFIERS
Entity type: PERSON
Name: Mario Rossi
Phone: +390212345678
"""
    await worker._upsert_entity(
        entity_content=new_entity,
        event_desc="Extracted from email TEST456",
        email_id="TEST456",
        entity_num=1,
        total_entities=1,
    )

    # Two merge attempts: A (rejected), then C (accepted).
    assert worker.llm_merge.merge.call_count == 2
    first = worker.llm_merge.merge.call_args_list[0].args[0]
    second = worker.llm_merge.merge.call_args_list[1].args[0]
    assert first == "A_SHARED_PHONE_BUT_DIFF_PERSON"
    assert second == "C_RIGHT_PERSON"
    worker.blob_storage.update_blob.assert_called_once()
    assert worker.blob_storage.update_blob.call_args.kwargs["blob_id"] == blob_c


@pytest.mark.asyncio
async def test_upsert_entity_no_match_creates_new_blob(fresh_db):
    """No identifier match, no cosine candidate → CREATE new blob.
    The new blob's identifiers must be written to person_identifiers."""
    from zylch.storage.storage import Storage

    storage = Storage()  # noqa: F841 — instantiated to ensure singleton
    owner = "owner@test.com"

    worker = _make_worker_with_mocks(
        owner_id=owner,
        llm_merge_returns=[],  # never called
    )
    # No blobs registered, no cosine match.
    worker.hybrid_search.find_candidates_for_reconsolidation.return_value = []

    # store_blob must return a real UUID-shaped id and the row must
    # exist in `blobs` for the FK on person_identifiers to be valid.
    new_blob_id = _make_blob(owner, content="NEW_BLOB_CONTENT")
    worker.blob_storage.store_blob = MagicMock(return_value={"id": new_blob_id})

    new_entity = """
#IDENTIFIERS
Entity type: PERSON
Name: Brand New Person
Email: newbie@example.com
Phone: +393331234567
"""
    await worker._upsert_entity(
        entity_content=new_entity,
        event_desc="Extracted from email TEST789",
        email_id="TEST789",
        entity_num=1,
        total_entities=1,
    )

    worker.llm_merge.merge.assert_not_called()
    worker.blob_storage.store_blob.assert_called_once()

    # Verify identifier rows landed on the newly-created blob.
    rows = storage.get_identifiers_for_blob(owner, new_blob_id)
    assert {(r["kind"], r["value"]) for r in rows} == {
        ("email", "newbie@example.com"),
        ("phone", "+393331234567"),
    }


# Lightweight stand-in for the namedtuple-shaped result returned by
# `hybrid_search.find_candidates_for_reconsolidation`. Real result has
# at least .blob_id, .content, .hybrid_score.
class MagicMock_namespace:
    def __init__(self, blob_id: str, content: str, hybrid_score: float):
        self.blob_id = blob_id
        self.content = content
        self.hybrid_score = hybrid_score


# ---------------------------------------------------------------------
# migrate_blob_references — Phase 1c: dedup sweep prerequisites
# ---------------------------------------------------------------------
#
# Before deleting a duplicate blob we move every cross-reference from
# the dup to the keeper. Without this step, the FK CASCADE on `blobs.id`
# silently drops:
#   - person_identifiers (the cross-channel match would lose the dup's
#     email/phone/lid),
#   - email_blobs / calendar_blobs (the F7 topical-sibling lookup
#     would lose the link "this email contributed to that blob"),
#   - dangling references in task_items.sources.blobs (existing tasks
#     would silently miss the keeper).


def test_migrate_person_identifiers_to_keeper(fresh_db):
    """Identifiers on dup must end up on keeper, idempotent on rerun."""
    from zylch.storage.storage import Storage

    storage = Storage()
    keeper = _make_blob("alice@example.com", content="KEEPER")
    dup = _make_blob("alice@example.com", content="DUP")

    storage.add_person_identifiers("alice@example.com", keeper, [("email", "shared@x.com")])
    storage.add_person_identifiers(
        "alice@example.com",
        dup,
        [("email", "shared@x.com"), ("phone", "+393331234567")],
    )

    counts = storage.migrate_blob_references(
        owner_id="alice@example.com",
        dup_blob_id=dup,
        keeper_blob_id=keeper,
    )
    # Only the phone is new on the keeper — the email was already there.
    assert counts["person_identifiers_migrated"] == 1

    keeper_ids = storage.get_identifiers_for_blob("alice@example.com", keeper)
    assert {(r["kind"], r["value"]) for r in keeper_ids} == {
        ("email", "shared@x.com"),
        ("phone", "+393331234567"),
    }

    # Re-run is a no-op
    counts2 = storage.migrate_blob_references(
        owner_id="alice@example.com",
        dup_blob_id=dup,
        keeper_blob_id=keeper,
    )
    assert counts2["person_identifiers_migrated"] == 0


def test_migrate_email_blobs_to_keeper(fresh_db):
    """email_blobs(email_id, dup) must become email_blobs(email_id, keeper)."""
    from zylch.storage.database import get_session
    from zylch.storage.models import Email, EmailBlob
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    keeper = _make_blob(owner, content="KEEPER")
    dup = _make_blob(owner, content="DUP")

    eid_keeper = "00000000-0000-0000-0000-eeeeeeeeeee1"
    eid_dup = "00000000-0000-0000-0000-eeeeeeeeeee2"
    eid_shared = "00000000-0000-0000-0000-eeeeeeeeeee3"
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    with get_session() as s:
        for eid in (eid_keeper, eid_dup, eid_shared):
            s.add(
                Email(
                    id=eid,
                    owner_id=owner,
                    gmail_id=eid,
                    thread_id=eid,
                    from_email="x@y.com",
                    date=now,
                )
            )

    storage.add_email_blob_link(owner, eid_keeper, keeper)
    storage.add_email_blob_link(owner, eid_shared, keeper)
    storage.add_email_blob_link(owner, eid_dup, dup)
    storage.add_email_blob_link(owner, eid_shared, dup)

    counts = storage.migrate_blob_references(owner_id=owner, dup_blob_id=dup, keeper_blob_id=keeper)
    assert counts["email_blobs_migrated"] == 1  # only eid_dup is new on keeper

    keeper_emails = storage.get_blobs_for_email(owner, eid_dup)
    assert keeper in keeper_emails

    # Sanity: the dup's email_blobs rows still exist; CASCADE will
    # drop them when the blob is deleted later.
    with get_session() as s:
        dup_links = (
            s.query(EmailBlob.email_id)
            .filter(EmailBlob.blob_id == dup, EmailBlob.owner_id == owner)
            .all()
        )
    assert {str(r[0]) for r in dup_links} == {eid_dup, eid_shared}


def test_migrate_task_items_sources_blobs(fresh_db):
    """task_items.sources.blobs lists must replace dup with keeper, dedup."""
    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    keeper = _make_blob(owner, content="KEEPER")
    dup = _make_blob(owner, content="DUP")
    other_blob = _make_blob(owner, content="OTHER")

    with get_session() as s:
        s.add(
            TaskItem(
                id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                owner_id=owner,
                event_type="email",
                event_id="ev_a",
                sources={"blobs": [dup], "emails": ["e_a"]},
            )
        )
        s.add(
            TaskItem(
                id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                owner_id=owner,
                event_type="email",
                event_id="ev_b",
                sources={"blobs": [dup, keeper], "emails": ["e_b"]},
            )
        )
        s.add(
            TaskItem(
                id="cccccccc-cccc-cccc-cccc-cccccccccccc",
                owner_id=owner,
                event_type="email",
                event_id="ev_c",
                sources={"blobs": [other_blob, dup], "emails": ["e_c"]},
            )
        )
        s.add(
            TaskItem(
                id="dddddddd-dddd-dddd-dddd-dddddddddddd",
                owner_id=owner,
                event_type="email",
                event_id="ev_d",
                sources={"blobs": [other_blob], "emails": ["e_d"]},
            )
        )

    counts = storage.migrate_blob_references(owner_id=owner, dup_blob_id=dup, keeper_blob_id=keeper)
    assert counts["task_items_updated"] == 3

    with get_session() as s:
        rows = {
            t.id: list(t.sources.get("blobs") or [])
            for t in s.query(TaskItem).filter(TaskItem.owner_id == owner).all()
        }
    assert rows["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"] == [keeper]
    assert rows["bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"] == [keeper]
    assert rows["cccccccc-cccc-cccc-cccc-cccccccccccc"] == [other_blob, keeper]
    assert rows["dddddddd-dddd-dddd-dddd-dddddddddddd"] == [other_blob]


def test_migrate_skips_when_dup_equals_keeper(fresh_db):
    """Self-migrate is a no-op (defensive guard)."""
    from zylch.storage.storage import Storage

    storage = Storage()
    blob = _make_blob("alice@example.com")
    storage.add_person_identifiers("alice@example.com", blob, [("email", "x@y.com")])

    counts = storage.migrate_blob_references(
        owner_id="alice@example.com",
        dup_blob_id=blob,
        keeper_blob_id=blob,
    )
    assert counts == {
        "person_identifiers_migrated": 0,
        "email_blobs_migrated": 0,
        "calendar_blobs_migrated": 0,
        "whatsapp_blobs_migrated": 0,
        "task_items_updated": 0,
    }


def test_migrate_skips_with_empty_inputs(fresh_db):
    from zylch.storage.storage import Storage

    storage = Storage()
    blob = _make_blob("alice@example.com")

    for owner, dup, keeper in [
        ("", blob, blob),
        ("alice@example.com", "", blob),
        ("alice@example.com", blob, ""),
    ]:
        counts = storage.migrate_blob_references(
            owner_id=owner, dup_blob_id=dup, keeper_blob_id=keeper
        )
        assert all(v == 0 for v in counts.values())


# ---------------------------------------------------------------------
# _build_dedup_clusters — pure function, no DB
# ---------------------------------------------------------------------


def test_dedup_cluster_builder_groups_by_shared_identifier():
    """Three blobs forming a chain: A↔B share email, B↔C share phone.
    Must yield ONE cluster of {A, B, C}."""
    from zylch.memory.llm_merge import _build_dedup_clusters

    blobs = [
        {"id": "A", "content": ""},
        {"id": "B", "content": ""},
        {"id": "C", "content": ""},
    ]
    blob_identifiers = {
        "A": {("email", "shared@a.b")},
        "B": {("email", "shared@a.b"), ("phone", "+391112223333")},
        "C": {("phone", "+391112223333")},
    }
    clusters = _build_dedup_clusters(blobs, blob_identifiers)
    assert len(clusters) == 1
    assert {b["id"] for b in clusters[0]} == {"A", "B", "C"}


def test_dedup_cluster_builder_falls_back_to_name():
    """Blobs without structured identifiers can still cluster by Name."""
    from zylch.memory.llm_merge import _build_dedup_clusters

    blobs = [
        {"id": "A", "content": "#IDENTIFIERS\nName: Carmine Salamone\n"},
        {"id": "B", "content": "#IDENTIFIERS\nName: carmine salamone\n"},
        {"id": "C", "content": "#IDENTIFIERS\nName: Different Person\n"},
    ]
    clusters = _build_dedup_clusters(blobs, {})
    assert len(clusters) == 1
    assert {b["id"] for b in clusters[0]} == {"A", "B"}


def test_dedup_cluster_builder_drops_singletons():
    from zylch.memory.llm_merge import _build_dedup_clusters

    blobs = [
        {"id": "A", "content": "#IDENTIFIERS\nName: alone-a"},
        {"id": "B", "content": "#IDENTIFIERS\nName: alone-b"},
    ]
    blob_identifiers = {
        "A": {("email", "a@x.com")},
        "B": {("email", "b@x.com")},
    }
    clusters = _build_dedup_clusters(blobs, blob_identifiers)
    assert clusters == []


def test_dedup_cluster_builder_empty_input():
    from zylch.memory.llm_merge import _build_dedup_clusters

    assert _build_dedup_clusters([], {}) == []


# ---------------------------------------------------------------------
# reconsolidate_now — Phase 1c end-to-end (mocked LLM)
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconsolidate_now_merges_and_migrates_refs(fresh_db, monkeypatch):
    """Flagship Phase 1c case: 2 blobs sharing email get clustered, LLM
    merge accepts, references migrate, dup is deleted. Models the
    FeFarma duplicate observed live on 2026-05-08."""
    from zylch.memory import llm_merge as merge_mod
    from zylch.storage.database import get_session
    from zylch.storage.models import Email, TaskItem
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "owner@test.com"

    keeper = _make_blob(
        owner,
        content=(
            "#IDENTIFIERS\nEntity type: COMPANY\nName: FEFARMA\n"
            "Email: info@fefarma.it\n\n#ABOUT\nKeeper has more history.\n"
            "lots of additional content to make this the longer one"
        ),
    )
    dup = _make_blob(
        owner,
        content=(
            "#IDENTIFIERS\nEntity type: COMPANY\nName: FeFarma\n"
            "Email: info@fefarma.it\n\n#ABOUT\nDup."
        ),
    )
    storage.add_person_identifiers(owner, keeper, [("email", "info@fefarma.it")])
    storage.add_person_identifiers(owner, dup, [("email", "info@fefarma.it")])

    dup_email_id = "00000000-0000-0000-0000-eeeeeeeeeee9"
    from datetime import datetime as _dt, timezone as _tz

    with get_session() as s:
        s.add(
            Email(
                id=dup_email_id,
                owner_id=owner,
                gmail_id=dup_email_id,
                thread_id=dup_email_id,
                from_email="info@fefarma.it",
                date=_dt.now(_tz.utc),
            )
        )
    storage.add_email_blob_link(owner, dup_email_id, dup)

    task_id = "11111111-1111-1111-1111-111111111111"
    with get_session() as s:
        s.add(
            TaskItem(
                id=task_id,
                owner_id=owner,
                event_type="email",
                event_id="ev_t",
                sources={"blobs": [dup], "emails": [dup_email_id]},
            )
        )

    fake_client = MagicMock()
    monkeypatch.setattr(merge_mod, "make_llm_client", lambda *a, **kw: fake_client)
    monkeypatch.setattr(merge_mod, "try_make_llm_client", lambda *a, **kw: fake_client)
    fake_merge_service = MagicMock()
    fake_merge_service.merge = MagicMock(
        return_value=(
            "#IDENTIFIERS\nEntity type: COMPANY\nName: FeFarma\n"
            "Email: info@fefarma.it\n\n#ABOUT\nMerged.\n"
            "longer than ten chars to bypass the INSERT length check"
        )
    )
    monkeypatch.setattr(merge_mod, "LLMMergeService", lambda *a, **kw: fake_merge_service)

    summary = await merge_mod.reconsolidate_now(owner)

    assert summary["groups_examined"] == 1
    assert summary["blobs_merged"] == 1
    assert summary["blobs_kept_distinct"] == 0
    assert summary["email_blobs_migrated"] == 1
    # The identifier was already on the keeper, so 0 net migrations.
    assert summary["person_identifiers_migrated"] == 0
    assert summary["task_items_updated"] == 1

    keeper_ids = storage.get_identifiers_for_blob(owner, keeper)
    assert ("email", "info@fefarma.it") in {(r["kind"], r["value"]) for r in keeper_ids}

    keeper_emails = storage.get_blobs_for_email(owner, dup_email_id)
    assert keeper in keeper_emails
    assert dup not in keeper_emails

    with get_session() as s:
        task = s.query(TaskItem).filter(TaskItem.id == task_id).one()
    assert task.sources["blobs"] == [keeper]


@pytest.mark.asyncio
async def test_reconsolidate_now_keeps_distinct_when_llm_inserts(fresh_db, monkeypatch):
    """LLM rejects the merge — both blobs survive, no migration runs."""
    from zylch.memory import llm_merge as merge_mod
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "owner@test.com"

    blob_a = _make_blob(
        owner,
        content="#IDENTIFIERS\nName: Mario Rossi\nPhone: +391112223333",
    )
    blob_b = _make_blob(
        owner,
        content="#IDENTIFIERS\nName: Mario Bianchi\nPhone: +391112223333",
    )
    storage.add_person_identifiers(owner, blob_a, [("phone", "+391112223333")])
    storage.add_person_identifiers(owner, blob_b, [("phone", "+391112223333")])

    fake_client = MagicMock()
    monkeypatch.setattr(merge_mod, "make_llm_client", lambda *a, **kw: fake_client)
    monkeypatch.setattr(merge_mod, "try_make_llm_client", lambda *a, **kw: fake_client)
    fake_merge_service = MagicMock()
    fake_merge_service.merge = MagicMock(return_value="INSERT")
    monkeypatch.setattr(merge_mod, "LLMMergeService", lambda *a, **kw: fake_merge_service)

    summary = await merge_mod.reconsolidate_now(owner)
    assert summary["blobs_merged"] == 0
    assert summary["blobs_kept_distinct"] == 1
    a_ids = storage.get_identifiers_for_blob(owner, blob_a)
    b_ids = storage.get_identifiers_for_blob(owner, blob_b)
    assert a_ids and b_ids


@pytest.mark.asyncio
async def test_reconsolidate_now_no_clusters_returns_zero(fresh_db, monkeypatch):
    from zylch.memory import llm_merge as merge_mod

    owner = "owner@test.com"
    _make_blob(owner, content="#IDENTIFIERS\nName: Lonely\n")

    fake_client = MagicMock()
    monkeypatch.setattr(merge_mod, "make_llm_client", lambda *a, **kw: fake_client)
    monkeypatch.setattr(merge_mod, "try_make_llm_client", lambda *a, **kw: fake_client)

    summary = await merge_mod.reconsolidate_now(owner)
    assert summary["groups_examined"] == 0
    assert summary["blobs_merged"] == 0


@pytest.mark.asyncio
async def test_reconsolidate_now_skips_when_no_llm(fresh_db, monkeypatch):
    from zylch.memory import llm_merge as merge_mod

    monkeypatch.setattr(merge_mod, "try_make_llm_client", lambda *a, **kw: None)

    summary = await merge_mod.reconsolidate_now("owner@test.com")
    assert summary["no_llm"] is True
    assert summary["blobs_merged"] == 0
