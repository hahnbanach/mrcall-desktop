"""Regression tests for ``zylch.whatsapp.sync.WhatsAppSyncService``.

Reproduces the 2026-05-06 bug where ``_store_message_from_event``
read fields off ``info`` directly (``info.Chat``, ``info.Sender``,
``info.PushName``, ``info.IsFromMe``, ``info.IsGroup``) but on real
neonize ``MessageEv`` events those fields live one level deeper on
``info.MessageSource`` (and the push-name field is spelled
``Pushname`` with a lowercase ``n``). The result was 36 rows in
``whatsapp_messages`` for the user with empty ``chat_jid`` /
``sender_jid`` / ``sender_name``, and the WhatsApp tab showed zero
threads even though messages had been received.

Tests use a real ``Neonize_pb2.Message`` event built with populated
``MessageSource``, store it via the real ``WhatsAppSyncService``
against a per-test SQLite file, and assert the row carries the JID
in ``user@server`` form (not the proto debug repr, not an empty
string).
"""

import os
import sys
import uuid
from pathlib import Path

import pytest

# neonize ships its proto bindings as a non-namespaced ``Neonize_pb2``
# module that is only importable from inside ``neonize/proto``. Locate
# that directory via the installed ``neonize`` package and add it to
# sys.path so the test can build real ``MessageEv`` events.
import neonize  # noqa: E402

_NEONIZE_PROTO = Path(neonize.__file__).resolve().parent / "proto"
if _NEONIZE_PROTO.exists() and str(_NEONIZE_PROTO) not in sys.path:
    sys.path.insert(0, str(_NEONIZE_PROTO))


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Per-test SQLite DB at a tmp path. Disposes the engine on teardown."""
    db_path = tmp_path / "wa_test.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))

    # Re-import database fresh so the singleton picks up the new env var.
    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield db_path
    db_mod.dispose_engine()


def _build_message_event(
    msg_id: str = "TEST123",
    chat_user: str = "393281234567",
    chat_server: str = "s.whatsapp.net",
    sender_user: str | None = None,
    sender_server: str | None = None,
    push_name: str = "Test Sender",
    text: str = "hello",
    is_from_me: bool = False,
    is_group: bool = False,
    timestamp_seconds: int = 1_700_000_000,
):
    """Build a real Neonize_pb2.Message (= MessageEv) with populated fields.

    Mirrors the shape neonize delivers to ``on_message`` callbacks.
    """
    import Neonize_pb2 as N

    ev = N.Message()
    ev.Info.ID = msg_id
    ev.Info.Pushname = push_name  # lowercase 'n' — that is the proto field name
    ev.Info.Timestamp = timestamp_seconds

    src = ev.Info.MessageSource
    src.Chat.User = chat_user
    src.Chat.Server = chat_server
    src.Sender.User = sender_user if sender_user is not None else chat_user
    src.Sender.Server = sender_server if sender_server is not None else chat_server
    src.IsFromMe = is_from_me
    src.IsGroup = is_group

    ev.Message.conversation = text
    return ev


def test_store_message_populates_chat_jid(fresh_db):
    """A real MessageEv with populated MessageSource must land with a
    real ``user@server`` chat_jid in the DB — not an empty string and
    not the proto debug repr (``'User: "..."\\nServer: "..."\\n'``)."""
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage
    from zylch.whatsapp.sync import WhatsAppSyncService

    owner_id = "test@example.com"
    sync = WhatsAppSyncService(storage=None, owner_id=owner_id)

    ev = _build_message_event(
        msg_id=uuid.uuid4().hex.upper(),
        chat_user="393281234567",
        chat_server="s.whatsapp.net",
        sender_user="393281234567",
        sender_server="s.whatsapp.net",
        push_name="Mario",
        text="ciao",
        is_from_me=False,
        is_group=False,
    )

    stored = sync._store_message_from_event(ev)
    assert stored is True, "sync should store a populated MessageEv"

    with get_session() as session:
        rows = (
            session.query(WhatsAppMessage)
            .filter(WhatsAppMessage.owner_id == owner_id)
            .all()
        )
    assert len(rows) == 1
    row = rows[0]

    assert row.chat_jid == "393281234567@s.whatsapp.net", (
        f"chat_jid should be user@server format, got {row.chat_jid!r}"
    )
    assert row.sender_jid == "393281234567@s.whatsapp.net"
    assert row.sender_name == "Mario"
    assert row.text == "ciao"
    assert row.is_from_me is False
    assert row.is_group is False


def test_store_group_message_marks_is_group(fresh_db):
    """A group event (chat server == g.us, IsGroup=True) must round-trip."""
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage
    from zylch.whatsapp.sync import WhatsAppSyncService

    owner_id = "test@example.com"
    sync = WhatsAppSyncService(storage=None, owner_id=owner_id)

    ev = _build_message_event(
        msg_id=uuid.uuid4().hex.upper(),
        chat_user="120363xxxxxx",
        chat_server="g.us",
        sender_user="393281234567",
        sender_server="s.whatsapp.net",
        is_group=True,
    )
    assert sync._store_message_from_event(ev) is True

    with get_session() as session:
        row = (
            session.query(WhatsAppMessage)
            .filter(WhatsAppMessage.owner_id == owner_id)
            .one()
        )
    assert row.chat_jid == "120363xxxxxx@g.us"
    assert row.is_group is True
    # Sender on a group is the participant, not the chat itself.
    assert row.sender_jid == "393281234567@s.whatsapp.net"


def test_store_outbound_message_marks_is_from_me(fresh_db):
    """An outbound MessageEv (IsFromMe=True) must land with the flag set."""
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage
    from zylch.whatsapp.sync import WhatsAppSyncService

    owner_id = "test@example.com"
    sync = WhatsAppSyncService(storage=None, owner_id=owner_id)

    ev = _build_message_event(
        msg_id=uuid.uuid4().hex.upper(),
        is_from_me=True,
        text="from me",
    )
    assert sync._store_message_from_event(ev) is True

    with get_session() as session:
        row = (
            session.query(WhatsAppMessage)
            .filter(WhatsAppMessage.owner_id == owner_id)
            .one()
        )
    assert row.is_from_me is True
    assert row.text == "from me"


def test_store_message_dedups_by_message_id(fresh_db):
    """Re-storing the same MessageEv (same ID) is a no-op (idempotent)."""
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage
    from zylch.whatsapp.sync import WhatsAppSyncService

    owner_id = "test@example.com"
    sync = WhatsAppSyncService(storage=None, owner_id=owner_id)

    msg_id = uuid.uuid4().hex.upper()
    ev1 = _build_message_event(msg_id=msg_id, text="first")
    ev2 = _build_message_event(msg_id=msg_id, text="second")

    assert sync._store_message_from_event(ev1) is True
    assert sync._store_message_from_event(ev2) is False  # already stored

    with get_session() as session:
        rows = (
            session.query(WhatsAppMessage)
            .filter(WhatsAppMessage.owner_id == owner_id)
            .all()
        )
    assert len(rows) == 1
    assert rows[0].text == "first"


def test_outbound_devicesent_message_extracts_text(fresh_db):
    """A message sent from the user's PHONE gets echoed to the linked
    desktop wrapped in ``deviceSentMessage.message``. ``_extract_text``
    must unwrap that envelope and pull the text from the inner Message,
    otherwise ``is_from_me=True`` rows land with ``text=NULL`` (the
    ``[empty]`` bubbles seen on `mario.alemi@gmail.com` 2026-05-06)."""
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage
    from zylch.whatsapp.sync import WhatsAppSyncService
    import Neonize_pb2 as N

    owner_id = "test@example.com"
    sync = WhatsAppSyncService(storage=None, owner_id=owner_id)

    ev = N.Message()
    ev.Info.ID = uuid.uuid4().hex.upper()
    ev.Info.Pushname = "Self"
    ev.Info.Timestamp = 1_700_000_000
    src = ev.Info.MessageSource
    src.Chat.User = "393281234567"
    src.Chat.Server = "s.whatsapp.net"
    src.Sender.User = "393999999999"  # the user's own JID
    src.Sender.Server = "s.whatsapp.net"
    src.IsFromMe = True
    src.IsGroup = False

    # outbound text wrapped in deviceSentMessage
    inner = ev.Message.deviceSentMessage.message
    inner.conversation = "ciao io a te stesso"
    ev.Message.deviceSentMessage.destinationJID = "393281234567@s.whatsapp.net"

    assert sync._store_message_from_event(ev) is True
    with get_session() as session:
        row = (
            session.query(WhatsAppMessage)
            .filter(WhatsAppMessage.owner_id == owner_id)
            .one()
        )
    assert row.is_from_me is True
    assert row.text == "ciao io a te stesso", (
        f"deviceSentMessage text not unwrapped: row.text={row.text!r}"
    )


def test_ephemeral_extended_text_extracts_text(fresh_db):
    """A disappearing extendedTextMessage arrives wrapped in
    ``ephemeralMessage.message``. ``_extract_text`` must unwrap and
    pick up ``extendedTextMessage.text`` from the inner Message."""
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage
    from zylch.whatsapp.sync import WhatsAppSyncService
    import Neonize_pb2 as N

    owner_id = "test@example.com"
    sync = WhatsAppSyncService(storage=None, owner_id=owner_id)

    ev = _build_message_event(
        msg_id=uuid.uuid4().hex.upper(), text="placeholder ignored",
    )
    # Replace the conversation payload with an ephemeral wrapper.
    ev.Message.Clear()
    inner = ev.Message.ephemeralMessage.message
    inner.extendedTextMessage.text = "messaggio effimero"

    assert sync._store_message_from_event(ev) is True
    with get_session() as session:
        row = (
            session.query(WhatsAppMessage)
            .filter(WhatsAppMessage.owner_id == owner_id)
            .one()
        )
    assert row.text == "messaggio effimero"


def _build_event_with_message_kind(kind: str, populate, msg_id: str | None = None):
    """Build a MessageEv with the given inner Message kind populated.

    ``populate(msg)`` runs against the inner ``Message`` proto and
    sets whatever sub-message / fields the test cares about.
    """
    import Neonize_pb2 as N

    ev = N.Message()
    ev.Info.ID = msg_id or uuid.uuid4().hex.upper()
    ev.Info.Pushname = "Tester"
    ev.Info.Timestamp = 1_700_000_000
    src = ev.Info.MessageSource
    src.Chat.User = "393281234567"
    src.Chat.Server = "s.whatsapp.net"
    src.Sender.User = "393281234567"
    src.Sender.Server = "s.whatsapp.net"
    src.IsFromMe = False
    src.IsGroup = False
    populate(ev.Message)
    return ev


def _stored_text(sync, owner_id, ev):
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage

    assert sync._store_message_from_event(ev) is True
    with get_session() as session:
        row = (
            session.query(WhatsAppMessage)
            .filter(
                WhatsAppMessage.owner_id == owner_id,
                WhatsAppMessage.message_id == ev.Info.ID,
            )
            .one()
        )
    return row.text


def test_image_without_caption_renders_image_placeholder(fresh_db):
    from zylch.whatsapp.sync import WhatsAppSyncService

    owner = "test@example.com"
    sync = WhatsAppSyncService(storage=None, owner_id=owner)
    ev = _build_event_with_message_kind(
        "imageMessage",
        lambda m: m.imageMessage.SetInParent(),
    )
    assert _stored_text(sync, owner, ev) == "[image]"


def test_image_with_caption_renders_caption(fresh_db):
    from zylch.whatsapp.sync import WhatsAppSyncService

    owner = "test@example.com"
    sync = WhatsAppSyncService(storage=None, owner_id=owner)

    def populate(m):
        m.imageMessage.caption = "gatto che dorme"

    ev = _build_event_with_message_kind("imageMessage", populate)
    assert _stored_text(sync, owner, ev) == "[image] gatto che dorme"


def test_voice_note_renders_voice_placeholder(fresh_db):
    from zylch.whatsapp.sync import WhatsAppSyncService

    owner = "test@example.com"
    sync = WhatsAppSyncService(storage=None, owner_id=owner)

    def populate(m):
        m.audioMessage.PTT = True  # push-to-talk = voice note
        m.audioMessage.seconds = 7

    ev = _build_event_with_message_kind("audioMessage", populate)
    assert _stored_text(sync, owner, ev) == "[voice]"


def test_audio_file_renders_audio_placeholder(fresh_db):
    from zylch.whatsapp.sync import WhatsAppSyncService

    owner = "test@example.com"
    sync = WhatsAppSyncService(storage=None, owner_id=owner)

    def populate(m):
        m.audioMessage.PTT = False
        m.audioMessage.seconds = 60

    ev = _build_event_with_message_kind("audioMessage", populate)
    assert _stored_text(sync, owner, ev) == "[audio]"


def test_sticker_renders_sticker_placeholder(fresh_db):
    from zylch.whatsapp.sync import WhatsAppSyncService

    owner = "test@example.com"
    sync = WhatsAppSyncService(storage=None, owner_id=owner)
    ev = _build_event_with_message_kind(
        "stickerMessage",
        lambda m: m.stickerMessage.SetInParent(),
    )
    assert _stored_text(sync, owner, ev) == "[sticker]"


def test_poll_creation_renders_question(fresh_db):
    from zylch.whatsapp.sync import WhatsAppSyncService

    owner = "test@example.com"
    sync = WhatsAppSyncService(storage=None, owner_id=owner)

    def populate(m):
        m.pollCreationMessageV3.name = "Pizza o sushi?"

    ev = _build_event_with_message_kind("pollCreationMessageV3", populate)
    assert _stored_text(sync, owner, ev) == "[poll: Pizza o sushi?]"


def test_location_renders_location_placeholder(fresh_db):
    from zylch.whatsapp.sync import WhatsAppSyncService

    owner = "test@example.com"
    sync = WhatsAppSyncService(storage=None, owner_id=owner)
    ev = _build_event_with_message_kind(
        "locationMessage",
        lambda m: m.locationMessage.SetInParent(),
    )
    assert _stored_text(sync, owner, ev) == "[location]"


def test_document_with_filename(fresh_db):
    from zylch.whatsapp.sync import WhatsAppSyncService

    owner = "test@example.com"
    sync = WhatsAppSyncService(storage=None, owner_id=owner)

    def populate(m):
        m.documentMessage.fileName = "contratto.pdf"

    ev = _build_event_with_message_kind("documentMessage", populate)
    assert _stored_text(sync, owner, ev) == "[document: contratto.pdf]"


def test_protocol_message_returns_none(fresh_db):
    """System-level proto messages stay invisible — they aren't user content."""
    from zylch.whatsapp.sync import WhatsAppSyncService

    owner = "test@example.com"
    sync = WhatsAppSyncService(storage=None, owner_id=owner)
    ev = _build_event_with_message_kind(
        "protocolMessage",
        lambda m: m.protocolMessage.SetInParent(),
    )
    assert _stored_text(sync, owner, ev) is None


def test_list_threads_filter_accepts_real_chat_jid(fresh_db):
    """End-to-end: a populated MessageEv stored via the real sync
    service must show up in ``whatsapp.list_threads`` (the filter
    must NOT reject ``user@s.whatsapp.net`` rows)."""
    import asyncio

    from zylch.rpc.whatsapp_actions import whatsapp_list_threads
    from zylch.whatsapp.sync import WhatsAppSyncService

    owner_id = "test@example.com"
    # whatsapp_list_threads resolves owner_id from settings via
    # cli/utils — point it at our test owner via env.
    os.environ["EMAIL_ADDRESS"] = owner_id

    sync = WhatsAppSyncService(storage=None, owner_id=owner_id)
    ev = _build_message_event(
        msg_id=uuid.uuid4().hex.upper(),
        chat_user="393281234567",
        chat_server="s.whatsapp.net",
    )
    assert sync._store_message_from_event(ev) is True

    out = asyncio.run(
        whatsapp_list_threads({"limit": 10, "offset": 0}, notify=lambda *a, **k: None)
    )
    assert out["total_messages"] == 1
    assert out["owner_id"] == owner_id
    assert len(out["threads"]) == 1, f"expected one thread, got {out!r}"
    assert out["threads"][0]["jid"] == "393281234567@s.whatsapp.net"
