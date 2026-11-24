"""One raw SMTP transaction using an existing IMAP client's credentials."""

from __future__ import annotations

from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
import re
import smtplib
import ssl
from typing import Any

from .mailbox_errors import MailboxProviderError


def _envelope(owner: str, raw: bytes) -> tuple[bytes, list[str], str]:
    if not isinstance(raw, bytes) or not raw:
        raise MailboxProviderError("mailbox_message_invalid", non_dispatch=True)
    message = BytesParser(policy=policy.SMTP).parsebytes(raw)
    if message.defects or any(len(message.get_all(name, [])) > 1 for name in ("From", "To", "Cc", "Bcc", "Message-ID")):
        raise MailboxProviderError("mailbox_message_invalid", non_dispatch=True)
    sender = getaddresses(message.get_all("From", []))
    if len(sender) != 1 or sender[0][1].strip().lower() != owner:
        raise MailboxProviderError("mailbox_sender_mismatch", non_dispatch=True)
    message_id = str(message.get("Message-ID") or "")
    if not re.fullmatch(r"<[^<>\s]+@[^<>\s]+>", message_id):
        raise MailboxProviderError("mailbox_message_id_invalid", non_dispatch=True)
    recipients = []
    for _name, address in getaddresses(sum((message.get_all(name, []) for name in ("To", "Cc", "Bcc")), [])):
        if (not address or not address.isascii() or any(c.isspace() or c in "<>\r\n" for c in address)
                or address.count("@") != 1 or not all(address.split("@"))):
            raise MailboxProviderError("mailbox_recipient_invalid", non_dispatch=True)
        if address.lower() not in {value.lower() for value in recipients}:
            recipients.append(address)
    if not recipients or len(recipients) > 100:
        raise MailboxProviderError("mailbox_recipient_invalid", non_dispatch=True)
    # Preserve all MIME bytes and omitted alternatives. Bcc is envelope-only.
    if message.get_all("Bcc"):
        if b"\r\n\r\n" not in raw:
            raw = message.as_bytes(policy=policy.SMTP)
        head, body = raw.split(b"\r\n\r\n", 1)
        kept = []
        dropping = False
        for line in head.split(b"\r\n"):
            if not line.startswith((b" ", b"\t")):
                dropping = line.split(b":", 1)[0].lower() == b"bcc"
            if not dropping:
                kept.append(line)
        raw = b"\r\n".join(kept) + b"\r\n\r\n" + body
    return raw, recipients, message_id


def send_raw(client: Any, raw: bytes, *, smtp_factory=None, ssl_factory=None) -> dict[str, Any]:
    """Submit once, refusing every recipient failure before sending DATA.

    A transport failure after DATA starts is uncertain. No connection, DATA or
    recipient transaction is retried here; the caller owns durable Sent recovery.
    """
    from .imap_client import _smtp_timeout_seconds

    owner = str(client.email_addr).strip().lower()
    wire, recipients, message_id = _envelope(owner, raw)
    timeout = _smtp_timeout_seconds()
    smtp = None
    data_started = False
    try:
        if int(client.smtp_port) == 465:
            smtp = (ssl_factory or smtplib.SMTP_SSL)(
                client.smtp_host, client.smtp_port, timeout=timeout, context=ssl.create_default_context()
            )
        else:
            smtp = (smtp_factory or smtplib.SMTP)(client.smtp_host, client.smtp_port, timeout=timeout)
        if smtp.ehlo()[0] != 250:
            raise MailboxProviderError("smtp_handshake_refused", non_dispatch=True)
        if int(client.smtp_port) != 465:
            smtp.starttls(context=ssl.create_default_context())
            if smtp.ehlo()[0] != 250:
                raise MailboxProviderError("smtp_handshake_refused", non_dispatch=True)
        smtp.login(client.email_addr, client.password)
        options = []
        if any(byte > 127 for byte in wire):
            if not smtp.has_extn("8bitmime"):
                raise MailboxProviderError("smtp_message_encoding_unsupported", non_dispatch=True)
            options.append("BODY=8BITMIME")
        if smtp.mail(owner, options=options)[0] != 250:
            raise MailboxProviderError("smtp_sender_refused", non_dispatch=True)
        # A partial RCPT list is never followed by DATA. Closing the transaction
        # cannot deliver any of the accepted subset without its message body.
        for address in recipients:
            if smtp.rcpt(address)[0] not in (250, 251, 252):
                raise MailboxProviderError("smtp_recipient_refused", non_dispatch=True)
        data_started = True
        code, _response = smtp.data(wire)
        if code != 250:
            raise MailboxProviderError("smtp_data_refused", non_dispatch=400 <= code < 600)
        return {"acknowledged": True, "message_id": message_id}
    except MailboxProviderError:
        raise
    except smtplib.SMTPResponseException as error:
        rejected = not data_started or 400 <= error.smtp_code < 600
        reason = "smtp_data_refused" if data_started else "smtp_authentication_or_transaction_refused"
        raise MailboxProviderError(reason, non_dispatch=rejected) from None
    except Exception:
        raise MailboxProviderError("smtp_submission_unavailable", non_dispatch=not data_started) from None
    finally:
        if smtp is not None:
            # QUIT acknowledgement is not delivery evidence and must not mask a
            # DATA acknowledgement. close() releases the socket without another
            # network exchange, including when the DATA response was lost.
            try:
                smtp.close()
            except Exception:
                raise MailboxProviderError("smtp_close_unavailable", non_dispatch=not data_started) from None
