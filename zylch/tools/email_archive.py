"""Email archive manager with IMAP integration.

Uses IMAPClient (replaces Gmail API). All storage uses
Supabase (NO local filesystem per ARCHITECTURE.md).
"""

import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, List, Optional

from zylch.storage import Storage

logger = logging.getLogger(__name__)


class EmailArchiveManager:
    """Manages complete email archive using Supabase storage.

    All data stored in Supabase emails table (NO local filesystem per ARCHITECTURE.md).
    """

    def __init__(
        self,
        gmail_client,
        owner_id: str,
        supabase_storage: Optional[Storage] = None,
    ):
        """Initialize archive manager.

        Args:
            gmail_client: IMAPClient instance for email
            owner_id: User ID (required)
            supabase_storage: Optional Storage instance
        """
        self.gmail = gmail_client
        self.owner_id = owner_id
        self.supabase = (
            supabase_storage or Storage.get_instance()
        )
        self._connected = False

        logger.info(
            f"EmailArchiveManager initialized"
            f" for owner {owner_id}"
        )

    def _ensure_connected(self) -> None:
        """Ensure IMAP client is connected (lazy)."""
        if not self._connected:
            # IMAPClient auto-reconnects via
            # _ensure_connected(), but we call
            # connect() if not yet done
            if hasattr(self.gmail, '_conn'):
                if self.gmail._conn is None:
                    self.gmail.connect()
            else:
                # Legacy GmailClient compat
                if not self.gmail.service:
                    self.gmail.authenticate()
            self._connected = True

    def incremental_sync(
        self,
        days_back: Optional[int] = None,
        force_full: bool = False,
        on_progress: Optional[Callable[[int, str], None]] = None,
    ) -> Dict[str, Any]:
        """Sync emails from Gmail based on actual data in DB.

        Derives sync state from emails table - no separate sync_state needed.

        Args:
            days_back: Number of days to sync (default: 30)
            force_full: Ignored (kept for API compatibility)

        Returns:
            Sync results
        """
        from zylch.config import settings

        logger.info(
            f"Starting email sync"
            f" (days_back={days_back})..."
        )

        # Ensure Gmail is authenticated (lazy)
        self._ensure_connected()

        # Calculate target date
        now = datetime.now(timezone.utc)
        sync_days = days_back if days_back is not None else 30
        target_date = now - timedelta(days=sync_days)

        # Get oldest email date from DB to know current coverage
        oldest_email_date = self.supabase.get_oldest_email_date(self.owner_id)
        # Ensure timezone-aware for comparison with target_date
        if oldest_email_date and oldest_email_date.tzinfo is None:
            oldest_email_date = oldest_email_date.replace(tzinfo=timezone.utc)

        # Determine sync_from date
        if oldest_email_date is None:
            # No emails in DB - sync from target_date
            sync_from = target_date
            logger.info(f"No emails in DB. Syncing from {sync_from.strftime('%Y-%m-%d')}")
        elif target_date < oldest_email_date:
            # Need older emails - sync from target_date
            sync_from = target_date
            logger.info(
                f"Extending coverage from"
                f" {oldest_email_date.strftime('%Y-%m-%d')}"
                f" back to"
                f" {sync_from.strftime('%Y-%m-%d')}"
            )
        else:
            # Already have coverage - sync from oldest to catch any gaps
            sync_from = oldest_email_date
            logger.info(f"Syncing from oldest email date: {sync_from.strftime('%Y-%m-%d')}")

        try:
            # Fetch email IDs via IMAP date query
            query = (
                f"after:{sync_from.strftime('%Y/%m/%d')}"
            )
            logger.info(
                f"Searching for message IDs: {query}"
            )
            if on_progress:
                on_progress(10, "Searching mailbox...")
            message_ids = self.gmail.list_message_ids(
                query=query,
            )
            logger.info(
                f"Found {len(message_ids)} message IDs"
            )

            if not message_ids:
                return {
                    'success': True,
                    'messages_added': 0,
                    'messages_deleted': 0
                }

            # Get existing email IDs to filter dupes
            existing_emails = self.supabase.get_emails(
                self.owner_id,
                limit=len(message_ids) + 1000,
            )
            # Support both gmail_id and message_id
            existing_ids = set()
            for em in existing_emails:
                if em.get("gmail_id"):
                    existing_ids.add(em["gmail_id"])
                if em.get("message_id_header"):
                    existing_ids.add(
                        em["message_id_header"]
                    )

            new_message_ids = [
                msg_id
                for msg_id in message_ids
                if msg_id not in existing_ids
            ]
            logger.info(
                f"Found {len(new_message_ids)}"
                f" new messages to sync"
            )

            if not new_message_ids:
                return {
                    'success': True,
                    'messages_added': 0,
                    'messages_deleted': 0,
                    'total_fetched': 0
                }

            # Fetch full messages for the new IDs
            if on_progress:
                on_progress(
                    30,
                    f"Fetching {len(new_message_ids)} new emails...",
                )
            messages = self.gmail.get_batch(
                new_message_ids, format="full"
            )
            logger.info(
                f"Fetched {len(messages)}"
                f" full messages"
            )

            # Convert and store messages in batches
            if on_progress:
                on_progress(
                    60,
                    f"Storing {len(messages)} emails with embeddings...",
                )
            batch_size = settings.email_archive_batch_size
            total_stored = 0

            for i in range(
                0, len(messages), batch_size
            ):
                batch = messages[i : i + batch_size]
                try:
                    archive_messages = [
                        self._convert_message(msg)
                        for msg in batch
                    ]
                    stored = (
                        self.supabase.store_emails_batch(
                            self.owner_id,
                            archive_messages,
                        )
                    )
                    total_stored += stored

                    end = min(
                        i + batch_size, len(messages)
                    )
                    logger.info(
                        f"Progress: {end}"
                        f"/{len(messages)}"
                        f" processed"
                    )
                    if on_progress and len(messages) > 0:
                        pct = 60 + int(30 * end / len(messages))
                        on_progress(
                            pct,
                            f"Stored {end}/{len(messages)} emails",
                        )

                except Exception as e:
                    logger.error(
                        f"Error storing batch"
                        f" at offset {i}: {e}"
                    )

            logger.info(
                f"Email sync complete:"
                f" {total_stored} messages stored"
            )

            return {
                'success': True,
                'messages_added': total_stored,
                'messages_deleted': 0,
                'total_fetched': len(messages)
            }

        except Exception as e:
            logger.error(f"Email sync failed: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def _extract_emails_from_header(self, header: str) -> str:
        """Extract email addresses from RFC 5322 format.

        Parses headers like 'Name <email>, Name2 <email2>' and returns
        just the email addresses as comma-separated string.

        Args:
            header: Raw email header value

        Returns:
            Comma-separated email addresses
        """
        if not header:
            return ''

        emails = []
        for part in header.split(','):
            part = part.strip()
            if '<' in part and '>' in part:
                email = part.split('<')[1].split('>')[0].strip()
            else:
                email = part.strip()
            if email:
                emails.append(email)

        return ', '.join(emails)

    def _convert_message(
        self, msg: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Convert email message to archive format.

        Works with both IMAPClient and legacy GmailClient
        message formats.

        Args:
            msg: Message from IMAPClient or GmailClient

        Returns:
            Message in archive format
        """
        date_timestamp = None
        date_iso = None

        # 1. Try Date header first
        if msg.get("date"):
            try:
                dt = parsedate_to_datetime(
                    msg["date"]
                )
                date_timestamp = int(dt.timestamp())
                date_iso = dt.isoformat()
            except Exception as e:
                logger.warning(
                    f"Failed to parse Date header"
                    f" '{msg['date']}': {e}"
                )

        # 2. Fallback to internal_date (Gmail API)
        if (
            date_iso is None
            and msg.get("internal_date")
        ):
            try:
                ts = (
                    int(msg["internal_date"]) / 1000
                )
                dt = datetime.fromtimestamp(
                    ts, tz=timezone.utc
                )
                date_timestamp = int(ts)
                date_iso = dt.isoformat()
            except Exception as e:
                logger.warning(
                    f"Failed to parse"
                    f" internal_date: {e}"
                )

        # 3. Final fallback to current time
        if date_iso is None:
            now = datetime.now(timezone.utc)
            date_timestamp = int(now.timestamp())
            date_iso = now.isoformat()
            msg_id = msg.get(
                "message_id", msg.get("id", "?")
            )
            logger.warning(
                f"Using current time for msg"
                f" {msg_id} (no date parsed)"
            )

        # Extract from email/name
        from_email = msg.get("from_email")
        from_name = msg.get("from_name")
        if not from_email and msg.get("from"):
            from_str = msg["from"]
            if "<" in from_str and ">" in from_str:
                parts = from_str.split("<")
                from_name = parts[0].strip()
                from_email = (
                    parts[1].split(">")[0].strip()
                )
            else:
                from_email = from_str.strip()

        # Detect auto-reply
        from zylch.utils.auto_reply_detector import (
            detect_auto_reply,
        )

        auto_reply_headers = {
            "Auto-Submitted": msg.get(
                "auto_submitted"
            ),
            "X-Autoreply": msg.get("x_autoreply"),
            "Precedence": msg.get("precedence"),
            "X-Auto-Response-Suppress": msg.get(
                "x_auto_response_suppress"
            ),
        }
        is_auto_reply = detect_auto_reply(
            auto_reply_headers, from_email
        )

        # Use message_id as ID (IMAP) or id (Gmail)
        msg_id = msg.get(
            "message_id", msg.get("id", "")
        )

        # Body: IMAP provides body_plain/body_html,
        # Gmail provides body
        body_plain = msg.get(
            "body_plain", msg.get("body", "")
        )
        body_html = msg.get("body_html")

        return {
            "id": msg_id,
            "thread_id": msg.get("thread_id", ""),
            "from_email": from_email,
            "from_name": from_name,
            "to_email": self._extract_emails_from_header(
                msg.get("to", "")
            ),
            "cc_email": self._extract_emails_from_header(
                msg.get("cc", "")
            ),
            "subject": msg.get("subject", ""),
            "date": date_iso,
            "date_timestamp": date_timestamp,
            "snippet": msg.get("snippet", ""),
            "body_plain": body_plain,
            "body_html": body_html,
            "labels": msg.get("labels", []),
            "message_id_header": msg.get(
                "message_id", ""
            ),
            "in_reply_to": msg.get(
                "in_reply_to", ""
            ),
            "references": msg.get("references", ""),
            "is_auto_reply": is_auto_reply,
        }

    def get_thread_messages(
        self,
        thread_id: str,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Get all messages in a thread from archive.

        Args:
            thread_id: Gmail thread ID
            limit: Optional limit for recent messages only

        Returns:
            List of messages sorted by date
        """
        messages = self.supabase.get_thread_emails(self.owner_id, thread_id)
        if limit:
            messages = messages[:limit]
        return messages

    def get_threads_in_window(self, days_back: int = 30) -> List[str]:
        """Get all threads with activity in the last N days.

        Used by Intelligence Cache to analyze recent threads.

        Args:
            days_back: How many days to look back

        Returns:
            List of thread IDs with recent activity
        """
        return self.supabase.get_threads_in_window(self.owner_id, days_back)

    def search_messages(
        self,
        query: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Full-text search across all archived messages.

        Args:
            query: Search query (searches subject, body, from)
            from_date: Optional start date filter (not yet supported)
            to_date: Optional end date filter (not yet supported)
            limit: Max results

        Returns:
            List of matching messages
        """
        # Note: Date filters not yet supported in Supabase search_emails RPC
        return self.supabase.search_emails(self.owner_id, query, limit)

    def get_stats(self) -> Dict[str, Any]:
        """Get archive statistics.

        Returns:
            Dict with total messages, threads, date range, last sync
        """
        return self.supabase.get_email_stats(self.owner_id)
