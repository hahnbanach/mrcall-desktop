"""Tests for WhatsApp voice-note transcription (faster-whisper).

Covers:
  * real on-device STT against a fixture ogg/opus (auto-detect + forced),
  * the ``transcription`` / ``media_path`` schema migration,
  * the storage round-trip for the transcription watermark,
  * ``resolve_user_language`` honouring USER_LANGUAGE without a default.

The real-STT cases skip gracefully when the fixture audio is absent so
the suite stays portable.
"""

import os
import uuid
from datetime import datetime, timezone

import pytest

_AUDIO = "/tmp/wa_voice_test.ogg"
_HAVE_AUDIO = os.path.exists(_AUDIO)


# ---------------------------------------------------------------------
# resolve_user_language — no hardcoded Italian default
# ---------------------------------------------------------------------


def test_resolve_user_language_returns_set_code(monkeypatch):
    from zylch.whatsapp.transcription import resolve_user_language

    monkeypatch.setenv("USER_LANGUAGE", "en")
    assert resolve_user_language() == "en"
    monkeypatch.setenv("USER_LANGUAGE", "IT")  # case-insensitive
    assert resolve_user_language() == "it"


def test_resolve_user_language_none_when_unset_or_unknown(monkeypatch):
    from zylch.whatsapp.transcription import resolve_user_language

    monkeypatch.delenv("USER_LANGUAGE", raising=False)
    assert resolve_user_language() is None  # NOT "it"
    monkeypatch.setenv("USER_LANGUAGE", "")
    assert resolve_user_language() is None
    monkeypatch.setenv("USER_LANGUAGE", "zz")
    assert resolve_user_language() is None


# ---------------------------------------------------------------------
# Real on-device STT
# ---------------------------------------------------------------------


@pytest.mark.skipif(not _HAVE_AUDIO, reason=f"fixture audio {_AUDIO} not present")
def test_transcribe_audio_autodetect_returns_expected_text():
    from zylch.whatsapp.transcription import transcribe_audio

    out = transcribe_audio(_AUDIO, language=None)
    assert out, "auto-detect transcription must be non-empty"
    assert "preventivo" in out.lower()


@pytest.mark.skipif(not _HAVE_AUDIO, reason=f"fixture audio {_AUDIO} not present")
def test_transcribe_audio_forced_italian_non_empty():
    from zylch.whatsapp.transcription import transcribe_audio

    out = transcribe_audio(_AUDIO, language="it")
    assert out and out.strip()


def test_transcribe_audio_missing_file_returns_none():
    """A non-existent path must degrade to None, never raise."""
    from zylch.whatsapp.transcription import transcribe_audio

    assert transcribe_audio("/tmp/does-not-exist-xyz.ogg", language="it") is None


# ---------------------------------------------------------------------
# Migration — fresh DB carries the new columns
# ---------------------------------------------------------------------


def test_migration_adds_transcription_and_media_path(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "schema.db"))
    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    try:
        from zylch.storage.database import get_session

        with get_session() as s:
            cols = {
                r[1]
                for r in s.execute(
                    __import__("sqlalchemy").text("PRAGMA table_info(whatsapp_messages)")
                )
            }
    finally:
        db_mod.dispose_engine()

    assert "transcription" in cols
    assert "media_path" in cols
    assert "media_type" in cols


# ---------------------------------------------------------------------
# Storage round-trip — untranscribed query + setter
# ---------------------------------------------------------------------


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "stt_store.db"))
    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield tmp_path
    db_mod.dispose_engine()


def _insert_voice_row(owner, *, media_path, media_type="voice", transcription=None):
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage

    row_id = str(uuid.uuid4())
    with get_session() as s:
        s.add(
            WhatsAppMessage(
                id=row_id,
                owner_id=owner,
                message_id=row_id,
                chat_jid="393331234567@s.whatsapp.net",
                sender_jid="393331234567@s.whatsapp.net",
                sender_name="John",
                text="[voice]",
                media_type=media_type,
                media_path=media_path,
                transcription=transcription,
                timestamp=datetime.now(timezone.utc),
                is_from_me=False,
                is_group=False,
            )
        )
    return row_id


def test_untranscribed_voice_roundtrip(fresh_db):
    from zylch.storage.storage import Storage

    owner = "alice@example.com"
    storage = Storage()

    # A voice row with media_path + no transcription appears.
    vid = _insert_voice_row(owner, media_path="/tmp/wa_media/x.ogg")
    # A voice row WITHOUT media_path must NOT appear (history-sync tag).
    _insert_voice_row(owner, media_path=None)
    # A non-audio row must NOT appear.
    _insert_voice_row(owner, media_path="/tmp/wa_media/y.ogg", media_type=None)

    pending = storage.get_untranscribed_voice_messages(owner)
    ids = {r["id"] for r in pending}
    assert vid in ids
    assert len(ids) == 1
    assert pending[0]["media_path"] == "/tmp/wa_media/x.ogg"

    # After setting a transcription it disappears from the pending set.
    storage.set_whatsapp_transcription(owner, vid, "Ciao, ti richiamo domani.")
    assert storage.get_untranscribed_voice_messages(owner) == []

    # And the transcription is surfaced by the unprocessed-messages dict.
    unproc = storage.get_unprocessed_whatsapp_messages(owner)
    by_id = {r["id"]: r for r in unproc}
    assert by_id[vid]["transcription"] == "Ciao, ti richiamo domani."
    assert by_id[vid]["media_type"] == "voice"
    assert by_id[vid]["media_path"] == "/tmp/wa_media/x.ogg"
