"""IMAP/SMTP email client for Zylch standalone.

Replaces Gmail/Outlook OAuth API clients with standard
IMAP + app password. Works with any IMAP provider.
"""

import imaplib
import logging
import smtplib
import email as email_lib
from email.header import decode_header
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid, parseaddr
from typing import Any, Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

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
        fallback_prefix: Prefix for fallback host (e.g. "imap")
        fallback_port: Default port when no preset matches

    Returns:
        Tuple of (host, port)
    """
    domain = email_addr.split("@")[1].lower()
    preset = presets.get(domain)
    host = explicit_host or (preset[0] if preset else f"{fallback_prefix}.{domain}")
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

        Args:
            conn: Active IMAP connection
            msg_num: IMAP message sequence number

        Returns:
            Parsed email dict or None on error
        """
        status, data = conn.fetch(msg_num, "(RFC822)")
        if status != "OK" or not data[0]:
            return None

        raw = data[0][1]
        msg = email_lib.message_from_bytes(raw)

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
            # Auto-reply detection headers
            "auto_submitted": msg.get("Auto-Submitted", ""),
            "x_autoreply": msg.get("X-Autoreply", ""),
            "precedence": msg.get("Precedence", ""),
            "x_auto_response_suppress": msg.get("X-Auto-Response-Suppress", ""),
        }

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

    def list_message_ids(
        self,
        query: str = "",
        max_results: int = 0,
    ) -> List[str]:
        """List message IDs from INBOX + Sent folders.

        Syncs both received and sent emails so task detection
        can see user replies.

        Args:
            query: Gmail-style query (parsed for date filter)
            max_results: 0 = no limit (default). All matching
                emails are returned.

        Returns:
            List of Message-ID header values (deduplicated)
        """
        conn = self._ensure_connected()

        logger.debug(f"[IMAP] list_message_ids(query={query})")

        # Parse Gmail-style "after:YYYY/MM/DD" into IMAP
        imap_criteria = self._gmail_query_to_imap(query)

        # Collect IDs from INBOX + Sent
        all_ids = set()
        folders = ["INBOX"]
        sent_folder = self._find_sent_folder()
        if sent_folder:
            folders.append(sent_folder)

        for folder in folders:
            try:
                conn.select(folder, readonly=True)
            except Exception:
                logger.warning(
                    f"[IMAP] Cannot select {folder}",
                )
                continue

            ids = self._search_folder_ids(
                conn,
                imap_criteria,
                max_results,
            )
            all_ids.update(ids)
            logger.info(
                f"[IMAP] {folder}: {len(ids)} message IDs",
            )

        logger.info(
            f"[IMAP] Total unique IDs: {len(all_ids)}",
        )
        return list(all_ids)

    def _search_folder_ids(
        self,
        conn,
        imap_criteria: str,
        max_results: int = 0,
    ) -> List[str]:
        """Search current folder and return Message-IDs."""
        status, data = conn.search(None, imap_criteria)
        if status != "OK" or not data[0]:
            return []

        msg_nums = data[0].split()
        if max_results > 0:
            msg_nums = msg_nums[-max_results:]

        ids = []
        for num in msg_nums:
            try:
                status, hdr_data = conn.fetch(num, "(BODY[HEADER.FIELDS (MESSAGE-ID)])")
                if status == "OK" and hdr_data[0]:
                    raw = hdr_data[0][1]
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="replace")
                    # Extract Message-ID value
                    for line in raw.strip().splitlines():
                        if line.lower().startswith("message-id:"):
                            mid = line.split(":", 1)[1].strip()
                            ids.append(mid)
                            break
            except Exception as e:
                logger.warning(f"[IMAP] Error fetching ID for " f"msg {num}: {e}")

        logger.info(f"[IMAP] list_message_ids -> {len(ids)} IDs")
        return ids

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
        conn.select("INBOX", readonly=True)

        status, data = conn.search(
            None,
            f'(HEADER Message-ID "{message_id}")',
        )
        if status != "OK" or not data[0]:
            return []

        msg_num = data[0].split()[-1]
        status, msg_data = conn.fetch(
            msg_num,
            "(RFC822)",
        )
        if status != "OK" or not msg_data[0]:
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
        cc: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        references: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send email via SMTP.

        Args:
            to: Recipient email address
            subject: Email subject
            body: Plain text body
            cc: CC addresses (comma-separated)
            in_reply_to: Message-ID for reply threading
            references: References header for threading

        Returns:
            Dict with message_id of sent email
        """
        logger.debug(f"[SMTP] send(to={to}, subject={subject})")

        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = self.email_addr
        msg["To"] = to
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=self.email_addr.split("@")[1])

        if cc:
            msg["Cc"] = cc
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = references

        # Collect all recipients
        recipients = [addr.strip() for addr in to.split(",")]
        if cc:
            recipients.extend(addr.strip() for addr in cc.split(","))

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(self.email_addr, self.password)
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
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        references: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send email (GmailClient-compatible interface).

        Args:
            to: Recipient email
            subject: Email subject
            body: Email body
            from_email: Ignored (uses self.email_addr)
            cc: CC recipients
            bcc: BCC recipients (not supported in SMTP
                 envelope but added to recipients)
            in_reply_to: Message-ID for threading
            references: References header for threading
            thread_id: Ignored (IMAP uses Message-ID refs)

        Returns:
            Dict with sent message info
        """
        result = self.send(
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            in_reply_to=in_reply_to,
            references=references,
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
