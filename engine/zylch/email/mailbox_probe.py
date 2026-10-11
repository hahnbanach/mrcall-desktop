"""Test a mailbox's IMAP access the way the sync will use it.

Login, LIST, a read-only SELECT of INBOX, then of the Sent and archive
folders when discovery finds them — an absent Sent or archive folder is
absent, as ``sync_folders`` treats it, never a failure. The outcome is one
of five statuses:

- ``ok`` — everything the sync needs answered;
- ``auth`` — the server refused the credentials;
- ``tls`` — the secure connection could not be established;
- ``unreachable`` — DNS, refusal, timeout or another transport failure;
- ``folder`` — a folder discovery found cannot be selected.

The message never carries the password: it is built from the exceptions
the client raises (host, address, server text), and scrubbed once more
against the password before it leaves.
"""

from __future__ import annotations

import imaplib
import logging
import socket
import ssl
from dataclasses import dataclass

from zylch.email.imap_client import IMAPClient, IMAPError, IMAPFolderError, _scrub_secret

logger = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_AUTH = "auth"
STATUS_TLS = "tls"
STATUS_UNREACHABLE = "unreachable"
STATUS_FOLDER = "folder"


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    status: str
    message: str
    folders: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"ok": self.ok, "status": self.status, "message": self.message}


def _walk(error: BaseException):
    seen: set = set()
    cur: BaseException | None = error
    for _ in range(8):
        if cur is None or id(cur) in seen:
            return
        seen.add(id(cur))
        yield cur
        cur = getattr(cur, "__cause__", None)


def classify_connect_error(error: BaseException) -> str:
    """``auth`` / ``tls`` / ``unreachable`` from the exception chain ``connect`` raises."""
    for cur in _walk(error):
        if isinstance(cur, (imaplib.IMAP4.error, imaplib.IMAP4.abort)):
            text = str(cur).upper()
            if "AUTHENTICATIONFAILED" in text or "INVALID CREDENTIALS" in text or "LOGIN" in text:
                return STATUS_AUTH
        if isinstance(cur, ssl.SSLError):
            return STATUS_TLS
        if isinstance(cur, (socket.gaierror, ConnectionError, TimeoutError, socket.timeout)):
            return STATUS_UNREACHABLE
    for cur in _walk(error):
        if isinstance(cur, (imaplib.IMAP4.error, imaplib.IMAP4.abort)):
            return STATUS_AUTH
        if isinstance(cur, OSError):
            return STATUS_UNREACHABLE
    return STATUS_UNREACHABLE


def _scrub(message: str, password: str) -> str:
    return _scrub_secret(message, password)


def probe_mailbox(client: IMAPClient) -> ProbeResult:
    """Run the probe against ``client`` (never connected before, disconnected after)."""
    password = getattr(client, "password", "") or ""
    address = getattr(client, "email_addr", "")
    try:
        client.connect()
    except IMAPError as e:
        status = classify_connect_error(e)
        logger.info(f"[mailboxes] probe {address}: {status}")
        return ProbeResult(False, status, _scrub(str(e), password))
    except Exception as e:  # a failure the client did not wrap
        status = classify_connect_error(e)
        logger.info(f"[mailboxes] probe {address}: {status} ({type(e).__name__})")
        return ProbeResult(False, status, _scrub(f"{type(e).__name__}: {e}", password))

    checked: list[str] = []
    try:
        try:
            client.examine_folder("INBOX")
            checked.append("INBOX")
        except IMAPFolderError as e:
            return ProbeResult(
                False, STATUS_FOLDER, _scrub(f"INBOX cannot be opened: {e}", password)
            )
        for finder, label in (
            (client._find_sent_folder, "Sent"),
            (client.find_archive_folder, "archive"),
        ):
            try:
                name = finder()
            except Exception as e:
                logger.warning(f"[mailboxes] probe {address}: {label} discovery failed: {e}")
                name = None
            if not name:
                continue  # absent is absent, as sync_folders treats it
            try:
                client.examine_folder(name)
                checked.append(name)
            except IMAPFolderError as e:
                return ProbeResult(
                    False,
                    STATUS_FOLDER,
                    _scrub(f"{label} folder {name} cannot be opened: {e}", password),
                )
    except IMAPError as e:
        return ProbeResult(False, classify_connect_error(e), _scrub(str(e), password))
    finally:
        try:
            client.disconnect()
        except Exception as e:
            logger.debug(f"[mailboxes] probe {address}: disconnect failed: {e}")
    return ProbeResult(
        True, STATUS_OK, f"Connected; folders checked: {', '.join(checked)}", tuple(checked)
    )
