"""Email archive manager with Gmail API integration.

All storage uses Supabase (NO local filesystem per ARCHITECTURE.md).
"""

import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)


class EmailArchiveManager:
    """Manages complete email archive using Supabase storage.

    All data stored in Supabase emails table (NO local filesystem per ARCHITECTURE.md).
    """

    def __init__(
        self,
        gmail_client,
        owner_id: str,
        supabase_storage: Optional[SupabaseStorage] = None
    ):
        """Initialize archive manager.

        Args:
            gmail_client: GmailClient instance for fetching emails
            owner_id: User's Firebase UID (required)
            supabase_storage: Optional SupabaseStorage instance (uses singleton if not provided)
        """
        self.gmail = gmail_client
        self.owner_id = owner_id
        self.supabase = supabase_storage or SupabaseStorage.get_instance()
        self._authenticated = False

        # NOTE: Gmail authentication is now LAZY - only when actually needed
        # This allows the agent to initialize without valid Gmail credentials

        logger.info(f"EmailArchiveManager using Supabase for owner {owner_id}")

    def _ensure_authenticated(self) -> None:
        """Ensure Gmail client is authenticated (lazy authentication)."""
        if not self._authenticated and not self.gmail.service:
            self.gmail.authenticate()
            self._authenticated = True

    def incremental_sync(self, days_back: Optional[int] = None, force_full: bool = False) -> Dict[str, Any]:
        """Sync emails from Gmail based on actual data in DB.

        Derives sync state from emails table - no separate sync_state needed.

        Args:
            days_back: Number of days to sync (default: 30)
            force_full: Ignored (kept for API compatibility)

        Returns:
            Sync results
        """
        from zylch.config import settings

        logger.info(f"🔄 Starting email sync (days_back={days_back})...")

        # Ensure Gmail is authenticated (lazy)
        self._ensure_authenticated()

        # Calculate target date
        now = datetime.now(timezone.utc)
        sync_days = days_back if days_back is not None else 30
        target_date = now - timedelta(days=sync_days)

        # Get oldest email date from DB to know current coverage
        oldest_email_date = self.supabase.get_oldest_email_date(self.owner_id)

        # Determine sync_from date
        if oldest_email_date is None:
            # No emails in DB - sync from target_date
            sync_from = target_date
            logger.info(f"No emails in DB. Syncing from {sync_from.strftime('%Y-%m-%d')}")
        elif target_date < oldest_email_date:
            # Need older emails - sync from target_date
            sync_from = target_date
            logger.info(f"Extending coverage from {oldest_email_date.strftime('%Y-%m-%d')} back to {sync_from.strftime('%Y-%m-%d')}")
        else:
            # Already have coverage - sync from oldest to catch any gaps
            sync_from = oldest_email_date
            logger.info(f"Syncing from oldest email date: {sync_from.strftime('%Y-%m-%d')}")

        try:
            # Fetch email IDs from Gmail using date query
            query = f"after:{sync_from.strftime('%Y/%m/%d')}"
            logger.info(f"Searching Gmail for message IDs: {query}")
            message_ids = self.gmail.list_message_ids(query=query, max_results=5000)
            logger.info(f"Found {len(message_ids)} message IDs in Gmail")

            if not message_ids:
                return {
                    'success': True,
                    'messages_added': 0,
                    'messages_deleted': 0
                }

            # Get existing email IDs from Supabase to filter out duplicates
            existing_emails = self.supabase.get_emails(self.owner_id, limit=len(message_ids) + 1000)
            existing_ids = {email['gmail_id'] for email in existing_emails}

            new_message_ids = [msg_id for msg_id in message_ids if msg_id not in existing_ids]
            logger.info(f"Found {len(new_message_ids)} new messages to sync")

            if not new_message_ids:
                return {
                    'success': True,
                    'messages_added': 0,
                    'messages_deleted': 0,
                    'total_fetched': 0
                }

            # Fetch full messages for the new IDs
            messages = self.gmail.get_batch(new_message_ids, format='full')
            logger.info(f"Fetched {len(messages)} full messages from Gmail")

            # Convert and store messages in batches
            batch_size = settings.email_archive_batch_size
            total_stored = 0

            for i in range(0, len(messages), batch_size):
                batch = messages[i:i + batch_size]
                try:
                    archive_messages = [self._convert_message(msg) for msg in batch]
                    stored = self.supabase.store_emails_batch(self.owner_id, archive_messages)
                    total_stored += stored

                    if (i + batch_size) % 500 == 0 or (i + batch_size) >= len(messages):
                        logger.info(f"Progress: {min(i + batch_size, len(messages))}/{len(messages)} messages processed")

                except Exception as e:
                    logger.error(f"Error storing batch at offset {i}: {e}")

            logger.info(f"✅ Email sync complete: {total_stored} messages stored")

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

    def _convert_message(self, gmail_msg: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Gmail message format to archive format.

        Args:
            gmail_msg: Message from GmailClient.search_messages()

        Returns:
            Message in archive format
        """
        # Parse date to timestamp and ISO format
        date_timestamp = None
        date_iso = None

        # 1. Try Date header first
        if gmail_msg.get('date'):
            try:
                dt = parsedate_to_datetime(gmail_msg['date'])
                date_timestamp = int(dt.timestamp())
                date_iso = dt.isoformat()
            except Exception as e:
                logger.warning(f"Failed to parse Date header '{gmail_msg['date']}' for message {gmail_msg.get('id')}: {e}")

        # 2. Fallback to internal_date (from Gmail API)
        if date_iso is None and gmail_msg.get('internal_date'):
            try:
                # internalDate is ms since epoch
                ts = int(gmail_msg['internal_date']) / 1000
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                date_timestamp = int(ts)
                date_iso = dt.isoformat()
            except Exception as e:
                logger.warning(f"Failed to parse internal_date '{gmail_msg['internal_date']}': {e}")

        # 3. Final fallback to current time (to satisfy NOT NULL constraint)
        if date_iso is None:
            now = datetime.now(timezone.utc)
            date_timestamp = int(now.timestamp())
            date_iso = now.isoformat()
            logger.warning(f"Using current time for message {gmail_msg.get('id')} as no date could be parsed")

        # Extract email from "Name <email>" format
        from_email = None
        from_name = None
        if gmail_msg.get('from'):
            from_str = gmail_msg['from']
            if '<' in from_str and '>' in from_str:
                # Format: "Name <email>"
                parts = from_str.split('<')
                from_name = parts[0].strip()
                from_email = parts[1].split('>')[0].strip()
            else:
                # Just email
                from_email = from_str.strip()

        # Detect auto-reply based on headers and from email
        from zylch.utils.auto_reply_detector import detect_auto_reply
        auto_reply_headers = {
            'Auto-Submitted': gmail_msg.get('auto_submitted'),
            'X-Autoreply': gmail_msg.get('x_autoreply'),
            'Precedence': gmail_msg.get('precedence'),
            'X-Auto-Response-Suppress': gmail_msg.get('x_auto_response_suppress'),
        }
        is_auto_reply = detect_auto_reply(auto_reply_headers, from_email)

        return {
            'id': gmail_msg['id'],
            'thread_id': gmail_msg['thread_id'],
            'from_email': from_email,
            'from_name': from_name,
            'to_email': self._extract_emails_from_header(gmail_msg.get('to', '')),
            'cc_email': self._extract_emails_from_header(gmail_msg.get('cc', '')),
            'subject': gmail_msg.get('subject', ''),
            'date': date_iso,
            'date_timestamp': date_timestamp,
            'snippet': gmail_msg.get('snippet', ''),
            'body_plain': gmail_msg.get('body', ''),
            'body_html': None,  # Not extracted yet
            'labels': gmail_msg.get('labels', []),
            'message_id_header': gmail_msg.get('message_id', ''),
            'in_reply_to': gmail_msg.get('in_reply_to', ''),
            'references': gmail_msg.get('references', ''),
            'is_auto_reply': is_auto_reply,
        }

    def get_thread_messages(self, thread_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
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
