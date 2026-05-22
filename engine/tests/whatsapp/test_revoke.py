"""Tests for WhatsApp "delete for everyone" (revoke) handling.

When a WhatsApp message is deleted for everyone, the sender's phone
sends a ``MessageEv`` whose inner ``Message`` carries a
``protocolMessage`` with ``type == REVOKE`` and a ``key`` naming the
TARGET message. Before this feature the engine ignored revokes, so a
recalled secret (e.g. an SSH private key the sender deleted) persisted
in the local store forever.

These tests build REAL ``Neonize_pb2.Message`` events (same approach as
``test_sync.py``) so they exercise the actual protobuf field shapes
(``protocolMessage.type`` / ``protocolMessage.key.ID``, uppercase casing
on the live event path) rather than a hand-rolled fake.

Proto facts (neonize 0.3.17, verified by introspection):
  * ``Message.protocolMessage`` — field, camelCase.
  * ``WAWebProtobufsE2E.ProtocolMessage.Type.REVOKE == 0``.
  * ``protocolMessage.key`` fields: ``ID``, ``remoteJID``, ``fromMe``,
    ``participant`` (uppercase on the live ``MessageEv`` path).

CAVEAT: this only covers "delete for everyone" (revoke). "Delete for
me" sends NO network event and is undetectable. Live verification
(actually deleting a real WhatsApp message and confirming the row
vanishes) is NOT done here — see the harness report.
"""

import sys
import uuid
from pathlib import Path

import pytest

# neonize ships its proto bindings as a non-namespaced ``Neonize_pb2``
# module importable only from inside ``neonize/proto``. Mirror test_sync.py.
import neonize  # noqa: E402

_NEONIZE_PROTO = Path(neonize.__file__).resolve().parent / "proto"
if _NEONIZE_PROTO.exists() and str(_NEONIZE_PROTO) not in sys.path:
    sys.path.insert(0, str(_NEONIZE_PROTO))


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Per-test SQLite DB at a tmp path. Disposes the engine on teardown."""
    db_path = tmp_path / "wa_revoke_test.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))

    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield db_path
    db_mod.dispose_engine()


def _build_text_event(msg_id: str, text: str = "hello"):
    """A normal inbound text MessageEv with a populated MessageSource."""
    import Neonize_pb2 as N

    ev = N.Message()
    ev.Info.ID = msg_id
    ev.Info.Pushname = "Mario"
    ev.Info.Timestamp = 1_700_000_000
    src = ev.Info.MessageSource
    src.Chat.User = "393281234567"
    src.Chat.Server = "s.whatsapp.net"
    src.Sender.User = "393281234567"
    src.Sender.Server = "s.whatsapp.net"
    src.IsFromMe = False
    src.IsGroup = False
    ev.Message.conversation = text
    return ev


def _build_revoke_event(target_id: str, evt_id: str | None = None):
    """A "delete for everyone" MessageEv targeting ``target_id``.

    The revoke is itself a distinct message (its own ``Info.ID``) whose
    inner Message carries ``protocolMessage{type=REVOKE, key.ID=target}``.
    """
    import Neonize_pb2 as N

    ev = N.Message()
    ev.Info.ID = evt_id or uuid.uuid4().hex.upper()
    ev.Info.Pushname = "Mario"
    ev.Info.Timestamp = 1_700_000_100
    src = ev.Info.MessageSource
    src.Chat.User = "393281234567"
    src.Chat.Server = "s.whatsapp.net"
    src.Sender.User = "393281234567"
    src.Sender.Server = "s.whatsapp.net"
    src.IsFromMe = False
    src.IsGroup = False

    pm = ev.Message.protocolMessage
    pm.type = 0  # ProtocolMessage.Type.REVOKE
    pm.key.ID = target_id
    pm.key.remoteJID = "393281234567@s.whatsapp.net"
    pm.key.fromMe = False
    return ev


def _count_rows(owner_id: str) -> int:
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage

    with get_session() as session:
        return session.query(WhatsAppMessage).filter(WhatsAppMessage.owner_id == owner_id).count()


def test_revoke_deletes_target_and_stores_no_revoke_row(fresh_db):
    """A stored message + a revoke targeting it → target row gone, and
    the revoke itself is NOT stored as a new row."""
    from zylch.storage.storage import Storage
    from zylch.whatsapp.sync import WhatsAppSyncService

    owner = "test@example.com"
    storage = Storage()
    sync = WhatsAppSyncService(storage=storage, owner_id=owner)

    target_id = uuid.uuid4().hex.upper()
    assert sync.handle_message(_build_text_event(target_id, "secret ssh key")) is True
    assert _count_rows(owner) == 1

    revoke = _build_revoke_event(target_id)
    handled = sync.handle_message(revoke)
    assert handled is True, "revoke must be reported as handled"

    # Target gone AND no revoke row added: zero rows remain.
    assert _count_rows(owner) == 0, "revoke should delete target and store nothing"


def test_normal_message_still_stored(fresh_db):
    """A non-revoke message is stored unchanged (guard must not eat it)."""
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage
    from zylch.storage.storage import Storage
    from zylch.whatsapp.sync import WhatsAppSyncService

    owner = "test@example.com"
    sync = WhatsAppSyncService(storage=Storage(), owner_id=owner)

    msg_id = uuid.uuid4().hex.upper()
    assert sync.handle_message(_build_text_event(msg_id, "ciao")) is True

    with get_session() as session:
        row = session.query(WhatsAppMessage).filter(WhatsAppMessage.owner_id == owner).one()
    assert row.text == "ciao"
    assert row.chat_jid == "393281234567@s.whatsapp.net"


def test_revoke_for_unknown_target_is_noop(fresh_db):
    """A revoke for a target we never stored deletes 0 rows and does not
    raise — it is still reported handled (we still drop the revoke)."""
    from zylch.storage.storage import Storage
    from zylch.whatsapp.sync import WhatsAppSyncService

    owner = "test@example.com"
    sync = WhatsAppSyncService(storage=Storage(), owner_id=owner)

    revoke = _build_revoke_event("NEVER_SEEN_THIS_ID")
    assert sync.handle_message(revoke) is True
    assert _count_rows(owner) == 0


def test_storage_delete_removes_row_and_blob_link(fresh_db):
    """Storage unit: delete_whatsapp_message_by_message_id removes the
    message row AND its whatsapp_blobs link, returning the row count."""
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob, WhatsAppBlob, WhatsAppMessage
    from zylch.storage.storage import Storage

    owner = "test@example.com"
    storage = Storage()

    # Insert a message, a blob, and a link between them. We need the
    # engine UUID id of the message to wire the FK.
    protocol_id = "WIRE_MSG_ID_42"
    engine_id = None
    blob_id = uuid.uuid4().hex
    with get_session() as session:
        msg = WhatsAppMessage(
            owner_id=owner,
            message_id=protocol_id,
            chat_jid="393281234567@s.whatsapp.net",
            sender_jid="393281234567@s.whatsapp.net",
            text="has a blob",
            timestamp=__import__("datetime").datetime(2024, 1, 1),
        )
        session.add(msg)
        session.flush()
        engine_id = msg.id
        session.add(Blob(id=blob_id, owner_id=owner, namespace="person", content="blob body"))
        session.add(
            WhatsAppBlob(
                whatsapp_message_id=engine_id,
                blob_id=blob_id,
                owner_id=owner,
            )
        )

    # Sanity: the link exists.
    with get_session() as session:
        assert (
            session.query(WhatsAppBlob)
            .filter(WhatsAppBlob.whatsapp_message_id == engine_id)
            .count()
            == 1
        )

    deleted = storage.delete_whatsapp_message_by_message_id(owner, protocol_id)
    assert deleted == 1, "should report exactly one message row deleted"

    with get_session() as session:
        assert (
            session.query(WhatsAppMessage).filter(WhatsAppMessage.message_id == protocol_id).count()
            == 0
        )
        # No orphan blob-link row left behind.
        assert (
            session.query(WhatsAppBlob)
            .filter(WhatsAppBlob.whatsapp_message_id == engine_id)
            .count()
            == 0
        )

    # Deleting again is a clean no-op.
    assert storage.delete_whatsapp_message_by_message_id(owner, protocol_id) == 0
