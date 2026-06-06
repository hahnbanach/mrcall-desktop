"""Voice-aware memory gate (2026-05-20).

A transcribed voice note is signal even when short, so
``process_whatsapp_message`` must NOT drop it via the <20-char text gate
that still applies to plain text. These tests lock both halves of that
contract with the LLM client + extractor mocked (storage is real against
an in-memory SQLite via ``fresh_db``).
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "voice_memory_test.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))
    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield db_path
    db_mod.dispose_engine()


def _make_wa_row(
    owner: str,
    *,
    text: str,
    media_type=None,
    media_path=None,
    transcription=None,
) -> str:
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
                text=text,
                media_type=media_type,
                media_path=media_path,
                transcription=transcription,
                timestamp=datetime.now(timezone.utc),
                is_from_me=False,
                is_group=False,
            )
        )
    return row_id


def _make_worker(owner: str):
    """MemoryWorker with LLM client + merge + extractor mocked."""
    from zylch.workers import memory as mem_mod

    fake_client = MagicMock()
    with patch.object(mem_mod, "make_llm_client", return_value=fake_client):
        worker = mem_mod.MemoryWorker(
            storage=__import__("zylch.storage", fromlist=["Storage"]).Storage(),
            owner_id=owner,
        )
    worker.llm_merge = MagicMock()
    worker._custom_prompt = "FAKE PROMPT"
    worker._custom_prompt_loaded = True
    worker._extract_entities_for_message = MagicMock()
    return worker


# ---------------------------------------------------------------------
# Short transcribed voice note → NOT dropped
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_voice_transcription_is_not_dropped(fresh_db):
    owner = "alice@example.com"
    wa_id = _make_wa_row(
        owner,
        text="[voice]",
        media_type="voice",
        media_path="/tmp/wa_media/x.ogg",
        transcription="Richiamami",
    )

    worker = _make_worker(owner)
    # Extractor returns empty so we don't need the full upsert chain; what
    # matters is that the short-text gate did NOT short-circuit before it.
    worker._extract_entities_for_message.return_value = []

    ok = await worker.process_whatsapp_message(
        {
            "id": wa_id,
            "text": "[voice]",
            "media_type": "voice",
            "transcription": "Richiamami",
            "sender_jid": "393331234567@s.whatsapp.net",
            "sender_name": "John",
            "timestamp": "2026-05-20T10:00:00+00:00",
            "is_from_me": False,
            "is_group": False,
        }
    )
    assert ok is True
    # The gate let it through to extraction (a deliberate voice note is signal).
    worker._extract_entities_for_message.assert_called_once()


# ---------------------------------------------------------------------
# Short plain text → still dropped
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_plain_text_still_skipped(fresh_db):
    owner = "alice@example.com"
    wa_id = _make_wa_row(owner, text="ok")

    worker = _make_worker(owner)
    worker._extract_entities_for_message.return_value = []

    ok = await worker.process_whatsapp_message(
        {
            "id": wa_id,
            "text": "ok",
            "sender_jid": "393331234567@s.whatsapp.net",
            "sender_name": "John",
            "timestamp": "2026-05-20T10:00:00+00:00",
            "is_from_me": False,
            "is_group": False,
        }
    )
    assert ok is True
    # Plain short text keeps the <20 skip — extractor never called.
    worker._extract_entities_for_message.assert_not_called()


# ---------------------------------------------------------------------
# Envelope uses the transcription as the body
# ---------------------------------------------------------------------


def test_format_whatsapp_data_uses_transcription_as_body(fresh_db):
    from zylch.storage.storage import Storage
    from zylch.workers.memory import MemoryWorker

    worker = MemoryWorker.__new__(MemoryWorker)
    worker.storage = Storage()
    worker.owner_id = "alice@example.com"

    out = worker._format_whatsapp_data(
        {
            "sender_jid": "393331234567@s.whatsapp.net",
            "sender_name": "John",
            "timestamp": "2026-05-20T10:00:00+00:00",
            "text": "[voice]",
            "transcription": "Ciao Alex, ti richiamo domani per il preventivo.",
        }
    )
    assert "Ciao Alex, ti richiamo domani per il preventivo." in out
    assert "[voice]" not in out  # the placeholder must not leak into the envelope
