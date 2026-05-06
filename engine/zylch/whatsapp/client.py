"""WhatsApp client using neonize (whatsmeow Python wrapper).

Provides local WhatsApp connection via QR code login.
Session persists in a local SQLite database (~/.zylch/whatsapp.db).
Analogous to zylch/email/imap_client.py for email.
"""

import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from neonize.client import NewClient
from neonize.events import (
    EVENT_TO_INT,
    ConnectedEv,
    DisconnectedEv,
    HistorySyncEv,
    LoggedOutEv,
    MessageEv,
    ReceiptEv,
)

logger = logging.getLogger(__name__)


def _default_wa_db() -> str:
    """WhatsApp DB path — per-profile if available."""
    profile_dir = os.environ.get("ZYLCH_PROFILE_DIR")
    if profile_dir:
        return os.path.join(profile_dir, "whatsapp.db")
    return os.path.expanduser("~/.zylch/whatsapp.db")


class WhatsAppClient:
    """Local WhatsApp connection via neonize (whatsmeow).

    Usage:
        client = WhatsAppClient()
        client.connect()  # Shows QR on first run, then auto-reconnects
        contacts = client.get_contacts()
        client.disconnect()
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or _default_wa_db()
        self._client: Optional[NewClient] = None
        self._thread: Optional[threading.Thread] = None
        self._qr_callback: Optional[Callable] = None
        self._message_callback: Optional[Callable] = None
        self._history_callback: Optional[Callable] = None
        self._connected_callback: Optional[Callable] = None
        self._disconnected_callback: Optional[Callable] = None
        self._receipt_callback: Optional[Callable] = None
        self._logged_out = False

    def _ensure_db_dir(self):
        """Create parent directory for the session database."""
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

    def _init_client(self):
        """Initialize neonize NewClient and register event handlers."""
        self._ensure_db_dir()
        self._client = NewClient(self.db_path)
        self._register_events()
        logger.debug(f"[whatsapp] client initialized, db={self.db_path}")

    def _register_events(self):
        """Register event callbacks on the neonize client."""
        event = self._client.event

        # QR code display (first-time login)
        if self._qr_callback:
            event.qr(self._qr_callback)
        # else: default neonize handler prints QR to terminal

        # Map neonize event codes to our callbacks
        handlers = {
            MessageEv: self._on_message,
            HistorySyncEv: self._on_history_sync,
            ConnectedEv: self._on_connected,
            DisconnectedEv: self._on_disconnected,
            ReceiptEv: self._on_receipt,
            LoggedOutEv: self._on_logged_out,
        }
        for ev_type, handler in handlers.items():
            code = EVENT_TO_INT.get(ev_type)
            if code is not None:
                event.list_func[code] = handler

    # -- Event handlers ------------------------------------------------

    def _on_message(self, client: NewClient, message: MessageEv):
        """Handle incoming/outgoing message."""
        logger.debug("[whatsapp] MessageEv received")
        if self._message_callback:
            try:
                self._message_callback(message)
            except Exception as e:
                logger.error(f"[whatsapp] message callback error: {e}")

    def _on_history_sync(self, client: NewClient, event: HistorySyncEv):
        """Handle history sync (initial download of past messages)."""
        logger.info("[whatsapp] HistorySyncEv received")
        if self._history_callback:
            try:
                self._history_callback(event)
            except Exception as e:
                logger.error(f"[whatsapp] history callback error: {e}")

    def _on_connected(self, client: NewClient, event: ConnectedEv):
        """Handle successful connection."""
        logger.info("[whatsapp] connected")
        self._logged_out = False
        if self._connected_callback:
            try:
                self._connected_callback()
            except Exception as e:
                logger.error(f"[whatsapp] connected callback error: {e}")

    def _on_disconnected(self, client: NewClient, event: DisconnectedEv):
        """Handle disconnection."""
        logger.warning("[whatsapp] disconnected")
        if self._disconnected_callback:
            try:
                self._disconnected_callback()
            except Exception as e:
                logger.error(f"[whatsapp] disconnected callback error: {e}")

    def _on_receipt(self, client: NewClient, event: ReceiptEv):
        """Handle delivery/read receipts."""
        if self._receipt_callback:
            try:
                self._receipt_callback(event)
            except Exception as e:
                logger.error(f"[whatsapp] receipt callback error: {e}")

    def _on_logged_out(self, client: NewClient, event: LoggedOutEv):
        """Handle forced logout (user removed device from phone)."""
        logger.warning("[whatsapp] logged out — session invalidated")
        self._logged_out = True

    # -- Public API ----------------------------------------------------

    def on_message(self, callback: Callable):
        """Register callback for incoming messages."""
        self._message_callback = callback

    def on_history_sync(self, callback: Callable):
        """Register callback for history sync events."""
        self._history_callback = callback

    def on_connected(self, callback: Callable):
        """Register callback for connection events."""
        self._connected_callback = callback

    def on_disconnected(self, callback: Callable):
        """Register callback for disconnection events."""
        self._disconnected_callback = callback

    def on_receipt(self, callback: Callable):
        """Register callback for delivery/read receipts."""
        self._receipt_callback = callback

    def set_qr_callback(self, callback: Callable):
        """Set custom QR code display callback.

        Args:
            callback: function(client, qr_data_bytes) — display QR to user
        """
        self._qr_callback = callback

    def connect(self, blocking: bool = True):
        """Connect to WhatsApp.

        On first run, displays QR code for user to scan.
        On subsequent runs, reconnects using saved session.

        Args:
            blocking: if True, blocks until disconnect.
                      if False, runs in a background thread.
        """
        self._init_client()

        if blocking:
            logger.info("[whatsapp] connecting (blocking)...")
            self._client.connect()
        else:
            logger.info("[whatsapp] connecting (background thread)...")
            self._thread = threading.Thread(
                target=self._client.connect,
                daemon=True,
                name="whatsapp-client",
            )
            self._thread.start()

    def disconnect(self):
        """Disconnect from WhatsApp cleanly."""
        if self._client:
            try:
                self._client.disconnect()
            except Exception as e:
                logger.warning(f"[whatsapp] disconnect error: {e}")
            logger.info("[whatsapp] disconnected")

    @staticmethod
    def _call_or_attr(obj, name: str, default: bool = False) -> bool:
        """Read a bool from the underlying neonize client whether the
        wrapped library exposes it as a method or as a plain attribute.

        Recent neonize versions changed several flags from methods
        (``client.is_connected()``) to attributes
        (``client.is_connected``). Calling the new form as a method
        raises ``'bool' object is not callable``; reading the old form
        without parentheses gives a bound method instead of the value.
        Detect at runtime and use the right form.
        """
        raw = getattr(obj, name, default)
        try:
            return bool(raw() if callable(raw) else raw)
        except Exception:
            return default

    def is_connected(self) -> bool:
        """Check if currently connected to WhatsApp."""
        if self._client is None:
            return False
        return self._call_or_attr(self._client, "is_connected", False)

    def is_logged_in(self) -> bool:
        """Check if session is valid (not logged out from phone)."""
        if self._client is None:
            return False
        return (
            self._call_or_attr(self._client, "is_logged_in", False)
            and not self._logged_out
        )

    def has_session(self) -> bool:
        """Check if a saved session exists on disk."""
        return Path(self.db_path).exists()

    def get_me(self):
        """Get own JID and device info."""
        if self._client and self._client.me:
            return self._client.me
        return None

    # -- Contacts ------------------------------------------------------

    def get_contacts(self) -> List[Any]:
        """Get contact info for known JIDs.

        neonize doesn't have a "get all contacts" API.
        Returns empty list — contacts are extracted from
        synced messages instead.
        """
        return []

    def get_contact(self, jid) -> Optional[Any]:
        """Get a specific contact by JID."""
        if not self._client:
            return None
        try:
            results = self._client.get_user_info(jid)
            return results[0] if results else None
        except Exception as e:
            logger.warning(f"[whatsapp] get_contact failed: {e}")
            return None

    # -- Messaging -----------------------------------------------------

    def send_message(self, jid, text: str) -> Optional[str]:
        """Send a text message.

        Args:
            jid: recipient JID (use build_jid() to construct)
            text: message text

        Returns:
            Message ID on success, None on failure.
        """
        if not self._client:
            logger.error("[whatsapp] cannot send: client not initialized")
            return None
        try:
            resp = self._client.send_message(jid, text)
            logger.debug(f"[whatsapp] sent message to {jid}")
            return resp
        except Exception as e:
            logger.error(f"[whatsapp] send_message failed: {e}")
            return None

    def is_on_whatsapp(self, phone_numbers: List[str]) -> List[Dict]:
        """Check which phone numbers are registered on WhatsApp.

        Args:
            phone_numbers: list of phone numbers with country code

        Returns:
            List of results with JID and registration status.
        """
        if not self._client:
            return []
        try:
            return self._client.is_on_whatsapp(phone_numbers)
        except Exception as e:
            logger.error(f"[whatsapp] is_on_whatsapp failed: {e}")
            return []

    def get_joined_groups(self) -> List[Any]:
        """Get list of WhatsApp groups the user is in."""
        if not self._client:
            return []
        try:
            return self._client.get_joined_groups()
        except Exception as e:
            logger.error(f"[whatsapp] get_joined_groups failed: {e}")
            return []

    def logout(self):
        """Logout and clear the local session."""
        if self._client:
            try:
                self._client.logout()
            except Exception as e:
                logger.warning(f"[whatsapp] logout error: {e}")
        # Remove session DB
        db = Path(self.db_path)
        if db.exists():
            db.unlink()
            logger.info(f"[whatsapp] session removed: {self.db_path}")
