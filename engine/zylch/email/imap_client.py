"""IMAP/SMTP email client for Zylch standalone.

Replaces Gmail/Outlook OAuth API clients with standard
IMAP + app password. Works with any IMAP provider.
"""

import imaplib
import logging
import mimetypes
import os
import re
import smtplib
import email as email_lib
from dataclasses import dataclass
from email.header import decode_header
from email.message import EmailMessage
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid, parseaddr
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


class IMAPError(RuntimeError):
    """Base class for IMAP failures that must NOT be read as 'no mail'.

    The sync path used to translate every protocol failure into an empty
    result: a SEARCH that returned NO looked exactly like an empty
    mailbox, so a broken folder scan advanced the sync floor as if it had
    seen everything. These exceptions exist so a caller has to decide
    explicitly, and so the cursor never advances over a failure.

    Only folder-wide failures raise. Per-message FETCH failures are
    returned as counted UID lists instead: one unreadable message must
    hold the cursor without costing the whole folder its scan.
    """


class IMAPFolderError(IMAPError):
    """SELECT/EXAMINE of a folder failed, or the folder is unusable."""


class IMAPSearchError(IMAPError):
    """A SEARCH command returned a non-OK status or an unparsable result."""


# IMAP date literals are `dd-Mon-yyyy` with ENGLISH month abbreviations
# (RFC 3501). `strftime("%b")` is locale-dependent — under it_IT it emits
# "ago" for August and the server rejects the search — so the month names
# are spelled out here instead.
_IMAP_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def format_imap_date(dt: datetime) -> str:
    """Format a datetime as an RFC 3501 date literal (locale-independent)."""
    return f"{dt.day:02d}-{_IMAP_MONTHS[dt.month - 1]}-{dt.year}"


@dataclass(frozen=True)
class FolderState:
    """What EXAMINE told us about a folder.

    ``uidvalidity`` anchors the sync cursor: if it changes, every UID we
    stored for that folder is meaningless. ``uidnext`` is the UID the
    next delivered message will get, so ``uidnext - 1`` is the highest
    UID that currently exists.
    """

    name: str
    uidvalidity: int
    uidnext: int
    exists: int


@dataclass(frozen=True)
class FolderScan:
    """The result of one read-only pass over a folder.

    ``unresolved_uids`` is the load-bearing field: those are UIDs the
    server matched but whose identity we could not establish. They are
    the reason a sync cursor is allowed to stall — silence about them is
    what turned a fetch failure into a permanently skipped message.
    """

    state: FolderState
    uids: List[int]
    message_ids: Dict[int, str]
    unresolved_uids: List[int]


# Common IMAP server presets: domain -> (imap_host, imap_port)
IMAP_PRESETS: Dict[str, tuple] = {
    "gmail.com": ("imap.gmail.com", 993),
    "googlemail.com": ("imap.gmail.com", 993),
    "outlook.com": ("outlook.office365.com", 993),
    "hotmail.com": ("outlook.office365.com", 993),
    "live.com": ("outlook.office365.com", 993),
    "yahoo.com": ("imap.mail.yahoo.com", 993),
    "yahoo.it": ("imap.mail.yahoo.com", 993),
    "icloud.com": ("imap.mail.me.com", 993),
    "me.com": ("imap.mail.me.com", 993),
    "fastmail.com": ("imap.fastmail.com", 993),
}

# Common SMTP server presets: domain -> (smtp_host, smtp_port)
SMTP_PRESETS: Dict[str, tuple] = {
    "gmail.com": ("smtp.gmail.com", 587),
    "googlemail.com": ("smtp.gmail.com", 587),
    "outlook.com": ("smtp.office365.com", 587),
    "hotmail.com": ("smtp.office365.com", 587),
    "live.com": ("smtp.office365.com", 587),
    "yahoo.com": ("smtp.mail.yahoo.com", 587),
    "yahoo.it": ("smtp.mail.yahoo.com", 587),
    "icloud.com": ("smtp.mail.me.com", 587),
    "me.com": ("smtp.mail.me.com", 587),
    "fastmail.com": ("smtp.fastmail.com", 587),
}


def _resolve_host(
    email_addr: str,
    explicit_host: Optional[str],
    explicit_port: Optional[int],
    presets: Dict[str, tuple],
    fallback_prefix: str,
    fallback_port: int,
) -> tuple:
    """Resolve host/port from presets or explicit values.

    Args:
        email_addr: User email address
        explicit_host: Explicitly provided host (overrides preset)
        explicit_port: Explicitly provided port (overrides preset)
        presets: Dict mapping domain -> (host, port)
        fallback_prefix: Protocol prefix for the Google fallback host
            ("imap" -> imap.gmail.com, "smtp" -> smtp.gmail.com)
        fallback_port: Default port when no preset matches

    Returns:
        Tuple of (host, port)
    """
    domain = email_addr.split("@")[1].lower()
    preset = presets.get(domain)
    # No preset for this domain → default to Google (imap.gmail.com /
    # smtp.gmail.com). Most custom domains are on Google Workspace (e.g.
    # @mrcall.ai, MX aspmx.l.google.com); the old `<prefix>.<domain>` guess
    # was usually a non-existent host. An explicit host always wins.
    host = explicit_host or (preset[0] if preset else f"{fallback_prefix}.gmail.com")
    port = explicit_port or (preset[1] if preset else fallback_port)
    return host, port


def _decode_header_value(raw: Optional[str]) -> str:
    """Decode RFC 2047 encoded header into plain string.

    Args:
        raw: Raw header value (may be encoded)

    Returns:
        Decoded unicode string
    """
    if not raw:
        return ""
    parts = decode_header(raw)
    decoded_parts = []
    for data, charset in parts:
        if isinstance(data, bytes):
            enc = charset or "utf-8"
            try:
                decoded_parts.append(data.decode(enc))
            except (UnicodeDecodeError, LookupError):
                decoded_parts.append(data.decode("latin-1", errors="replace"))
        else:
            decoded_parts.append(data)
    return "".join(decoded_parts)


def _extract_attachment_filenames(
    msg: email_lib.message.Message,
) -> List[str]:
    """Walk a parsed MIME message and collect attachment filenames.

    Recognizes a part as an attachment when it has a
    ``Content-Disposition: attachment`` header OR when it carries a
    ``filename`` parameter (covers some inline images sent with a name).
    Filenames are RFC 2047-decoded. Parts without a usable filename are
    skipped — we only surface things the user could meaningfully see.

    Returns:
        List of filename strings (may be empty).
    """
    if not msg.is_multipart():
        # Single-part messages can still be a bare attachment, but in
        # practice IMAP-delivered mail uses multipart for that. Keep
        # the simple case simple.
        disp = str(msg.get("Content-Disposition", ""))
        if "attachment" in disp.lower():
            name = msg.get_filename()
            if name:
                return [_decode_header_value(name)]
        return []

    names: List[str] = []
    for part in msg.walk():
        # Skip the multipart wrappers themselves.
        if part.get_content_maintype() == "multipart":
            continue
        disp = str(part.get("Content-Disposition", "")).lower()
        filename = part.get_filename()
        is_attachment = "attachment" in disp or bool(filename)
        if not is_attachment:
            continue
        if not filename:
            # Attachment-disposed part without a filename — skip rather
            # than invent one; the LLM only needs human-meaningful names.
            continue
        names.append(_decode_header_value(filename))
    return names


def _extract_plain_body(
    msg: email_lib.message.Message,
) -> tuple:
    """Extract plain text and HTML body from email message.

    Walks multipart messages recursively.

    Args:
        msg: Parsed email.message.Message

    Returns:
        Tuple of (plain_text, html_text)
    """
    plain = ""
    html = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if "attachment" in disp:
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset)
            except (UnicodeDecodeError, LookupError):
                text = payload.decode("latin-1", errors="replace")
            if ct == "text/plain" and not plain:
                plain = text
            elif ct == "text/html" and not html:
                html = text
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset)
            except (UnicodeDecodeError, LookupError):
                text = payload.decode("latin-1", errors="replace")
            ct = msg.get_content_type()
            if ct == "text/html":
                html = text
            else:
                plain = text
    # Fallback: extract text from HTML if no plain text
    if not plain and html:
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            plain = soup.get_text(separator="\n", strip=True)
        except Exception:
            pass

    return plain, html


def _parse_message_bytes(raw: Any) -> Optional[Dict[str, Any]]:
    """Parse raw RFC 822 bytes into the archive's message dict.

    Module-level (not a method) so the sequence-number path and the UID
    path share exactly one parser, and so it is testable without a
    connection. Returns None when ``raw`` is not bytes — a shape the
    server should never send, but one that must not read as "empty
    message" further up.
    """
    if not isinstance(raw, (bytes, bytearray)):
        logger.warning(f"[IMAP] _parse_message_bytes: unexpected payload type {type(raw)}")
        return None

    msg = email_lib.message_from_bytes(bytes(raw))

    # Decode headers
    subject = _decode_header_value(msg.get("Subject"))
    from_header = _decode_header_value(msg.get("From"))
    to_header = _decode_header_value(msg.get("To", ""))
    cc_header = _decode_header_value(msg.get("Cc", ""))
    date_header = msg.get("Date", "")
    message_id = msg.get("Message-ID", "")
    in_reply_to = msg.get("In-Reply-To", "")
    references_raw = msg.get("References", "")

    # Parse from name/email
    from_name, from_email = parseaddr(from_header)

    # Extract body
    body_plain, body_html = _extract_plain_body(msg)

    # Attachment metadata — filenames only, no bytes. The LLM and the
    # desktop Email tab need to know what files are present without
    # paying for a re-fetch via fetch_attachments().
    attachment_filenames = _extract_attachment_filenames(msg)

    # Thread ID: use References chain or Message-ID
    thread_id = ""
    if references_raw:
        refs = references_raw.strip().split()
        thread_id = refs[0] if refs else message_id
    elif in_reply_to:
        thread_id = in_reply_to
    else:
        thread_id = message_id

    return {
        "message_id": message_id.strip(),
        "from_email": from_email,
        "from_name": from_name,
        "from": from_header,
        "to_email": to_header,
        "to": to_header,
        "cc_email": cc_header,
        "cc": cc_header,
        "subject": subject,
        "date": date_header,
        "body_plain": body_plain,
        "body_html": body_html,
        "body": body_plain or body_html,
        "thread_id": thread_id.strip(),
        "in_reply_to": (in_reply_to.strip() if in_reply_to else ""),
        "references": (references_raw.strip() if references_raw else ""),
        "snippet": body_plain or body_html or "",
        # Attachment metadata. NEVER includes raw bytes — only filenames.
        "has_attachments": bool(attachment_filenames),
        "attachment_filenames": attachment_filenames,
        # Auto-reply detection headers
        "auto_submitted": msg.get("Auto-Submitted", ""),
        "x_autoreply": msg.get("X-Autoreply", ""),
        "precedence": msg.get("Precedence", ""),
        "x_auto_response_suppress": msg.get("X-Auto-Response-Suppress", ""),
    }


def _parse_uid_from_prefix(prefix: Any) -> Optional[int]:
    """Extract the UID from a FETCH response prefix.

    imaplib hands back entries shaped like
    ``(b'12 (UID 4711 BODY[HEADER.FIELDS (MESSAGE-ID)] {58}', b'...')``.
    We always ask for ``UID`` explicitly in the fetch item list so this
    match is not at the mercy of server-side response ordering.
    """
    if isinstance(prefix, (bytes, bytearray)):
        text = bytes(prefix).decode("utf-8", errors="replace")
    elif isinstance(prefix, str):
        text = prefix
    else:
        return None
    match = re.search(r"\bUID\s+(\d+)", text)
    return int(match.group(1)) if match else None


def _extract_message_id_header(raw: Any) -> str:
    """Pull the Message-ID value out of a HEADER.FIELDS fetch payload.

    Parsed with the email module rather than by splitting lines: RFC 5322
    allows a header to be folded across lines, and a long Message-ID
    (Exchange emits 90+ character ones) can legitimately arrive as
    ``Message-ID:\\r\\n <...>``. A line-based reader would call that
    message "no Message-ID" and skip it — silently losing exactly the
    kind of mail this whole change exists to stop losing.
    """
    if isinstance(raw, (bytes, bytearray)):
        payload = bytes(raw)
    elif isinstance(raw, str):
        payload = raw.encode("utf-8", errors="replace")
    else:
        return ""
    parsed = email_lib.message_from_bytes(payload)
    value = parsed.get("Message-ID")
    if not value:
        return ""
    # Unfold: the parser keeps the CRLF+WSP of a folded value.
    return " ".join(str(value).split())


class IMAPClient:
    """IMAP email client with SMTP sending support.

    Replaces GmailClient/OutlookClient for standalone mode.
    Uses standard imaplib/smtplib with app passwords.
    """

    def __init__(
        self,
        email_addr: str,
        password: str,
        imap_host: Optional[str] = None,
        imap_port: Optional[int] = None,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
    ):
        """Initialize IMAP/SMTP client.

        Auto-detects server from email domain if not provided.

        Args:
            email_addr: Full email address (e.g. user@gmail.com)
            password: App password (NOT account password)
            imap_host: IMAP server hostname (auto-detected)
            imap_port: IMAP server port (default 993)
            smtp_host: SMTP server hostname (auto-detected)
            smtp_port: SMTP server port (default 587)
        """
        self.email_addr = email_addr
        self.password = password

        self.imap_host, self.imap_port = _resolve_host(
            email_addr,
            imap_host,
            imap_port,
            IMAP_PRESETS,
            "imap",
            993,
        )
        self.smtp_host, self.smtp_port = _resolve_host(
            email_addr,
            smtp_host,
            smtp_port,
            SMTP_PRESETS,
            "smtp",
            587,
        )

        self._conn: Optional[imaplib.IMAP4_SSL] = None
        self._sent_folder: Optional[str] = None
        self._sent_folder_resolved: bool = False

        logger.debug(
            f"[IMAP] Configured for {email_addr} "
            f"imap={self.imap_host}:{self.imap_port} "
            f"smtp={self.smtp_host}:{self.smtp_port}"
        )

    def connect(self) -> None:
        """Connect and authenticate to IMAP server."""
        logger.debug(f"[IMAP] Connecting to " f"{self.imap_host}:{self.imap_port}")
        self._conn = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
        self._conn.login(self.email_addr, self.password)
        logger.info(f"[IMAP] Connected as {self.email_addr}")

    def disconnect(self) -> None:
        """Disconnect from IMAP server."""
        if self._conn:
            try:
                self._conn.logout()
            except Exception:
                pass
            self._conn = None
            logger.debug("[IMAP] Disconnected")

    def _ensure_connected(self) -> imaplib.IMAP4_SSL:
        """Ensure IMAP connection is active.

        Reconnects if the connection was dropped.

        Returns:
            Active IMAP connection

        Raises:
            ConnectionError: If connection cannot be established
        """
        if self._conn is None:
            self.connect()
        try:
            self._conn.noop()
        except Exception:
            logger.debug("[IMAP] Connection lost, reconnecting")
            self.connect()
        return self._conn

    def fetch_emails(
        self,
        folder: str = "INBOX",
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Fetch emails from a folder.

        Args:
            folder: IMAP folder name (default INBOX)
            since: Only fetch emails after this date
            limit: Max emails to fetch

        Returns:
            List of email dicts with: message_id, from_email,
            from_name, to_email, cc_email, subject, date,
            body_plain, body_html, thread_id, in_reply_to,
            references
        """
        conn = self._ensure_connected()

        logger.debug(f"[IMAP] fetch_emails(folder={folder}, " f"since={since}, limit={limit})")

        status, _ = conn.select(folder, readonly=True)
        if status != "OK":
            logger.error(f"[IMAP] Cannot select folder {folder}")
            return []

        # Build IMAP search criteria
        if since:
            date_str = since.strftime("%d-%b-%Y")
            criteria = f'(SINCE "{date_str}")'
        else:
            criteria = "ALL"

        status, data = conn.search(None, criteria)
        if status != "OK" or not data[0]:
            logger.debug(f"[IMAP] No messages match criteria " f"{criteria}")
            return []

        msg_nums = data[0].split()
        # Take most recent (last N)
        msg_nums = msg_nums[-limit:]

        logger.debug(f"[IMAP] Found {len(msg_nums)} messages, " f"fetching...")

        results = []
        for num in msg_nums:
            try:
                parsed = self._fetch_one(conn, num)
                if parsed:
                    results.append(parsed)
            except Exception as e:
                logger.warning(f"[IMAP] Error fetching msg {num}: {e}")

        logger.info(f"[IMAP] fetch_emails -> {len(results)} emails " f"from {folder}")
        return results

    def _fetch_one(
        self,
        conn: imaplib.IMAP4_SSL,
        msg_num: bytes,
    ) -> Optional[Dict[str, Any]]:
        """Fetch and parse a single email by sequence number.

        Uses ``BODY.PEEK[]`` rather than ``RFC822``: the latter is
        defined to set the ``\\Seen`` flag. Read-only SELECT hides that
        today, but a peek fetch means the sync path can never mark a
        customer's mail as read even if a caller opens the folder
        read/write.

        Args:
            conn: Active IMAP connection
            msg_num: IMAP message sequence number

        Returns:
            Parsed email dict or None on error
        """
        status, data = conn.fetch(msg_num, "(BODY.PEEK[])")
        if status != "OK" or not data or not data[0]:
            logger.warning(f"[IMAP] fetch({msg_num!r}) -> status={status!r}, no data")
            return None

        entry = data[0]
        if not isinstance(entry, tuple) or len(entry) < 2:
            logger.warning(f"[IMAP] fetch({msg_num!r}) -> unexpected response shape")
            return None

        return _parse_message_bytes(entry[1])

    def _find_sent_folder(self) -> Optional[str]:
        """Find the Sent mail folder name (cached per session).

        Uses IMAP LIST to find the folder with \\Sent flag.
        Returns the name quoted for IMAP SELECT.
        Result is cached — IMAP LIST is only called once.
        """
        if self._sent_folder_resolved:
            return self._sent_folder

        result = self._find_sent_folder_uncached()
        self._sent_folder = result
        self._sent_folder_resolved = True
        return result

    def _find_sent_folder_uncached(self) -> Optional[str]:
        """Find the Sent mail folder (no cache)."""
        conn = self._ensure_connected()
        status, folders = conn.list()
        if status != "OK":
            return None

        for folder_line in folders:
            decoded = folder_line.decode(
                "utf-8",
                errors="replace",
            )
            if "\\Sent" in decoded:
                # Extract folder name (last quoted string)
                parts = decoded.rsplit('"', 2)
                if len(parts) >= 2:
                    name = parts[-2]
                    logger.debug(
                        f"[IMAP] Found Sent folder: {name}",
                    )
                    return f'"{name}"'

        # Fallback: try common names
        for name in (
            '"[Gmail]/Sent Mail"',
            "Sent",
            '"Sent Messages"',
            "INBOX.Sent",
        ):
            try:
                status, _ = conn.select(name, readonly=True)
                if status == "OK":
                    logger.debug(
                        f"[IMAP] Sent folder fallback:" f" {name}",
                    )
                    return name
            except Exception:
                continue
        return None

    def find_archive_folder(self) -> Optional[str]:
        """Find the Archive/All-Mail folder name.

        Strategy:
          1. LIST and scan SPECIAL-USE flags: `\\All` (Gmail "All Mail",
             which is where Gmail's "Archive" button moves mail) wins
             over `\\Archive` (standard IMAP archive).
          2. Fallback to provider-specific common names.

        Returns the name quoted for IMAP SELECT/MOVE (so spaces and
        brackets work), or None if no archive-like folder is found.
        """
        conn = self._ensure_connected()
        status, folders = conn.list()
        if status != "OK":
            logger.warning("[IMAP] find_archive_folder: LIST failed")
            return None

        all_flag_name: Optional[str] = None
        archive_flag_name: Optional[str] = None

        for folder_line in folders:
            decoded = folder_line.decode("utf-8", errors="replace")
            # SPECIAL-USE flags show up in the flags segment before the
            # delimiter/name, e.g. `(\HasNoChildren \All) "/" "[Gmail]/All Mail"`.
            if "\\All" in decoded and all_flag_name is None:
                parts = decoded.rsplit('"', 2)
                if len(parts) >= 2:
                    all_flag_name = f'"{parts[-2]}"'
            if "\\Archive" in decoded and archive_flag_name is None:
                parts = decoded.rsplit('"', 2)
                if len(parts) >= 2:
                    archive_flag_name = f'"{parts[-2]}"'

        if all_flag_name:
            logger.debug(f"[IMAP] Archive folder (\\All): {all_flag_name}")
            return all_flag_name
        if archive_flag_name:
            logger.debug(f"[IMAP] Archive folder (\\Archive): {archive_flag_name}")
            return archive_flag_name

        # Fallbacks by convention.
        for name in (
            '"[Gmail]/All Mail"',
            "Archive",
            '"Archives"',
            "INBOX.Archive",
        ):
            try:
                status, _ = conn.select(name, readonly=True)
                if status == "OK":
                    logger.debug(f"[IMAP] Archive folder fallback: {name}")
                    return name
            except Exception:
                continue

        logger.warning("[IMAP] No archive folder found")
        return None

    def move_message_by_message_id(
        self,
        message_id_header: str,
        dest_folder: str,
        source_folder: str = "INBOX",
    ) -> bool:
        """Move a single message (identified by its RFC 822 Message-ID)
        from `source_folder` to `dest_folder`.

        Uses IMAP UID SEARCH on the Message-ID header, then UID MOVE
        (preferred) or UID COPY+EXPUNGE as fallback for servers without
        RFC 6851 MOVE. Returns True iff at least one message was moved
        or the source message was not present (already moved is a no-op
        success). Returns False on protocol errors.

        `dest_folder` must already be IMAP-quoted if it contains spaces
        or brackets — use `find_archive_folder()` output directly.
        """
        if not message_id_header:
            logger.debug("[IMAP] move_message_by_message_id: empty message-id")
            return False

        conn = self._ensure_connected()

        # Open source folder read/write — MOVE/COPY require it.
        status, _ = conn.select(source_folder, readonly=False)
        if status != "OK":
            logger.warning(f"[IMAP] move: cannot select {source_folder}")
            return False

        # UID SEARCH HEADER Message-ID "<...>". The header value must be
        # quoted. imaplib takes each token as a separate argument.
        try:
            status, data = conn.uid(
                "SEARCH",
                None,
                "HEADER",
                "Message-ID",
                message_id_header,
            )
        except Exception as e:
            logger.warning(f"[IMAP] move: UID SEARCH failed: {e}")
            return False

        if status != "OK" or not data or not data[0]:
            # Not found in source folder. This is common when the user
            # already archived from another client, or the message was
            # only ever in Sent. Treat as success — the local flag is
            # what the UI reads.
            logger.debug(
                f"[IMAP] move: message-id {message_id_header} not in "
                f"{source_folder} (already moved?)"
            )
            return True

        uids = data[0].split()
        if not uids:
            return True

        uid_set = b",".join(uids).decode("ascii")

        # Try UID MOVE first (RFC 6851).
        try:
            status, _ = conn.uid("MOVE", uid_set, dest_folder)
            if status == "OK":
                logger.debug(
                    f"[IMAP] MOVE uid={uid_set} src={source_folder} " f"dst={dest_folder} -> OK"
                )
                return True
            logger.debug(f"[IMAP] UID MOVE returned {status!r}, falling back to COPY+EXPUNGE")
        except Exception as e:
            logger.debug(f"[IMAP] UID MOVE not supported ({e}), falling back to COPY+EXPUNGE")

        # Fallback: COPY + STORE \Deleted + EXPUNGE.
        try:
            status, _ = conn.uid("COPY", uid_set, dest_folder)
            if status != "OK":
                logger.warning(f"[IMAP] UID COPY failed for uid={uid_set} -> {dest_folder}")
                return False
            conn.uid("STORE", uid_set, "+FLAGS", "(\\Deleted)")
            conn.expunge()
            logger.debug(
                f"[IMAP] COPY+EXPUNGE uid={uid_set} src={source_folder} dst={dest_folder} -> OK"
            )
            return True
        except Exception as e:
            logger.warning(f"[IMAP] COPY+EXPUNGE failed: {e}")
            return False

    def sync_folders(self) -> List[str]:
        """Folders the archive sync must scan, in scan order.

        INBOX first (cheapest, the common case), then Sent (so task
        detection sees our own replies), then the provider's
        Archive/All-Mail folder.

        The archive folder is not optional bonus coverage: on Gmail the
        "Archive" button only removes the INBOX label, so a message that
        is filtered or archived — by a human in Superhuman, or by the
        operator's own `emails.archive` — disappears from INBOX while
        still being live mail. Scanning INBOX+Sent only made such a
        message invisible to the archive forever.

        Returns:
            Ordered, de-duplicated list of IMAP folder names (quoted
            where the provider needs it). Never empty: INBOX always
            participates.
        """
        folders = ["INBOX"]
        seen = {"inbox"}

        for finder, label in (
            (self._find_sent_folder, "sent"),
            (self.find_archive_folder, "archive"),
        ):
            try:
                name = finder()
            except Exception as e:
                logger.error(f"[IMAP] sync_folders: {label} folder discovery failed: {e}")
                continue
            if not name:
                logger.warning(f"[IMAP] sync_folders: no {label} folder found")
                continue
            key = name.strip('"').lower()
            if key in seen:
                continue
            seen.add(key)
            folders.append(name)

        logger.info(f"[IMAP] sync_folders -> {folders}")
        return folders

    def examine_folder(self, folder: str) -> FolderState:
        """EXAMINE a folder read-only and report its UID state.

        Args:
            folder: IMAP folder name, quoted if it needs quoting.

        Returns:
            FolderState with UIDVALIDITY / UIDNEXT / EXISTS.

        Raises:
            IMAPFolderError: the folder could not be selected. NEVER
                returns a neutral value — "cannot open the folder" and
                "the folder is empty" must not be indistinguishable.
        """
        conn = self._ensure_connected()

        try:
            status, data = conn.select(folder, readonly=True)
        except Exception as e:
            raise IMAPFolderError(f"EXAMINE {folder} raised: {e}") from e

        if status != "OK":
            raise IMAPFolderError(f"EXAMINE {folder} -> status={status!r} data={data!r}")

        exists = 0
        if data and data[0] not in (None, b"", ""):
            try:
                exists = int(data[0])
            except (TypeError, ValueError):
                exists = 0

        def _code(name: str, default: int) -> int:
            typ, values = conn.response(name)
            if not values or values[0] in (None, b"", ""):
                return default
            try:
                return int(values[0])
            except (TypeError, ValueError):
                return default

        uidvalidity = _code("UIDVALIDITY", 0)
        uidnext = _code("UIDNEXT", 0)

        if uidvalidity <= 0:
            # Without UIDVALIDITY the cursor has no anchor and stored
            # UIDs cannot be trusted. Refuse rather than sync blind.
            raise IMAPFolderError(f"EXAMINE {folder} returned no usable UIDVALIDITY")

        state = FolderState(
            name=folder,
            uidvalidity=uidvalidity,
            uidnext=uidnext,
            exists=exists,
        )
        logger.debug(
            f"[IMAP] examine_folder(folder={folder}) -> uidvalidity={uidvalidity} "
            f"uidnext={uidnext} exists={exists}"
        )
        return state

    def _uid_search_selected(self, folder: str, criteria: str) -> List[int]:
        """UID SEARCH in the ALREADY-selected folder.

        Raises:
            IMAPSearchError: on a non-OK status or an unparsable
                response. A failed search must never look like an empty
                mailbox — that is precisely how the old code let a
                broken scan advance the sync floor.
        """
        conn = self._ensure_connected()
        try:
            status, data = conn.uid("SEARCH", None, criteria)
        except Exception as e:
            raise IMAPSearchError(f"UID SEARCH {criteria!r} in {folder} raised: {e}") from e

        if status != "OK":
            raise IMAPSearchError(
                f"UID SEARCH {criteria!r} in {folder} -> status={status!r} data={data!r}"
            )

        if not data or data[0] in (None, b"", ""):
            logger.debug(f"[IMAP] UID SEARCH {criteria!r} in {folder} -> 0 uids")
            return []

        raw = data[0]
        if isinstance(raw, (bytes, bytearray)):
            tokens = bytes(raw).split()
        else:
            tokens = str(raw).split()

        uids: List[int] = []
        for token in tokens:
            try:
                uids.append(int(token))
            except (TypeError, ValueError):
                raise IMAPSearchError(
                    f"UID SEARCH {criteria!r} in {folder} returned non-numeric uid {token!r}"
                )

        uids.sort()
        logger.debug(f"[IMAP] UID SEARCH {criteria!r} in {folder} -> {len(uids)} uids")
        return uids

    def uid_search(self, folder: str, criteria: str) -> List[int]:
        """EXAMINE ``folder`` then UID SEARCH it. Raises on failure."""
        self.examine_folder(folder)
        return self._uid_search_selected(folder, criteria)

    def _fetch_message_ids_selected(
        self,
        folder: str,
        uids: Sequence[int],
        chunk_size: int = 200,
    ) -> Tuple[Dict[int, str], List[int]]:
        """Batched Message-ID header fetch in the ALREADY-selected folder.

        Returns:
            (uid -> Message-ID header value, list of UIDs we failed to
            resolve). The failure list is what blocks the sync cursor:
            a UID whose identity we could not establish must not be
            skipped over silently.
        """
        conn = self._ensure_connected()
        resolved: Dict[int, str] = {}
        failed: List[int] = []

        wanted = sorted(set(int(u) for u in uids))
        for start in range(0, len(wanted), chunk_size):
            chunk = wanted[start : start + chunk_size]
            uid_set = ",".join(str(u) for u in chunk)
            data: Any = []
            try:
                status, data = conn.uid(
                    "FETCH",
                    uid_set,
                    "(UID BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])",
                )
            except Exception as e:
                logger.error(
                    f"[IMAP] header FETCH raised for {len(chunk)} uids in {folder}: {e}",
                )
                status, data = "NO", []

            if status != "OK":
                logger.error(
                    f"[IMAP] header FETCH -> status={status!r} for {len(chunk)} uids in "
                    f"{folder}; retrying them one by one to isolate the bad uid(s)",
                )
                data = []

            for entry in data or []:
                if not isinstance(entry, tuple) or len(entry) < 2:
                    continue
                uid = _parse_uid_from_prefix(entry[0])
                if uid is None:
                    continue
                message_id = _extract_message_id_header(entry[1])
                resolved[uid] = message_id

            missing = [u for u in chunk if u not in resolved]
            for uid in missing:
                # One retry on its own — a single bad message must not
                # cost us the whole batch, and a UID that vanished
                # between SEARCH and FETCH (expunged by another client)
                # is a legitimate, loggable no-op rather than a failure.
                single = self._fetch_single_message_id(folder, uid)
                if single is None:
                    failed.append(uid)
                else:
                    resolved[uid] = single

        if failed:
            logger.error(
                f"[IMAP] {folder}: could not resolve Message-ID for {len(failed)} uid(s): "
                f"{failed} — the sync cursor will NOT advance past the lowest of them"
            )
        logger.debug(
            f"[IMAP] _fetch_message_ids_selected({folder}) -> {len(resolved)} resolved, "
            f"{len(failed)} failed"
        )
        return resolved, failed

    def _fetch_single_message_id(self, folder: str, uid: int) -> Optional[str]:
        """Retry a single UID's Message-ID fetch. None means 'failed'.

        An empty string is a valid answer: the message exists but has no
        Message-ID header. That is a data problem, not a fetch failure,
        and is handled by the caller.
        """
        conn = self._ensure_connected()
        try:
            status, data = conn.uid(
                "FETCH",
                str(uid),
                "(UID BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])",
            )
        except Exception as e:
            logger.warning(f"[IMAP] {folder}: single header FETCH uid={uid} raised: {e}")
            return None
        if status != "OK":
            logger.warning(f"[IMAP] {folder}: single header FETCH uid={uid} -> {status!r}")
            return None
        for entry in data or []:
            if isinstance(entry, tuple) and len(entry) >= 2:
                return _extract_message_id_header(entry[1])
        # No tuple in the response: on Gmail this is what an expunged
        # UID looks like. Nothing to ingest and nothing to block on.
        logger.warning(
            f"[IMAP] {folder}: uid={uid} returned no data (expunged since SEARCH?) — skipping"
        )
        return ""

    def scan_folder(
        self,
        folder: str,
        criteria_builder: Callable[[FolderState], str],
    ) -> "FolderScan":
        """One read-only pass over a folder: EXAMINE + UID SEARCH + IDs.

        Holds the folder selection for the whole pass so a sync tick
        costs one SELECT, one SEARCH and one batched header FETCH per
        folder.

        Args:
            folder: IMAP folder name (quoted if needed).
            criteria_builder: called with the FolderState that EXAMINE
                returned and must return raw IMAP SEARCH criteria, e.g.
                ``(OR UID 4711:* SINCE "25-Jul-2026")``. It is a callback
                rather than a plain string because the criteria depend on
                UIDVALIDITY — the caller has to see the folder's current
                UIDVALIDITY before it can decide whether its stored UID
                cursor is still meaningful — and doing that with a second
                EXAMINE would double the round trips on every tick.

        Returns:
            FolderScan with the folder state, the matching UIDs, the
            uid -> Message-ID map, and the UIDs that could not be
            resolved.

        Raises:
            IMAPFolderError, IMAPSearchError: never swallowed here.
        """
        state = self.examine_folder(folder)
        criteria = criteria_builder(state)
        uids = self._uid_search_selected(folder, criteria)
        message_ids, failed = self._fetch_message_ids_selected(folder, uids)
        logger.info(
            f"[IMAP] scan_folder({folder}) criteria={criteria!r} -> {len(uids)} uid(s), "
            f"{len(message_ids)} resolved, {len(failed)} unresolved "
            f"(uidvalidity={state.uidvalidity}, uidnext={state.uidnext})"
        )
        return FolderScan(
            state=state,
            uids=uids,
            message_ids=message_ids,
            unresolved_uids=failed,
        )

    def fetch_messages_by_uid(
        self,
        folder: str,
        uids: Sequence[int],
    ) -> Tuple[Dict[int, Dict[str, Any]], List[int]]:
        """Fetch full messages by UID from ``folder`` (read-only, peek).

        Args:
            folder: IMAP folder name (quoted if needed).
            uids: UIDs to fetch.

        Returns:
            (uid -> parsed message dict, list of UIDs that failed).
            Failures are counted and returned, never silently dropped:
            the caller needs them to hold the sync cursor back.

        Raises:
            IMAPFolderError: the folder could not be examined.
        """
        wanted = sorted(set(int(u) for u in uids))
        if not wanted:
            return {}, []

        self.examine_folder(folder)
        conn = self._ensure_connected()

        messages: Dict[int, Dict[str, Any]] = {}
        failed: List[int] = []

        for uid in wanted:
            try:
                status, data = conn.uid("FETCH", str(uid), "(UID BODY.PEEK[])")
            except Exception as e:
                logger.error(f"[IMAP] {folder}: FETCH uid={uid} raised: {e}")
                failed.append(uid)
                continue
            if status != "OK":
                logger.error(f"[IMAP] {folder}: FETCH uid={uid} -> status={status!r}")
                failed.append(uid)
                continue

            parsed = None
            for entry in data or []:
                if isinstance(entry, tuple) and len(entry) >= 2:
                    parsed = _parse_message_bytes(entry[1])
                    break
            if parsed is None:
                logger.error(f"[IMAP] {folder}: FETCH uid={uid} returned no message body")
                failed.append(uid)
                continue
            messages[uid] = parsed

        if failed:
            logger.error(
                f"[IMAP] {folder}: {len(failed)}/{len(wanted)} message fetch(es) FAILED: {failed}"
            )
        logger.info(
            f"[IMAP] fetch_messages_by_uid({folder}) -> {len(messages)}/{len(wanted)} fetched, "
            f"{len(failed)} failed"
        )
        return messages, failed

    def get_message(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Get a single message by Message-ID header.

        Searches INBOX and Sent folders.

        Args:
            message_id: RFC 5322 Message-ID value

        Returns:
            Parsed email dict or None
        """
        conn = self._ensure_connected()

        logger.debug(f"[IMAP] get_message(message_id={message_id})")

        # Search INBOX first, then Sent
        folders = ["INBOX"]
        sent = self._find_sent_folder()
        if sent:
            folders.append(sent)

        for folder in folders:
            try:
                conn.select(folder, readonly=True)
            except Exception:
                continue

            status, data = conn.search(
                None,
                f'(HEADER Message-ID "{message_id}")',
            )
            if status == "OK" and data[0]:
                msg_num = data[0].split()[-1]
                return self._fetch_one(conn, msg_num)

        logger.debug(f"[IMAP] Message not found: {message_id}")
        return None

    def fetch_attachments(
        self,
        message_id: str,
        save_dir: str = "/tmp/zylch/attachments",
    ) -> List[Dict[str, str]]:
        """Download attachments from an email.

        Args:
            message_id: RFC 5322 Message-ID value
            save_dir: Directory to save files

        Returns:
            List of {"filename", "content_type", "path"}
        """
        import os

        conn = self._ensure_connected()

        # Search across folders, not just INBOX. On Gmail an *archived*
        # message lives only in "[Gmail]/All Mail" (the Archive button just
        # removes the INBOX label), and a message the user sent lives in
        # Sent — INBOX-only meant attachments on archived/sent mail came
        # back as "no attachments found" even though the file is right
        # there. INBOX first (cheapest, the common case), then archive,
        # then Sent; stop at the first folder that has the message.
        folders = ["INBOX"]
        archive = self.find_archive_folder()
        if archive and archive not in folders:
            folders.append(archive)
        sent = self._find_sent_folder()
        if sent and sent not in folders:
            folders.append(sent)

        msg_data = None
        for folder in folders:
            try:
                status, _ = conn.select(folder, readonly=True)
                if status != "OK":
                    continue
                status, data = conn.search(
                    None,
                    f'(HEADER Message-ID "{message_id}")',
                )
                if status != "OK" or not data or not data[0]:
                    continue
                msg_num = data[0].split()[-1]
                status, fetched = conn.fetch(msg_num, "(RFC822)")
                if status == "OK" and fetched and fetched[0]:
                    msg_data = fetched
                    logger.debug(f"[IMAP] fetch_attachments: found {message_id} in {folder}")
                    break
            except Exception as e:
                logger.warning(f"[IMAP] fetch_attachments: folder {folder}: {e}")
                continue

        if msg_data is None:
            logger.debug(f"[IMAP] fetch_attachments: message {message_id} not found in {folders}")
            return []

        msg = email_lib.message_from_bytes(msg_data[0][1])
        os.makedirs(save_dir, exist_ok=True)

        results = []
        for part in msg.walk():
            disp = str(
                part.get("Content-Disposition", ""),
            )
            if "attachment" not in disp:
                continue

            filename = part.get_filename()
            if not filename:
                filename = f"attachment_{len(results)}"
            filename = _decode_header_value(filename)

            payload = part.get_payload(decode=True)
            if not payload:
                continue

            path = os.path.join(save_dir, filename)
            with open(path, "wb") as f:
                f.write(payload)

            results.append(
                {
                    "filename": filename,
                    "content_type": part.get_content_type(),
                    "path": path,
                    "size": len(payload),
                },
            )
            logger.info(
                f"[IMAP] Saved attachment:" f" {filename} ({len(payload)} bytes)",
            )

        return results

    def get_batch(
        self,
        message_ids: List[str],
        format: str = "full",
    ) -> List[Dict[str, Any]]:
        """Get multiple messages by Message-ID headers.

        Provides interface compatibility with GmailClient.

        Args:
            message_ids: List of Message-ID values
            format: Ignored (kept for API compat)

        Returns:
            List of parsed email dicts
        """
        logger.debug(f"[IMAP] get_batch(count={len(message_ids)})")
        results = []
        for mid in message_ids:
            msg = self.get_message(mid)
            if msg:
                results.append(msg)
        logger.info(f"[IMAP] get_batch -> {len(results)}" f"/{len(message_ids)} fetched")
        return results

    def search(
        self,
        query: str,
        folder: str = "INBOX",
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Search emails by keyword.

        Uses IMAP SEARCH TEXT command for server-side search.

        Args:
            query: Search keywords
            folder: IMAP folder to search
            limit: Max results

        Returns:
            List of matching email dicts
        """
        conn = self._ensure_connected()

        logger.debug(f"[IMAP] search(query={query}, " f"folder={folder}, limit={limit})")

        conn.select(folder, readonly=True)

        # Build IMAP search criteria from query
        imap_criteria = self._gmail_query_to_imap(query)

        status, data = conn.search(None, imap_criteria)
        if status != "OK" or not data[0]:
            logger.debug(f"[IMAP] No search results for: {query}")
            return []

        msg_nums = data[0].split()[-limit:]

        results = []
        for num in msg_nums:
            try:
                parsed = self._fetch_one(conn, num)
                if parsed:
                    results.append(parsed)
            except Exception as e:
                logger.warning(f"[IMAP] Error fetching search " f"result {num}: {e}")

        logger.info(f"[IMAP] search -> {len(results)} results " f"for '{query}'")
        return results

    def search_messages(
        self,
        query: str,
        max_results: int = 50,
    ) -> List[Dict[str, Any]]:
        """Search messages (GmailClient-compatible interface).

        Args:
            query: Gmail-style search query
            max_results: Maximum results

        Returns:
            List of email dicts
        """
        return self.search(query=query, limit=max_results)

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        in_reply_to: Optional[str] = None,
        references: Optional[str] = None,
        attachment_paths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Send email via SMTP.

        Args:
            to: Recipient email address (or comma-separated list).
            subject: Email subject.
            body: Plain text body.
            cc: Optional list of CC email addresses. Added to the Cc
                header and to the SMTP recipient list.
            bcc: Optional list of BCC email addresses. Added to the
                SMTP recipient list but NOT to any header (Bcc is
                invisible to other recipients).
            in_reply_to: Message-ID for reply threading.
            references: References header for threading.
            attachment_paths: Optional list of local file paths to attach.
                When present, the message is built as a multipart using
                ``email.message.EmailMessage``; when absent, legacy
                ``MIMEText`` is used for backwards compatibility.

        Returns:
            Dict with message_id of sent email.
        """
        cc_list = [a.strip() for a in (cc or []) if a and a.strip()]
        bcc_list = [a.strip() for a in (bcc or []) if a and a.strip()]

        logger.debug(
            f"[SMTP] send(to={to}, subject={subject},"
            f" cc={len(cc_list)}, bcc={len(bcc_list)},"
            f" attachments={len(attachment_paths or [])})"
        )

        has_attachments = bool(attachment_paths)
        msg: Any
        if has_attachments:
            msg = EmailMessage()
            msg.set_content(body)
        else:
            msg = MIMEText(body, "plain", "utf-8")

        msg["From"] = self.email_addr
        msg["To"] = to
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=self.email_addr.split("@")[1])

        if cc_list:
            # Cc header is visible to all recipients.
            msg["Cc"] = ", ".join(cc_list)
        # NOTE: NEVER set a Bcc header. Bcc is implicit and must only be
        # delivered via the SMTP envelope (to_addrs below).
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = references

        if has_attachments:
            for path in attachment_paths or []:
                if not os.path.isfile(path):
                    raise FileNotFoundError(f"Attachment not found: {path}")
                ctype, _ = mimetypes.guess_type(path)
                if ctype is None:
                    maintype, subtype = "application", "octet-stream"
                else:
                    maintype, subtype = ctype.split("/", 1)
                with open(path, "rb") as fh:
                    data = fh.read()
                msg.add_attachment(
                    data,
                    maintype=maintype,
                    subtype=subtype,
                    filename=os.path.basename(path),
                )

        # Collect all recipients for the SMTP envelope. BCC recipients
        # must be included here so SMTP delivers to them, but we already
        # omitted the Bcc header above so they remain invisible to
        # To/Cc recipients.
        recipients = [addr.strip() for addr in to.split(",") if addr.strip()]
        recipients.extend(cc_list)
        recipients.extend(bcc_list)

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(self.email_addr, self.password)
                if has_attachments:
                    # EmailMessage: use send_message so envelope headers are
                    # handled consistently with multipart payloads.
                    smtp.send_message(msg, self.email_addr, recipients)
                else:
                    smtp.sendmail(
                        self.email_addr,
                        recipients,
                        msg.as_string(),
                    )

            sent_id = msg["Message-ID"]
            logger.info(f"[SMTP] Email sent to {to}: {subject} " f"(id={sent_id})")
            return {"id": sent_id, "status": "sent"}

        except Exception as e:
            logger.error(f"[SMTP] Failed to send: {e}")
            raise

    def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        from_email: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        in_reply_to: Optional[str] = None,
        references: Optional[str] = None,
        thread_id: Optional[str] = None,
        attachment_paths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Send email (GmailClient-compatible interface).

        Args:
            to: Recipient email.
            subject: Email subject.
            body: Email body.
            from_email: Ignored (uses self.email_addr).
            cc: Optional list of CC recipients. Appears in the Cc
                header and in the SMTP envelope.
            bcc: Optional list of BCC recipients. Added to the SMTP
                envelope ONLY — no Bcc header is emitted.
            in_reply_to: Message-ID for threading.
            references: References header for threading.
            thread_id: Ignored (IMAP uses Message-ID refs).
            attachment_paths: Local file paths to attach.

        Returns:
            Dict with sent message info.
        """
        result = self.send(
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
            in_reply_to=in_reply_to,
            references=references,
            attachment_paths=attachment_paths,
        )
        return result

    def _gmail_query_to_imap(self, query: str) -> str:
        """Convert Gmail-style query to IMAP SEARCH criteria.

        Supports:
        - after:YYYY/MM/DD -> SINCE DD-Mon-YYYY
        - from:addr -> FROM addr
        - to:addr -> TO addr
        - OR operator -> OR (...)
        - bare text -> TEXT "..."

        Args:
            query: Gmail-style search query

        Returns:
            IMAP SEARCH criteria string
        """
        import re

        if not query or not query.strip():
            return "ALL"

        parts = []
        remaining = query.strip()

        # Extract after: date
        after_match = re.search(r"after:(\d{4})/(\d{2})/(\d{2})", remaining)
        if after_match:
            y, m, d = after_match.groups()
            dt = datetime(int(y), int(m), int(d))
            imap_date = dt.strftime("%d-%b-%Y")
            parts.append(f'SINCE "{imap_date}"')
            remaining = remaining[: after_match.start()] + remaining[after_match.end() :]

        # Extract from: and to: directives
        for directive in ("from", "to"):
            pattern = rf"{directive}:(\S+)"
            match = re.search(pattern, remaining)
            if match:
                value = match.group(1)
                imap_key = directive.upper()
                parts.append(f'{imap_key} "{value}"')
                remaining = remaining[: match.start()] + remaining[match.end() :]

        # Handle OR operator for remaining text
        remaining = remaining.strip()
        if remaining:
            # Check for "X OR Y" pattern
            or_match = re.match(r"(.+?)\s+OR\s+(.+)", remaining)
            if or_match:
                left = or_match.group(1).strip()
                right = or_match.group(2).strip()
                parts.append(f'OR TEXT "{left}" TEXT "{right}"')
            elif remaining:
                parts.append(f'TEXT "{remaining}"')

        if not parts:
            return "ALL"

        # IMAP search: multiple criteria are ANDed
        result = " ".join(parts)
        logger.debug(f"[IMAP] Query '{query}' -> IMAP '{result}'")
        return result
