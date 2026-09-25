"""Tests for the person_identifiers index (whatsapp-pipeline-parity Phase 1a).

Phase 1a is additive: rows are written by the memory worker on every
upsert, but no read path consults them yet. These tests cover:

- `_normalise_phone` — canonicalisation of phone strings, with the same
  formats observed in real blobs.
- `_parse_identifiers_block` — extraction of (kind, value) tuples from
  the structured `#IDENTIFIERS` header. Only structured input is parsed;
  prose in #ABOUT / #HISTORY is never consulted.
- Storage helpers `add_person_identifiers`, `find_blobs_by_identifiers`,
  `get_identifiers_for_blob` — idempotency, owner isolation, lookup.
"""

import uuid

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
        ("+39 333 1234567", "+393331234567"),
        ("+393331234567", "+393331234567"),
        ("+39 347 0000000", "+393470000000"),
        ("+39.333.1234567", "+393331234567"),
        ("+39-333-1234567", "+393331234567"),
        # 00 prefix maps to +
        ("00393331234567", "+393331234567"),
        # Bare 10-digit form (Italian local) — kept as-is. We don't
        # invent a country code (that would be a heuristic that mis-fires
        # on non-Italian numbers).
        ("3290000000", "3290000000"),
        # International number with parens (US format)
        ("  +1 (415) 555-1234 ", "+14155551234"),
        # Embedded narrative tail — clipped at first non-numeric char.
        ("+39 333 1234567 (cell)", "+393331234567"),
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
    """Real shape from support@example.com blob ca832b39-…"""
    content = """
#IDENTIFIERS
Entity type: PERSON
Name: Maria
Email: brown@example.com
Phone: 3290000000
Company: Beta Spa
Role: Front Office / Receptionist

#ABOUT
Maria is a Front Office / Receptionist at Beta Spa ...
"""
    assert _parse_identifiers_block(content) == [
        ("email", "brown@example.com"),
        ("phone", "3290000000"),
    ]


def test_parse_multi_value_phone():
    """Real shape from examplebiz blob 085bfe05-…"""
    content = """
#IDENTIFIERS
Entity type: PERSON
Name: Pedro Alvarez
Email: carlos@example.com
Phone: +39 347 0000000, +393331234567
Company: Acme srl Società Benefit
"""
    assert _parse_identifiers_block(content) == [
        ("email", "carlos@example.com"),
        ("phone", "+393470000000"),
        ("phone", "+393331234567"),
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
Name: Luca Bianchi
Phone: +393331234567
LID: 19095575629933@lid
"""
    assert _parse_identifiers_block(content) == [
        ("phone", "+393331234567"),
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
Name: John
Email: contact@example.com

#ABOUT
You can reach John at Phone: +393331234567 (this MUST NOT be picked up).
"""
    parsed = _parse_identifiers_block(content)
    assert parsed == [("email", "contact@example.com")]
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
    from zylch.memory.company_key import current_company_key, entity_namespace
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob

    blob_id = str(uuid.uuid4())
    with get_session() as s:
        s.add(
            Blob(
                id=blob_id,
                owner_id=owner_id,
                namespace=entity_namespace(current_company_key()),
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
        identifiers=[("email", "contact@example.com"), ("phone", "+393331234567")],
    )
    assert n == 2

    rows = storage.get_identifiers_for_blob("alice@example.com", blob_id)
    assert {(r["kind"], r["value"]) for r in rows} == {
        ("email", "contact@example.com"),
        ("phone", "+393331234567"),
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
        [("phone", "+393331234567"), ("email", "contact@example.com")],
    )
    storage.add_person_identifiers("alice@example.com", blob2, [("phone", "+393339998888")])

    # Match by phone — finds blob1 only
    hits = storage.find_blobs_by_identifiers("alice@example.com", [("phone", "+393331234567")])
    assert hits == [blob1]

    # OR semantics: ANY of the tuples matches
    hits = storage.find_blobs_by_identifiers(
        "alice@example.com",
        [("phone", "+393331234567"), ("phone", "+393339998888")],
    )
    assert set(hits) == {blob1, blob2}

    # No match
    assert (
        storage.find_blobs_by_identifiers("alice@example.com", [("phone", "+393999999999")]) == []
    )


def test_find_blobs_by_identifiers_is_company_scoped(fresh_db):
    """The identifier index belongs to the company, not to an owner.

    Two accounts sharing one memory key are one company: a phone that
    account A indexed is found by account B — that is the point of a
    shared memory (a WhatsApp from +39333… reaches the blob a colleague
    built from an email signature). Until 2026-09 this index was walled
    per owner; the wall is now the company key, and ``owner_id`` on a row
    is provenance only.
    """
    from zylch.storage.storage import Storage

    storage = Storage()
    blob_a = _make_blob("alice@example.com")
    blob_b = _make_blob("bob@example.com")

    storage.add_person_identifiers("alice@example.com", blob_a, [("phone", "+393331234567")])
    storage.add_person_identifiers("bob@example.com", blob_b, [("phone", "+393331234567")])

    hits_a = storage.find_blobs_by_identifiers("alice@example.com", [("phone", "+393331234567")])
    hits_b = storage.find_blobs_by_identifiers("bob@example.com", [("phone", "+393331234567")])
    assert sorted(hits_a) == sorted(hits_b) == sorted([blob_a, blob_b])


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
# _build_dedup_clusters — pure function, no DB
# ---------------------------------------------------------------------


def test_dedup_cluster_builder_groups_by_shared_identifier():
    """Three blobs forming a chain: A↔B share email, B↔C share phone.
    Must yield ONE cluster of {A, B, C}."""
    from zylch.memory.clusters import _build_dedup_clusters

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
    from zylch.memory.clusters import _build_dedup_clusters

    blobs = [
        {"id": "A", "content": "#IDENTIFIERS\nName: John Smith\n"},
        {"id": "B", "content": "#IDENTIFIERS\nName: john smith\n"},
        {"id": "C", "content": "#IDENTIFIERS\nName: Different Person\n"},
    ]
    clusters = _build_dedup_clusters(blobs, {})
    assert len(clusters) == 1
    assert {b["id"] for b in clusters[0]} == {"A", "B"}


def test_dedup_cluster_builder_drops_singletons():
    from zylch.memory.clusters import _build_dedup_clusters

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
    from zylch.memory.clusters import _build_dedup_clusters

    assert _build_dedup_clusters([], {}) == []
