"""WhatsApp sync service — stores messages and contacts in SQLite.

Analogous to zylch/tools/email_sync.py for email.
Handles HistorySyncEv (initial) and MessageEv (ongoing).
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Dict, Optional

from zylch.storage.database import get_session

logger = logging.getLogger(__name__)


class WhatsAppSyncService:
    """Sync WhatsApp messages and contacts to local SQLite.

    Usage:
        sync = WhatsAppSyncService(storage, owner_id)
        wa_client.on_message(sync.handle_message)
        wa_client.on_history_sync(sync.handle_history_sync)
        wa_client.connect()
    """

    def __init__(self, storage, owner_id: str):
        self.storage = storage
        self.owner_id = owner_id
        self._messages_synced = 0
        self._contacts_synced = 0
        self._db_lock = threading.Lock()

    # -- History sync (initial connect) --------------------------------

    def handle_history_sync(self, event) -> int:
        """Process HistorySyncEv — initial history download.

        Called by neonize when WhatsApp pushes past conversations
        on first device link.

        Returns:
            Number of messages stored.
        """
        count = 0
        try:
            data = event.data if hasattr(event, "data") else event
            conversations = data.conversations if hasattr(data, "conversations") else []
            logger.info(f"[wa-sync] history sync: {len(conversations)}" " conversations")

            for conv in conversations:
                messages = conv.messages if hasattr(conv, "messages") else []
                for msg_wrapper in messages:
                    msg = msg_wrapper.message if hasattr(msg_wrapper, "message") else msg_wrapper
                    stored = self._store_message_from_proto(msg)
                    if stored:
                        count += 1

            self._messages_synced += count
            logger.info(f"[wa-sync] history sync complete:" f" {count} messages stored")
        except Exception as e:
            logger.error(f"[wa-sync] history sync error: {e}")
        return count

    # -- Real-time messages --------------------------------------------

    def handle_message(self, event) -> bool:
        """Process MessageEv — single incoming/outgoing message.

        Returns:
            True if message was stored.
        """
        try:
            stored = self._store_message_from_event(event)
            if stored:
                self._messages_synced += 1
            return stored
        except Exception as e:
            logger.error(f"[wa-sync] message handler error: {e}")
            return False

    # -- Contact sync --------------------------------------------------

    def sync_contacts(self, wa_client=None) -> int:
        """Extract contacts from synced WhatsApp messages.

        neonize doesn't have a "get all contacts" API, so we
        derive contacts from messages already stored in DB.

        Returns:
            Number of contacts upserted.
        """
        from sqlalchemy import func

        from zylch.storage.models import (
            WhatsAppContact,
            WhatsAppMessage,
        )

        count = 0
        try:
            with self._db_lock, get_session() as session:
                # Get distinct chat JIDs from messages (non-group, not from me)
                rows = (
                    session.query(
                        WhatsAppMessage.chat_jid,
                        WhatsAppMessage.sender_name,
                        func.max(WhatsAppMessage.timestamp),
                    )
                    .filter(
                        WhatsAppMessage.owner_id == self.owner_id,
                        WhatsAppMessage.is_group.is_(False),
                        WhatsAppMessage.is_from_me.is_(False),
                    )
                    .group_by(WhatsAppMessage.chat_jid)
                    .all()
                )

                for jid_str, sender_name, last_ts in rows:
                    if not jid_str:
                        continue
                    phone = _jid_to_phone(jid_str)

                    existing = (
                        session.query(WhatsAppContact)
                        .filter_by(
                            owner_id=self.owner_id,
                            jid=str(jid_str),
                        )
                        .first()
                    )

                    if existing:
                        if sender_name:
                            existing.push_name = sender_name
                        existing.last_message_at = last_ts
                        existing.synced_at = datetime.now(
                            timezone.utc,
                        )
                    else:
                        new_contact = WhatsAppContact(
                            owner_id=self.owner_id,
                            jid=str(jid_str),
                            phone_number=phone,
                            push_name=sender_name,
                            synced_at=datetime.now(
                                timezone.utc,
                            ),
                        )
                        session.add(new_contact)
                    count += 1

            self._contacts_synced = count
            logger.info(f"[wa-sync] contacts synced: {count}")
        except Exception as e:
            logger.error(
                f"[wa-sync] contact sync error: {e}",
            )
            count = 0
        return count

    # -- Group name sync ----------------------------------------------

    def sync_groups(self, wa_client) -> int:
        """Persist joined-group names to ``whatsapp_contacts`` so the
        renderer can show the group's actual title instead of the last
        sender's name. Group JIDs are stored as the row key (no
        per-person contact ever has a ``@g.us`` JID, so the namespace
        does not collide).

        Returns the number of groups upserted.
        """
        from zylch.storage.models import WhatsAppContact

        try:
            groups = list(wa_client.get_joined_groups() or [])
        except Exception as e:
            logger.warning(f"[wa-sync] get_joined_groups failed: {e}")
            return 0

        count = 0
        try:
            with self._db_lock, get_session() as session:
                for g in groups:
                    try:
                        jid_obj = getattr(g, "JID", None)
                        user = getattr(jid_obj, "User", "") if jid_obj else ""
                        server = getattr(jid_obj, "Server", "") if jid_obj else ""
                        if not user:
                            continue
                        jid = f"{user}@{server or 'g.us'}"
                        gname_obj = getattr(g, "GroupName", None)
                        name = (getattr(gname_obj, "Name", "") or "").strip()
                        if not name:
                            continue

                        existing = (
                            session.query(WhatsAppContact)
                            .filter_by(owner_id=self.owner_id, jid=jid)
                            .first()
                        )
                        if existing:
                            existing.name = name
                            existing.synced_at = datetime.now(timezone.utc)
                        else:
                            session.add(
                                WhatsAppContact(
                                    owner_id=self.owner_id,
                                    jid=jid,
                                    phone_number=None,
                                    name=name,
                                    synced_at=datetime.now(timezone.utc),
                                )
                            )
                        count += 1
                    except Exception as e:
                        logger.warning(
                            f"[wa-sync] group upsert error: {e}",
                        )
                        continue
            logger.info(f"[wa-sync] groups synced: {count}")
        except Exception as e:
            logger.error(
                f"[wa-sync] sync_groups error: {e}",
            )
            count = 0
        return count

    # -- Full sync (contacts + wait for history) -----------------------

    def full_sync(self, wa_client) -> Dict[str, int]:
        """Run full sync: contacts + message count.

        Call after wa_client.connect() and initial history
        sync events have been processed.

        Returns:
            Dict with contacts and messages counts.
        """
        contacts = self.sync_contacts(wa_client)
        return {
            "contacts": contacts,
            "messages": self._messages_synced,
        }

    # -- Internal: store messages --------------------------------------

    def _store_message_from_event(self, event) -> bool:
        """Store a single MessageEv into whatsapp_messages.

        ``MessageEv.Info`` is a ``MessageInfo`` proto whose JID-bearing
        fields (Chat, Sender, IsFromMe, IsGroup) live one level deeper
        on the nested ``MessageSource``. The push-name field is spelled
        ``Pushname`` (lowercase ``n``), not ``PushName``. Reading them
        off ``info`` directly silently falls through to the default and
        produces empty rows — that is why 36 messages stored with empty
        ``chat_jid`` until 2026-05-06.
        """

        try:
            info = event.Info if hasattr(event, "Info") else event
            message = event.Message if hasattr(event, "Message") else event

            # Extract fields from protobuf
            msg_id = str(info.ID if hasattr(info, "ID") else "")
            if not msg_id:
                return False

            src = info.MessageSource if hasattr(info, "MessageSource") else None
            chat_jid = _format_jid(getattr(src, "Chat", None)) if src is not None else ""
            sender_jid = _format_jid(getattr(src, "Sender", None)) if src is not None else ""
            is_from_me = bool(getattr(src, "IsFromMe", False)) if src is not None else False
            is_group = bool(getattr(src, "IsGroup", False)) if src is not None else False
            timestamp = _extract_timestamp(info)
            text = _extract_text(message)
            sender_name = str(info.Pushname) if hasattr(info, "Pushname") else ""

            return self._upsert_message(
                msg_id=msg_id,
                chat_jid=chat_jid,
                sender_jid=sender_jid,
                sender_name=sender_name,
                text=text,
                timestamp=timestamp,
                is_from_me=is_from_me,
                is_group=is_group,
            )
        except Exception as e:
            logger.warning(f"[wa-sync] could not store event message: {e}")
            return False

    def _store_message_from_proto(self, msg) -> bool:
        """Store a message from history sync protobuf."""

        try:
            key = msg.key if hasattr(msg, "key") else None
            if not key:
                return False

            msg_id = str(key.id) if hasattr(key, "id") else ""
            if not msg_id:
                return False

            chat_jid = str(key.remoteJid if hasattr(key, "remoteJid") else "")
            is_from_me = bool(key.fromMe if hasattr(key, "fromMe") else False)
            sender_jid = (
                str(key.participant)
                if hasattr(key, "participant") and key.participant
                else chat_jid
            )

            inner = msg.message if hasattr(msg, "message") else msg
            text = _extract_text(inner)
            timestamp = _extract_timestamp_from_int(
                msg.messageTimestamp if hasattr(msg, "messageTimestamp") else 0
            )
            sender_name = str(msg.pushName if hasattr(msg, "pushName") else "")

            return self._upsert_message(
                msg_id=msg_id,
                chat_jid=chat_jid,
                sender_jid=sender_jid if not is_from_me else "me",
                sender_name=sender_name,
                text=text,
                timestamp=timestamp,
                is_from_me=is_from_me,
                is_group="@g.us" in chat_jid,
            )
        except Exception as e:
            logger.warning(f"[wa-sync] could not store proto message: {e}")
            return False

    def _upsert_message(
        self,
        msg_id: str,
        chat_jid: str,
        sender_jid: str,
        sender_name: str,
        text: Optional[str],
        timestamp: Optional[datetime],
        is_from_me: bool,
        is_group: bool,
    ) -> bool:
        """Insert or skip a message in whatsapp_messages."""
        from zylch.storage.models import WhatsAppMessage

        if not msg_id:
            return False

        try:
            with self._db_lock, get_session() as session:
                existing = session.query(WhatsAppMessage).filter_by(message_id=msg_id).first()
                if existing:
                    return False  # Already stored

                new_msg = WhatsAppMessage(
                    owner_id=self.owner_id,
                    message_id=msg_id,
                    chat_jid=chat_jid,
                    sender_jid=sender_jid,
                    sender_name=sender_name or None,
                    text=text,
                    timestamp=timestamp or datetime.now(timezone.utc),
                    is_from_me=is_from_me,
                    is_group=is_group,
                )
                session.add(new_msg)
            return True
        except Exception as e:
            logger.warning(f"[wa-sync] upsert error: {e}")
            return False

    @property
    def stats(self) -> Dict[str, int]:
        """Return sync statistics."""
        return {
            "messages_synced": self._messages_synced,
            "contacts_synced": self._contacts_synced,
        }


# -- Helpers -----------------------------------------------------------


# Wrappers used by WhatsApp's E2E protocol that nest the *real* Message
# under their own ``.message`` field. Without unwrapping these, outbound
# messages (echoed from the user's phone via ``deviceSentMessage``),
# disappearing messages, view-once and edited messages all stored with
# ``text=NULL`` and rendered as "[empty]" bubbles in the WhatsApp tab.
_E2E_WRAPPER_FIELDS = (
    "deviceSentMessage",
    "ephemeralMessage",
    "viewOnceMessage",
    "viewOnceMessageV2",
    "viewOnceMessageV2Extension",
    "editedMessage",
    "documentWithCaptionMessage",
)


def _unwrap_message(message):
    """Descend through E2E wrapper messages to the inner content.

    ``deviceSentMessage``, ``ephemeralMessage``, ``viewOnceMessage*``,
    ``editedMessage``, and ``documentWithCaptionMessage`` all carry the
    actual message proto on a nested ``.message`` field. Walk down up
    to ``MAX_DEPTH`` levels (in practice ephemeral can wrap view-once,
    or edited can wrap ephemeral, etc.) and return the leaf Message.
    Returns the input unchanged if no wrapper is present.
    """
    MAX_DEPTH = 5
    for _ in range(MAX_DEPTH):
        if message is None:
            return None
        descended = False
        for wrapper in _E2E_WRAPPER_FIELDS:
            try:
                has_wrapper = message.HasField(wrapper)
            except (ValueError, AttributeError):
                continue
            if not has_wrapper:
                continue
            sub = getattr(message, wrapper, None)
            if sub is None:
                continue
            try:
                if not sub.HasField("message"):
                    continue
            except (ValueError, AttributeError):
                continue
            message = sub.message
            descended = True
            break
        if not descended:
            return message
    return message


def _has_field(message, name: str) -> bool:
    """``HasField`` shim that returns False instead of raising on
    unknown / scalar fields."""
    if message is None:
        return False
    try:
        return message.HasField(name)
    except (ValueError, AttributeError):
        return False


def _extract_text(message) -> Optional[str]:
    """Extract a display string from a WhatsApp message protobuf.

    Order of preference:
      1. Real text (conversation, extendedTextMessage.text).
      2. Caption on a media message (image, video, document).
      3. A typed placeholder for media-only / system messages so the
         renderer shows ``[image]`` / ``[voice]`` / ``[sticker]`` /
         ``[poll: ...]`` etc. instead of ``[empty]``.

    Unwraps deviceSentMessage / ephemeral / view-once / edited envelopes
    first via ``_unwrap_message``.
    """
    message = _unwrap_message(message)
    if message is None:
        return None

    # 1. Direct text payloads
    if hasattr(message, "conversation") and message.conversation:
        return message.conversation
    if _has_field(message, "extendedTextMessage"):
        ext = message.extendedTextMessage
        text = getattr(ext, "text", "") or ""
        if text:
            return text

    # 2. Media with caption (these proto fields all carry .caption).
    for attr, label in (
        ("imageMessage", "image"),
        ("videoMessage", "video"),
        ("documentMessage", "document"),
    ):
        if _has_field(message, attr):
            sub = getattr(message, attr)
            caption = getattr(sub, "caption", "") or ""
            if caption:
                return f"[{label}] {caption}"

    # 3. Typed placeholders for media-only messages. Without these the
    # renderer shows "[empty]" for every voice note / sticker / poll —
    # cosmetically broken, see 2026-05-06 user complaint.
    if _has_field(message, "imageMessage"):
        return "[image]"
    if _has_field(message, "videoMessage"):
        return "[video]"
    if _has_field(message, "audioMessage"):
        audio = message.audioMessage
        is_ptt = bool(getattr(audio, "PTT", False)) or bool(getattr(audio, "ptt", False))
        return "[voice]" if is_ptt else "[audio]"
    if _has_field(message, "ptvMessage"):
        return "[video note]"
    if _has_field(message, "documentMessage"):
        doc = message.documentMessage
        fn = getattr(doc, "fileName", "") or getattr(doc, "filename", "") or ""
        return f"[document: {fn}]" if fn else "[document]"
    if _has_field(message, "stickerMessage") or _has_field(message, "lottieStickerMessage"):
        return "[sticker]"
    if _has_field(message, "stickerPackMessage"):
        return "[sticker pack]"
    if _has_field(message, "contactMessage"):
        name = getattr(message.contactMessage, "displayName", "") or ""
        return f"[contact: {name}]" if name else "[contact]"
    if _has_field(message, "contactsArrayMessage"):
        return "[contacts]"
    if _has_field(message, "locationMessage") or _has_field(message, "liveLocationMessage"):
        return "[location]"
    for poll_field in (
        "pollCreationMessage",
        "pollCreationMessageV2",
        "pollCreationMessageV3",
        "pollCreationMessageV4",
    ):
        if _has_field(message, poll_field):
            poll = getattr(message, poll_field)
            q = getattr(poll, "name", "") or ""
            return f"[poll: {q}]" if q else "[poll]"
    if _has_field(message, "pollUpdateMessage"):
        return "[poll vote]"
    if _has_field(message, "reactionMessage"):
        emoji = getattr(message.reactionMessage, "text", "") or ""
        return f"[reaction: {emoji}]" if emoji else "[reaction]"
    if _has_field(message, "groupInviteMessage"):
        return "[group invite]"
    if _has_field(message, "eventMessage"):
        return "[event]"
    if _has_field(message, "buttonsMessage") or _has_field(message, "buttonsResponseMessage"):
        return "[buttons]"
    if _has_field(message, "interactiveMessage") or _has_field(message, "interactiveResponseMessage"):
        return "[interactive]"
    if _has_field(message, "templateMessage") or _has_field(message, "templateButtonReplyMessage"):
        return "[template]"
    if _has_field(message, "listMessage") or _has_field(message, "listResponseMessage"):
        return "[list]"
    if _has_field(message, "orderMessage"):
        return "[order]"
    if _has_field(message, "invoiceMessage"):
        return "[invoice]"
    if _has_field(message, "productMessage"):
        return "[product]"
    if _has_field(message, "albumMessage"):
        return "[album]"
    if _has_field(message, "call"):
        return "[call]"
    # protocolMessage / senderKeyDistributionMessage / messageContextInfo /
    # encReactionMessage / appStateSync* etc. are system-level — return
    # None so the renderer can keep them out of the visible flow.
    return None


def _safe_from_timestamp(ts) -> Optional[datetime]:
    """Convert Unix timestamp to datetime, handling bogus values.

    WhatsApp sometimes sends nanosecond timestamps or
    corrupted values that produce years like 58227.
    """
    if not ts or not isinstance(ts, (int, float)) or ts <= 0:
        return None
    # Nanoseconds → seconds (if ts > year 3000 in seconds)
    if ts > 32503680000:  # 3000-01-01 UTC
        ts = ts / 1_000_000_000
    try:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        # Reject dates before 2009 (WhatsApp launched) or after 2100
        if dt.year < 2009 or dt.year > 2100:
            return None
        return dt
    except (ValueError, OSError, OverflowError):
        return None


def _extract_timestamp(info) -> Optional[datetime]:
    """Extract timestamp from message info."""
    if hasattr(info, "Timestamp") and info.Timestamp:
        ts = info.Timestamp
        if isinstance(ts, datetime):
            return ts
        return _safe_from_timestamp(ts)
    return None


def _extract_timestamp_from_int(ts) -> Optional[datetime]:
    """Convert Unix timestamp to datetime."""
    return _safe_from_timestamp(ts)


def _format_jid(jid) -> str:
    """Format a neonize JID proto as ``"user@server"``.

    str(jid) on a populated neonize JID proto returns the protobuf debug
    repr (e.g. ``'User: "393281234567"\\nServer: "s.whatsapp.net"\\n'``),
    not the wire-format string the rest of the code base expects. Build
    it explicitly from the User / Server fields. Returns ``""`` when the
    JID is empty / unset so caller-side ``"" / NULL`` checks keep
    working.
    """
    if jid is None:
        return ""
    user = getattr(jid, "User", "") or ""
    server = getattr(jid, "Server", "") or ""
    if not user and not server:
        return ""
    return f"{user}@{server}"


def _jid_to_phone(jid_str: str) -> str:
    """Convert WhatsApp JID to phone number.

    Example: "393281234567@s.whatsapp.net" → "+393281234567"
    """
    if "@" in jid_str:
        number = jid_str.split("@")[0]
        if number.isdigit():
            return f"+{number}"
    return jid_str


def _extract_contact_name(contact_info) -> Optional[str]:
    """Extract display name from contact info."""
    if isinstance(contact_info, dict):
        return (
            contact_info.get("FullName")
            or contact_info.get("FirstName")
            or contact_info.get("BusinessName")
        )
    if hasattr(contact_info, "FullName"):
        return contact_info.FullName
    if hasattr(contact_info, "FirstName"):
        return contact_info.FirstName
    return None


def _extract_push_name(contact_info) -> Optional[str]:
    """Extract push name (WhatsApp display name) from contact."""
    if isinstance(contact_info, dict):
        return contact_info.get("PushName")
    if hasattr(contact_info, "PushName"):
        return contact_info.PushName
    return None
