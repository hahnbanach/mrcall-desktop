"""WhatsApp sync service — stores messages and contacts in SQLite.

Analogous to zylch/tools/email_sync.py for email.
Handles HistorySyncEv (initial) and MessageEv (ongoing).
"""

import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from zylch.storage.database import get_session

logger = logging.getLogger(__name__)


def _wa_media_dir() -> str:
    """Return (and create) the per-profile WhatsApp media directory.

    Mirrors ``zylch.whatsapp.client._default_wa_db``'s base resolution:
    the profile dir when ``ZYLCH_PROFILE_DIR`` is set, otherwise
    ``~/.zylch``. Downloaded voice-note bytes are written here so the
    later transcription pass can read them off disk.
    """
    base = os.environ.get("ZYLCH_PROFILE_DIR") or os.path.expanduser("~/.zylch")
    media_dir = os.path.join(base, "wa_media")
    Path(media_dir).mkdir(parents=True, exist_ok=True)
    return media_dir


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
        # The WhatsAppClient wrapper, set by the connect flow before the
        # socket opens (see rpc/whatsapp_actions.py). Required to download
        # voice-note bytes at event time; left None in code paths that
        # only replay history (no live download available there).
        self.wa_client = None

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

    # -- LID → phone+name resolution (from neonize session DB) ----------

    def sync_lid_contacts(self, wa_client=None) -> int:
        """Resolve every ``@lid`` JID we've seen in messages to a real
        phone number + display name, using neonize's own session DB
        (``whatsapp.db``).

        Two tables there give us everything:

        * ``whatsmeow_lid_map(lid, pn)`` — LID ↔ phone-JID local-part.
        * ``whatsmeow_contacts(their_jid, full_name, first_name,
          push_name, business_name, …)`` — the user's address-book
          entries as WhatsApp itself sees them. Populated by neonize
          during the normal app-state sync; no extra round-trip needed.

        We open the file read-only (SQLite WAL is concurrency-safe) and
        upsert each LID into our own ``whatsapp_contacts`` table keyed
        by the LID itself, so ``list_threads`` can render the real
        contact name instead of a numeric pseudonym.

        Returns the number of LID contacts upserted.
        """
        import sqlite3 as _sqlite3

        from zylch.storage.models import WhatsAppContact, WhatsAppMessage
        from zylch.whatsapp.client import _default_wa_db

        # Distinct LID local-parts present in our messages (chat or sender).
        lids: set[str] = set()
        try:
            with self._db_lock, get_session() as session:
                rows = (
                    session.query(WhatsAppMessage.chat_jid, WhatsAppMessage.sender_jid)
                    .filter(WhatsAppMessage.owner_id == self.owner_id)
                    .all()
                )
            for chat, sender in rows:
                if chat and chat.endswith("@lid"):
                    lids.add(chat.split("@", 1)[0])
                if sender and sender.endswith("@lid"):
                    lids.add(sender.split("@", 1)[0])
        except Exception as e:
            logger.error(f"[wa-sync] sync_lid_contacts: collect LIDs failed: {e}")
            return 0

        if not lids:
            return 0

        wa_db = _default_wa_db()
        try:
            conn = _sqlite3.connect(f"file:{wa_db}?mode=ro", uri=True)
        except Exception as e:
            logger.warning(f"[wa-sync] sync_lid_contacts: open {wa_db}: {e}")
            return 0

        # Build (lid, phone, name) tuples.
        resolved: list = []
        try:
            cur = conn.cursor()
            for lid in lids:
                cur.execute(
                    "SELECT pn FROM whatsmeow_lid_map WHERE lid=?",
                    (lid,),
                )
                row = cur.fetchone()
                pn_user = row[0].split("@", 1)[0] if row and row[0] else None

                # Collect every name field from BOTH JID forms (LID and
                # phone) into one bag, then pick by priority. Doing it
                # row-by-row was wrong: e.g. the LID row may carry only
                # ``push_name='A'`` (a single-letter status nick) while
                # the phone row carries ``first_name='Alessandro
                # Simonetti'`` — picking per-row would lock us to 'A'.
                full_names: list = []
                business_names: list = []
                first_names: list = []
                push_names: list = []
                lookups = [f"{lid}@lid"]
                if pn_user:
                    lookups.append(f"{pn_user}@s.whatsapp.net")
                for jid_form in lookups:
                    cur.execute(
                        "SELECT full_name, first_name, push_name, business_name "
                        "FROM whatsmeow_contacts WHERE their_jid=? LIMIT 1",
                        (jid_form,),
                    )
                    r = cur.fetchone()
                    if not r:
                        continue
                    fn, fr, pu, bn = r
                    if (fn or "").strip():
                        full_names.append(fn.strip())
                    if (bn or "").strip():
                        business_names.append(bn.strip())
                    if (fr or "").strip():
                        first_names.append(fr.strip())
                    if (pu or "").strip():
                        push_names.append(pu.strip())

                # Priority: real address-book full_name → business_name →
                # first_name (own contact-list label) → push_name (the
                # other side's self-set status nick, often noisy).
                name = None
                for bucket in (full_names, business_names, first_names, push_names):
                    if bucket:
                        name = bucket[0]
                        break

                phone = f"+{pn_user}" if pn_user and pn_user.isdigit() else None
                if name or phone:
                    resolved.append((f"{lid}@lid", phone, name))
        finally:
            conn.close()

        if not resolved:
            logger.info("[wa-sync] lid contacts synced: 0 (no resolutions)")
            return 0

        count = 0
        try:
            with self._db_lock, get_session() as session:
                for jid, phone, name in resolved:
                    existing = (
                        session.query(WhatsAppContact)
                        .filter_by(owner_id=self.owner_id, jid=jid)
                        .first()
                    )
                    if existing:
                        if name:
                            existing.name = name
                        if phone:
                            existing.phone_number = phone
                        existing.synced_at = datetime.now(timezone.utc)
                    else:
                        session.add(
                            WhatsAppContact(
                                owner_id=self.owner_id,
                                jid=jid,
                                phone_number=phone,
                                name=name,
                                synced_at=datetime.now(timezone.utc),
                            )
                        )
                    count += 1
            logger.info(f"[wa-sync] lid contacts synced: {count}")
        except Exception as e:
            logger.error(f"[wa-sync] sync_lid_contacts upsert error: {e}")
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

            # "Delete for everyone" (revoke): the message names a TARGET to
            # remove and must NOT itself be stored. Handle it before any
            # field extraction so a recalled secret (e.g. an SSH key the
            # sender deleted) is purged from the local store rather than
            # persisted as a junk/empty row.
            revoke_target = _extract_revoke_target(message)
            if revoke_target:
                n = 0
                if self.storage is not None:
                    n = self.storage.delete_whatsapp_message_by_message_id(
                        self.owner_id, revoke_target
                    )
                logger.info(
                    f"[wa-sync] revoke: deleted target message_id={revoke_target} (rows={n})"
                )
                return True

            src = info.MessageSource if hasattr(info, "MessageSource") else None
            chat_jid = _format_jid(getattr(src, "Chat", None)) if src is not None else ""
            sender_jid = _format_jid(getattr(src, "Sender", None)) if src is not None else ""
            is_from_me = bool(getattr(src, "IsFromMe", False)) if src is not None else False
            is_group = bool(getattr(src, "IsGroup", False)) if src is not None else False
            timestamp = _extract_timestamp(info)
            text = _extract_text(message)
            sender_name = str(info.Pushname) if hasattr(info, "Pushname") else ""

            # Voice/audio handling: classify on the UNWRAPPED proto (the
            # one that directly carries audioMessage) and download the
            # bytes NOW — WhatsApp media URLs expire, and only the live
            # client can decrypt. Transcription happens later in batch.
            unwrapped = _unwrap_message(message)
            media_kind = _extract_media_kind(message)
            media_path = None
            if media_kind in ("voice", "audio") and self.wa_client is not None:
                media_path = self._download_audio(msg_id, unwrapped)

            return self._upsert_message(
                msg_id=msg_id,
                chat_jid=chat_jid,
                sender_jid=sender_jid,
                sender_name=sender_name,
                text=text,
                timestamp=timestamp,
                is_from_me=is_from_me,
                is_group=is_group,
                media_type=media_kind,
                media_path=media_path,
            )
        except Exception as e:
            logger.warning(f"[wa-sync] could not store event message: {e}")
            return False

    def _download_audio(self, msg_id: str, unwrapped) -> Optional[str]:
        """Download a voice/audio blob to ``<wa_media>/<msg_id>.ogg``.

        Args:
            msg_id: Protocol message id, used as the filename stem.
            unwrapped: The unwrapped Message proto carrying audioMessage —
                what neonize's ``download_any`` expects.

        Returns:
            The absolute file path on success, or ``None`` if the client
            returned no bytes or the download/write failed (defensive:
            the caller still tags ``media_type`` so the row is not lost).
        """
        try:
            data = self.wa_client.download_media(unwrapped)
            if not data:
                logger.warning(f"[wa-sync] _download_audio(msg_id={msg_id}) -> no bytes")
                return None
            path = os.path.join(_wa_media_dir(), f"{msg_id}.ogg")
            with open(path, "wb") as fh:
                fh.write(data)
            logger.info(
                f"[wa-sync] _download_audio(msg_id={msg_id}) -> " f"path={path} bytes={len(data)}"
            )
            return path
        except Exception as e:
            logger.warning(f"[wa-sync] _download_audio(msg_id={msg_id}) failed: {e}")
            return None

    def _store_message_from_proto(self, msg) -> bool:
        """Store a message from history sync protobuf."""

        try:
            key = msg.key if hasattr(msg, "key") else None
            if not key:
                return False

            msg_id = str(key.id) if hasattr(key, "id") else ""
            if not msg_id:
                return False

            inner = msg.message if hasattr(msg, "message") else msg

            # Best-effort revoke handling in history replay: if a revoke
            # rides in via HistorySyncEv, delete its target and skip the
            # revoke row. The history proto's inner Message shape may differ
            # from the live one; _extract_revoke_target is fully defensive
            # and returns None (→ stored normally / skipped) if it can't
            # find a protocolMessage, so this never crashes the replay.
            revoke_target = _extract_revoke_target(inner)
            if revoke_target:
                n = 0
                if self.storage is not None:
                    n = self.storage.delete_whatsapp_message_by_message_id(
                        self.owner_id, revoke_target
                    )
                logger.info(
                    f"[wa-sync] revoke (history): deleted target "
                    f"message_id={revoke_target} (rows={n})"
                )
                return True

            chat_jid = str(key.remoteJid if hasattr(key, "remoteJid") else "")
            is_from_me = bool(key.fromMe if hasattr(key, "fromMe") else False)
            sender_jid = (
                str(key.participant)
                if hasattr(key, "participant") and key.participant
                else chat_jid
            )

            text = _extract_text(inner)
            timestamp = _extract_timestamp_from_int(
                msg.messageTimestamp if hasattr(msg, "messageTimestamp") else 0
            )
            sender_name = str(msg.pushName if hasattr(msg, "pushName") else "")

            # Tag the media kind so voice/audio rows are classifiable, but
            # leave media_path NULL: the history-sync path has no reliable
            # live client to download from (v1). The transcription step
            # skips rows with media_path NULL, so these stay un-transcribed
            # until a real-time MessageEv re-delivers them.
            media_kind = _extract_media_kind(inner)

            return self._upsert_message(
                msg_id=msg_id,
                chat_jid=chat_jid,
                sender_jid=sender_jid if not is_from_me else "me",
                sender_name=sender_name,
                text=text,
                timestamp=timestamp,
                is_from_me=is_from_me,
                is_group="@g.us" in chat_jid,
                media_type=media_kind,
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
        media_type: Optional[str] = None,
        media_path: Optional[str] = None,
    ) -> bool:
        """Insert or skip a message in whatsapp_messages.

        Args:
            media_type: ``"voice"`` / ``"audio"`` for audio messages, else
                ``None``. Backfilled onto an existing row when currently
                empty.
            media_path: Local path to the downloaded audio bytes, or
                ``None``. Backfilled onto an existing row when currently
                empty (e.g. a history-sync placeholder later gets the live
                download via a MessageEv).
        """
        from zylch.storage.models import WhatsAppMessage

        if not msg_id:
            return False

        try:
            with self._db_lock, get_session() as session:
                existing = session.query(WhatsAppMessage).filter_by(message_id=msg_id).first()
                if existing:
                    # Backfill on second arrival: WhatsApp's first delivery
                    # of a message during history sync sometimes lands as a
                    # placeholder with no decrypted body, then the real
                    # MessageEv arrives later with the actual proto. Plain
                    # ``return False`` here meant the row stayed
                    # ``text=NULL`` forever and the renderer showed
                    # ``[empty]``. Update the columns whose first version
                    # was empty when the second version has something
                    # better to offer.
                    changed = False
                    if text and not (existing.text or "").strip():
                        existing.text = text
                        changed = True
                    if timestamp is not None and (
                        existing.timestamp is None or existing.timestamp.year < 2000
                    ):
                        existing.timestamp = timestamp
                        changed = True
                    if sender_name and not existing.sender_name:
                        existing.sender_name = sender_name
                        changed = True
                    if chat_jid and not existing.chat_jid:
                        existing.chat_jid = chat_jid
                        changed = True
                    if sender_jid and not existing.sender_jid:
                        existing.sender_jid = sender_jid
                        changed = True
                    if media_type and not (existing.media_type or "").strip():
                        existing.media_type = media_type
                        changed = True
                    if media_path and not (existing.media_path or "").strip():
                        existing.media_path = media_path
                        changed = True
                    return changed

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
                    media_type=media_type,
                    media_path=media_path,
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


# waE2E ProtocolMessage.Type.REVOKE — "delete for everyone". The enum
# value is 0 and stable in whatsmeow/waE2E (verified against neonize
# 0.3.17: WAWebProtobufsE2E.ProtocolMessage.Type). We hardcode it rather
# than import the proto class so a version bump that renames the module
# can't crash the message handler — _extract_revoke_target stays purely
# field-introspection based.
_REVOKE_TYPE = 0


def _extract_revoke_target(message) -> Optional[str]:
    """Return the TARGET message id of a "delete for everyone" revoke.

    A revoke arrives as a ``Message`` carrying a ``protocolMessage`` whose
    ``type == REVOKE`` and whose ``key`` identifies the message to remove.
    We must delete that target row and NOT store the revoke itself.

    Returns the target's protocol message id (``protocolMessage.key.ID``)
    when the message is a revoke with an actionable key, else ``None``.

    Defensive by construction — proto3 enums default ``type`` to 0
    (== REVOKE) even when unset, so a non-revoke ``protocolMessage`` (an
    edit, an ephemeral-setting change, a history-sync notification, …)
    would look like a revoke if we only checked ``type``. We therefore
    require BOTH ``type == REVOKE`` AND a non-empty target key id; a bare
    ``type=0`` with no key is not a real revoke and is ignored. Casing
    differs by source: live ``MessageEv`` keys use ``ID``/``remoteJID``;
    history ``WebMessageInfo`` keys use ``id``/``remoteJid`` — we try
    both. Never raises.
    """
    message = _unwrap_message(message)
    if message is None:
        return None
    if not _has_field(message, "protocolMessage"):
        return None
    pm = getattr(message, "protocolMessage", None)
    if pm is None:
        return None
    try:
        ptype = getattr(pm, "type", getattr(pm, "Type", None))
    except Exception:
        ptype = None
    if ptype != _REVOKE_TYPE:
        return None
    key = getattr(pm, "key", None)
    if key is None:
        return None
    target_id = getattr(key, "ID", None) or getattr(key, "id", None)
    target_id = str(target_id) if target_id else ""
    return target_id or None


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
    if _has_field(message, "interactiveMessage") or _has_field(
        message, "interactiveResponseMessage"
    ):
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
    #
    # Diagnostic: log which oneof / fields ARE set on a Message that we
    # couldn't extract anything from, so we know exactly which proto
    # kind needs new placeholder support next. Sampled at INFO level so
    # it's visible in zylch.log without DEBUG noise. Only logs once per
    # unique field-set within a process to avoid log spam on chats with
    # many of the same kind.
    try:
        set_fields = sorted(f.name for f, _ in message.ListFields())
        signature = ",".join(set_fields) or "(none)"
        if signature not in _UNHANDLED_PROTO_SIGNATURES:
            _UNHANDLED_PROTO_SIGNATURES.add(signature)
            logger.info(f"[wa-sync] _extract_text returned None: fields=[{signature}]")
    except Exception:
        pass
    return None


# Module-level set so the diagnostic line above logs each new combination
# only once per process — keeps zylch.log readable while still surfacing
# every unhandled proto kind we see.
_UNHANDLED_PROTO_SIGNATURES: set = set()


def _extract_media_kind(message) -> Optional[str]:
    """Classify the AUDIO media kind of a WhatsApp message, if any.

    Scope is deliberately narrow — only audio kinds matter for voice-note
    transcription. Images, documents, stickers etc. are not classified
    here (``_extract_text`` already produces their display placeholders).

    Unwraps E2E envelopes via :func:`_unwrap_message` first, mirroring
    what ``_extract_text`` does so the classification matches the proto
    that actually carries ``audioMessage``.

    Args:
        message: The (possibly E2E-wrapped) WhatsApp Message proto.

    Returns:
        ``"voice"`` for push-to-talk audio, ``"audio"`` for a non-PTT
        audio file, or ``None`` for anything else.
    """
    message = _unwrap_message(message)
    if message is None:
        return None
    if not _has_field(message, "audioMessage"):
        return None
    audio = message.audioMessage
    is_ptt = bool(getattr(audio, "PTT", False)) or bool(getattr(audio, "ptt", False))
    return "voice" if is_ptt else "audio"


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

    Only ``@s.whatsapp.net`` carries a real phone number in its
    local-part. ``@lid`` is a privacy pseudonym (opaque numeric id, not
    a phone) and ``@g.us`` is a synthetic group id — for both we return
    an empty string so callers don't render fake phone numbers.

    Example: "393281234567@s.whatsapp.net" → "+393281234567"
             "86904452186141@lid"          → ""
    """
    if "@" not in jid_str:
        return ""
    user, _, server = jid_str.partition("@")
    if server != "s.whatsapp.net":
        return ""
    if user.isdigit():
        return f"+{user}"
    return ""


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


def get_archived_chat_jids() -> set[str]:
    """Return the set of ``chat_jid``s the user has archived on WhatsApp.

    The archived flag lives in neonize's own session DB (``whatsapp.db``)
    under ``whatsmeow_chat_settings(our_jid, chat_jid, muted_until,
    pinned, archived)``; ``chat_jid`` there matches our
    ``whatsapp_messages.chat_jid`` form verbatim
    (``<digits>@s.whatsapp.net`` / ``@g.us`` / ``@lid``). We open the
    file read-only — exactly like :meth:`WhatsAppSyncService.sync_lid_contacts`
    — so we never contend with the live whatsmeow connection.

    Degrades to an EMPTY set on ANY failure (file missing, the table
    not present on an older session DB, a malformed row, …) — this is a
    best-effort filter and must never raise into the pipeline. The
    archived flag is populated by app-state sync, so a chat archived on
    the phone only takes effect here after the next connect/sync.
    """
    import sqlite3 as _sqlite3

    from zylch.whatsapp.client import _default_wa_db

    wa_db = _default_wa_db()
    conn = None
    try:
        conn = _sqlite3.connect(f"file:{wa_db}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute("SELECT chat_jid FROM whatsmeow_chat_settings WHERE archived=1")
        archived = {row[0] for row in cur.fetchall() if row and row[0]}
        logger.debug(f"[wa-archived] {len(archived)} archived chat(s) in session DB")
        return archived
    except Exception as e:
        # Missing file, missing table on an older session DB, locked, etc.
        logger.debug(f"[wa-archived] could not read archived chats from {wa_db}: {e}")
        return set()
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def drop_archived_messages(messages: list[dict], archived: set[str]) -> list[dict]:
    """Filter out messages whose ``chat_jid`` is in ``archived``.

    Pure (no DB, no I/O) so the skip logic is unit-testable on its own.
    An empty ``archived`` set is a passthrough. Messages without a
    ``chat_jid`` are kept (defensive — the caller decides what to do with
    them; we never silently drop on missing data).
    """
    if not archived:
        return messages
    return [m for m in messages if (m.get("chat_jid") or "") not in archived]
