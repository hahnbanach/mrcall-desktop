"""Semantic tests for zylch.services.whatsapp_search.

Exercises the shared thread-row builder and the message/contact search
against a real temp SQLite DB (no neonize socket needed). These lock the
behaviour the desktop WhatsApp tab's search + listing depend on.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

OWNER = "owner-search-test"
BASE = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Per-test SQLite DB. Disposes the engine on teardown."""
    db_path = tmp_path / "wa_search_test.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))

    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield db_path
    db_mod.dispose_engine()


def _msg(
    chat_jid: str,
    text=None,
    *,
    minutes: int = 0,
    is_from_me: bool = False,
    sender_name=None,
    transcription=None,
    is_group: bool = False,
    media_type=None,
    owner: str = OWNER,
):
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage

    with get_session() as s:
        s.add(
            WhatsAppMessage(
                id=str(uuid.uuid4()),
                owner_id=owner,
                message_id=str(uuid.uuid4()),
                chat_jid=chat_jid,
                sender_jid=("me" if is_from_me else chat_jid),
                sender_name=sender_name,
                text=text,
                transcription=transcription,
                media_type=media_type,
                timestamp=BASE + timedelta(minutes=minutes),
                is_from_me=is_from_me,
                is_group=is_group,
            )
        )


def _contact(jid: str, *, name=None, push_name=None, phone=None, owner: str = OWNER):
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppContact

    with get_session() as s:
        s.add(
            WhatsAppContact(
                id=str(uuid.uuid4()),
                owner_id=owner,
                jid=jid,
                name=name,
                push_name=push_name,
                phone_number=phone,
                synced_at=BASE,
            )
        )


# ── build_thread_rows ──────────────────────────────────────────────────


def test_build_thread_rows_shape_and_order(fresh_db):
    from zylch.services.whatsapp_search import build_thread_rows
    from zylch.storage.database import get_session

    alice = "393331112222@s.whatsapp.net"
    bob = "393339998888@s.whatsapp.net"
    _msg(alice, "hi from alice", minutes=1, sender_name="Alice")
    _msg(alice, "ok ciao", minutes=5, is_from_me=True)
    _msg(bob, "yo", minutes=2, sender_name="Bob")
    _contact(alice, name="Alice Rossi", phone="+393331112222")

    # Order is preserved verbatim — caller decides ranking.
    with get_session() as s:
        rows = build_thread_rows(s, OWNER, [bob, alice])

    assert [r["jid"] for r in rows] == [bob, alice]
    by_jid = {r["jid"]: r for r in rows}

    a = by_jid[alice]
    assert a["name"] == "Alice Rossi"  # contact wins over sender_name
    assert a["phone"] == "+393331112222"
    assert a["message_count"] == 2
    assert a["last_preview"] == "ok ciao"  # latest message
    assert a["last_from_me"] is True
    assert a["is_group"] is False

    b = by_jid[bob]
    assert b["name"] == "Bob"  # falls back to peer sender_name (no contact)
    assert b["phone"] == "393339998888"  # bare local-part of @s.whatsapp.net
    assert b["message_count"] == 1
    assert b["last_from_me"] is False


def test_build_thread_rows_empty(fresh_db):
    from zylch.services.whatsapp_search import build_thread_rows
    from zylch.storage.database import get_session

    with get_session() as s:
        assert build_thread_rows(s, OWNER, []) == []


def test_build_thread_rows_lid_not_rendered_as_phone(fresh_db):
    from zylch.services.whatsapp_search import build_thread_rows
    from zylch.storage.database import get_session

    lid = "86904452186141@lid"
    _msg(lid, "hey", minutes=1, sender_name="Pseudonym")
    with get_session() as s:
        (row,) = build_thread_rows(s, OWNER, [lid])
    assert row["phone"] is None  # never expose the LID numeric id as a phone


# ── search_thread_jids ─────────────────────────────────────────────────


def test_search_by_message_text(fresh_db):
    from zylch.services.whatsapp_search import search_thread_jids
    from zylch.storage.database import get_session

    alice = "393331112222@s.whatsapp.net"
    bob = "393339998888@s.whatsapp.net"
    _msg(alice, "the invoice is attached", minutes=1)
    _msg(bob, "see you tomorrow", minutes=2)

    with get_session() as s:
        jids, snip = search_thread_jids(s, OWNER, "invoice", 50)

    assert jids == [alice]
    assert snip[alice] == "the invoice is attached"


def test_search_by_transcription_prefers_transcript_snippet(fresh_db):
    from zylch.services.whatsapp_search import search_thread_jids
    from zylch.storage.database import get_session

    carol = "393332221111@s.whatsapp.net"
    # Voice note: placeholder text, words live in the transcription.
    _msg(carol, "[voice]", minutes=1, media_type="voice", transcription="ci vediamo a Milano")

    with get_session() as s:
        jids, snip = search_thread_jids(s, OWNER, "milano", 50)

    assert jids == [carol]
    # Snippet is the transcript, not the "[voice]" placeholder.
    assert snip[carol] == "ci vediamo a Milano"


def test_search_by_contact_name(fresh_db):
    from zylch.services.whatsapp_search import search_thread_jids
    from zylch.storage.database import get_session

    alice = "393331112222@s.whatsapp.net"
    _msg(alice, "ok", minutes=1)
    _contact(alice, name="Alice Rossi", phone="+393331112222")

    with get_session() as s:
        jids, snip = search_thread_jids(s, OWNER, "rossi", 50)

    assert jids == [alice]  # matched via contact name, not message body


def test_search_by_phone_digits(fresh_db):
    from zylch.services.whatsapp_search import search_thread_jids
    from zylch.storage.database import get_session

    alice = "393331112222@s.whatsapp.net"
    _msg(alice, "hello", minutes=1)

    with get_session() as s:
        jids, _ = search_thread_jids(s, OWNER, "+39 333 111", 50)

    assert alice in jids  # digit run matched the chat_jid local-part


def test_search_group_message(fresh_db):
    from zylch.services.whatsapp_search import build_thread_rows, search_thread_jids
    from zylch.storage.database import get_session

    grp = "120363000000000000@g.us"
    _msg(grp, "team standup at 10", minutes=1, is_group=True, sender_name="Dave")

    with get_session() as s:
        jids, _ = search_thread_jids(s, OWNER, "standup", 50)
        rows = build_thread_rows(s, OWNER, jids)

    assert jids == [grp]
    assert rows[0]["is_group"] is True


def test_search_excludes_broadcast_and_newsletter(fresh_db):
    from zylch.services.whatsapp_search import search_thread_jids
    from zylch.storage.database import get_session

    _msg("status@broadcast", "promo deal", minutes=1)
    _msg("123@newsletter", "promo channel", minutes=2)
    real = "393331112222@s.whatsapp.net"
    _msg(real, "promo for you", minutes=3)

    with get_session() as s:
        jids, _ = search_thread_jids(s, OWNER, "promo", 50)

    assert jids == [real]  # broadcast + newsletter never surface


def test_search_empty_query(fresh_db):
    from zylch.services.whatsapp_search import search_thread_jids
    from zylch.storage.database import get_session

    _msg("393331112222@s.whatsapp.net", "anything", minutes=1)
    with get_session() as s:
        assert search_thread_jids(s, OWNER, "   ", 50) == ([], {})


def test_search_no_match(fresh_db):
    from zylch.services.whatsapp_search import search_thread_jids
    from zylch.storage.database import get_session

    _msg("393331112222@s.whatsapp.net", "hello world", minutes=1)
    with get_session() as s:
        jids, snip = search_thread_jids(s, OWNER, "zzzznotfound", 50)
    assert jids == []
    assert snip == {}


def test_search_orders_newest_first(fresh_db):
    from zylch.services.whatsapp_search import search_thread_jids
    from zylch.storage.database import get_session

    old = "393331110000@s.whatsapp.net"
    new = "393339990000@s.whatsapp.net"
    _msg(old, "report v1", minutes=1)
    _msg(new, "report v2", minutes=100)

    with get_session() as s:
        jids, _ = search_thread_jids(s, OWNER, "report", 50)

    assert jids == [new, old]  # most recent activity first
