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
