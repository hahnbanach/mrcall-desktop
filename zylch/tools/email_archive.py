"""Email archive manager with Gmail API integration."""

import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from zylch.config import settings
from zylch.tools.email_archive_backend import EmailArchiveBackend, SQLiteArchiveBackend

if TYPE_CHECKING:
    from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)


class EmailArchiveManager:
    """Manages complete email archive with configurable storage backend.

    Supports both SQLite (local) and Supabase (multi-tenant) backends.
    """

    def __init__(
        self,
        gmail_client,
        owner_id: Optional[str] = None,
        supabase_storage: Optional['SupabaseStorage'] = None
    ):
        """Initialize archive manager.

        Args:
            gmail_client: GmailClient instance for fetching emails
            owner_id: User's Firebase UID (required for Supabase backend)
            supabase_storage: Optional SupabaseStorage instance for multi-tenant
        """
        self.gmail = gmail_client
        self.owner_id = owner_id
        self.supabase = supabase_storage
        self._authenticated = False

        # NOTE: Gmail authentication is now LAZY - only when actually needed
        # This allows the agent to initialize without valid Gmail credentials

        # Use Supabase if provided, otherwise fall back to SQLite
        if self.supabase and self.owner_id:
            self.backend = None  # No SQLite backend needed
            self._use_supabase = True
            logger.info(f"EmailArchiveManager using Supabase for owner {owner_id}")
        else:
            self.backend = self._create_backend()
            self.backend.initialize()
            self._use_supabase = False
            logger.info("EmailArchiveManager using SQLite backend")

    def _ensure_authenticated(self) -> None:
        """Ensure Gmail client is authenticated (lazy authentication)."""
        if not self._authenticated and not self.gmail.service:
            self.gmail.authenticate()
            self._authenticated = True

    def _create_backend(self) -> EmailArchiveBackend:
        """Create storage backend based on configuration."""
        backend_type = settings.email_archive_backend.lower()

        if backend_type == "sqlite":
            return SQLiteArchiveBackend(
                db_path=str(settings.get_email_archive_path()),
                enable_fts=settings.email_archive_enable_fts
            )
        elif backend_type == "postgres":
            raise NotImplementedError(
                "PostgreSQL backend not implemented yet. "
                "Use EMAIL_ARCHIVE_BACKEND=sqlite for now."
            )
        else:
            raise ValueError(
                f"Unknown email archive backend: {backend_type}. "
                "Supported: sqlite"
            )

    def initial_full_sync(self, months_back: Optional[int] = None) -> Dict[str, Any]:
        """One-time initial sync to build archive.

        Fetches emails from Gmail and stores in archive.

        Args:
            months_back: How many months of history to fetch (default from settings)

        Returns:
            Sync results with stats
        """
        if months_back is None:
            months_back = settings.email_archive_initial_months

        logger.info(f"🔄 Starting initial full sync ({months_back} months)...")

        # Check if already completed
        if self._use_supabase:
            sync_state = self.supabase.get_sync_state(self.owner_id)
        else:
            sync_state = self.backend.get_sync_state()

        if sync_state and sync_state.get('full_sync_completed'):
            logger.warning("Initial sync already completed. Use incremental_sync() instead.")
            return {
                'success': False,
                'error': 'Initial sync already completed',
                'full_sync_completed_at': sync_state['full_sync_completed']
            }

        # Calculate date range
        now = datetime.now(timezone.utc)
        after_date = now - timedelta(days=months_back * 30)
        after_date_str = after_date.strftime('%Y/%m/%d')

        logger.info(f"Fetching emails after {after_date_str}")

        # Ensure Gmail is authenticated before fetching
        self._ensure_authenticated()

        # Fetch emails in batches
        batch_size = settings.email_archive_batch_size
        total_fetched = 0
        total_stored = 0
        errors = 0

        try:
            # Gmail search query
            query = f"after:{after_date_str}"

            # Fetch all messages matching query
            logger.info(f"Searching Gmail: {query}")
            messages = self.gmail.search_messages(query=query, max_results=5000)

            total_fetched = len(messages)
            logger.info(f"Fetched {total_fetched} messages from Gmail")

            # Process in batches
            for i in range(0, len(messages), batch_size):
                batch = messages[i:i + batch_size]

                try:
                    # Convert to archive format
                    archive_messages = [self._convert_message(msg) for msg in batch]

                    # Store batch - use appropriate backend
                    if self._use_supabase:
                        stored = self.supabase.store_emails_batch(self.owner_id, archive_messages)
                        total_stored += stored
                    else:
                        self.backend.store_messages_batch(archive_messages)
                        total_stored += len(archive_messages)

                    # Log progress
                    if (i + batch_size) % 1000 == 0 or (i + batch_size) >= len(messages):
                        logger.info(f"Progress: {total_stored}/{total_fetched} messages stored")

                except Exception as e:
                    logger.error(f"Error storing batch at offset {i}: {e}")
                    errors += 1

            # Get history_id from Gmail for future incremental sync
            # Note: This requires a recent API call to get the current history ID
            # We'll use the last message's internal date as a reference
            if messages:
                # Make a simple API call to get current history_id
                try:
                    # Get user profile which includes historyId
                    profile = self.gmail.service.users().getProfile(userId='me').execute()
                    history_id = profile.get('historyId')

                    if history_id:
                        if self._use_supabase:
                            self.supabase.update_sync_state(
                                owner_id=self.owner_id,
                                history_id=history_id,
                                last_sync=now
                            )
                        else:
                            self.backend.update_sync_state(
                                history_id=history_id,
                                last_sync=now
                            )
                        logger.info(f"Saved history_id: {history_id}")
                except Exception as e:
                    logger.warning(f"Could not get history_id: {e}")

            # Mark full sync as completed
            if self._use_supabase:
                self.supabase.mark_full_sync_completed(self.owner_id)
            else:
                self.backend.mark_full_sync_completed()

            logger.info(f"✅ Initial sync complete: {total_stored} messages stored")

            return {
                'success': True,
                'total_fetched': total_fetched,
                'total_stored': total_stored,
                'errors': errors,
                'months_back': months_back,
                'date_range': f"{after_date_str} to {now.strftime('%Y/%m/%d')}"
            }

        except Exception as e:
            logger.error(f"Initial sync failed: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'total_fetched': total_fetched,
                'total_stored': total_stored,
                'errors': errors
            }

    def incremental_sync(self) -> Dict[str, Any]:
        """Incremental sync using Gmail History API.

        Fetches only changes since last sync.

        Returns:
            Sync results
        """
        logger.info("🔄 Starting incremental sync...")

        # Ensure Gmail is authenticated (lazy)
        self._ensure_authenticated()

        # Get last sync state
        if self._use_supabase:
            sync_state = self.supabase.get_sync_state(self.owner_id)
        else:
            sync_state = self.backend.get_sync_state()

        if not sync_state or not sync_state.get('history_id'):
            logger.info("No sync state found. Auto-initializing archive with 1 month of history...")
            # Auto-initialize with 1 month of history for first-time users
            init_result = self.initial_full_sync(months_back=1)
            if not init_result.get('success'):
                return {
                    'success': False,
                    'error': f"Auto-initialization failed: {init_result.get('error', 'Unknown error')}"
                }
            # Return the init result as the sync result
            return {
                'success': True,
                'messages_added': init_result.get('total_stored', 0),
                'messages_deleted': 0,
                'auto_initialized': True,
                'months_synced': 1
            }

        start_history_id = sync_state['history_id']
        logger.info(f"Syncing from history_id: {start_history_id}")

        try:
            # Fetch history changes
            changes = self._fetch_history_changes(start_history_id)

            messages_added = changes['messages_added']
            messages_deleted = changes['messages_deleted']
            new_history_id = changes['new_history_id']

            logger.info(f"Changes found: +{len(messages_added)} -{len(messages_deleted)}")

            # Process added messages
            if messages_added:
                logger.info(f"Fetching {len(messages_added)} new/modified messages...")
                new_messages = []

                for msg_id in messages_added:
                    try:
                        # Fetch full message
                        gmail_msg = self.gmail.service.users().messages().get(
                            userId='me',
                            id=msg_id,
                            format='full'
                        ).execute()

                        # Parse and convert
                        parsed = self.gmail._parse_message(gmail_msg)
                        archive_msg = self._convert_message(parsed)
                        new_messages.append(archive_msg)

                    except Exception as e:
                        # 404 errors are normal (deleted/archived messages)
                        if "404" in str(e) or "not found" in str(e).lower():
                            logger.debug(f"Skipping message {msg_id}: not found (deleted or archived)")
                        else:
                            logger.error(f"Error fetching message {msg_id}: {e}")

                # Store in archive
                if new_messages:
                    if self._use_supabase:
                        self.supabase.store_emails_batch(self.owner_id, new_messages)
                    else:
                        self.backend.store_messages_batch(new_messages)
                    logger.info(f"Stored {len(new_messages)} messages")

            # Process deleted messages
            if messages_deleted:
                logger.info(f"Deleting {len(messages_deleted)} messages...")
                for msg_id in messages_deleted:
                    try:
                        if self._use_supabase:
                            self.supabase.delete_email(self.owner_id, msg_id)
                        else:
                            self.backend.delete_message(msg_id)
                    except Exception as e:
                        logger.error(f"Error deleting message {msg_id}: {e}")

            # Update sync state
            if self._use_supabase:
                self.supabase.update_sync_state(
                    owner_id=self.owner_id,
                    history_id=new_history_id,
                    last_sync=datetime.now(timezone.utc)
                )
            else:
                self.backend.update_sync_state(
                    history_id=new_history_id,
                    last_sync=datetime.now(timezone.utc)
                )

            logger.info(f"✅ Incremental sync complete")

            return {
                'success': True,
                'messages_added': len(messages_added),
                'messages_deleted': len(messages_deleted),
                'new_history_id': new_history_id
            }

        except Exception as e:
            logger.error(f"Incremental sync failed: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def _fetch_history_changes(self, start_history_id: str) -> Dict[str, Any]:
        """Fetch changes from Gmail History API.

        Args:
            start_history_id: History ID from last sync

        Returns:
            Dict with messages_added, messages_deleted, new_history_id
        """
        messages_added = []
        messages_deleted = []
        page_token = None
        new_history_id = start_history_id

        try:
            while True:
                # Call History API
                request = self.gmail.service.users().history().list(
                    userId='me',
                    startHistoryId=start_history_id,
                    historyTypes=['messageAdded', 'messageDeleted'],
                    pageToken=page_token
                )
                response = request.execute()

                # Get new history ID
                new_history_id = response.get('historyId', start_history_id)

                # Process history records
                history_records = response.get('history', [])

                for record in history_records:
                    # Messages added
                    if 'messagesAdded' in record:
                        for msg_added in record['messagesAdded']:
                            msg_id = msg_added['message']['id']
                            messages_added.append(msg_id)

                    # Messages deleted
                    if 'messagesDeleted' in record:
                        for msg_deleted in record['messagesDeleted']:
                            msg_id = msg_deleted['message']['id']
                            messages_deleted.append(msg_id)

                # Check for next page
                page_token = response.get('nextPageToken')
                if not page_token:
                    break

            return {
                'messages_added': list(set(messages_added)),  # Dedupe
                'messages_deleted': list(set(messages_deleted)),
                'new_history_id': new_history_id
            }

        except Exception as e:
            # Check if history ID expired (404 error)
            if '404' in str(e) or 'historyId' in str(e).lower():
                logger.warning(
                    "History ID expired. This happens if no sync for >30 days. "
                    "Falling back to date-based sync..."
                )
                # Fallback: use date-based sync for gap period
                return self._fallback_date_sync(start_history_id)
            else:
                raise

    def _fallback_date_sync(self, old_history_id: str) -> Dict[str, Any]:
        """Fallback sync when history ID expired.

        Uses date-based query to catch up.

        Args:
            old_history_id: Expired history ID

        Returns:
            Dict with changes
        """
        logger.info("Running fallback date-based sync...")

        # Get last sync timestamp from sync state
        if self._use_supabase:
            sync_state = self.supabase.get_sync_state(self.owner_id)
        else:
            sync_state = self.backend.get_sync_state()

        last_sync_str = sync_state.get('last_sync', '') if sync_state else ''

        if last_sync_str:
            try:
                last_sync = datetime.fromisoformat(last_sync_str)
                after_date = last_sync.strftime('%Y/%m/%d')

                # Fetch messages since last sync
                query = f"after:{after_date}"
                logger.info(f"Fetching emails: {query}")

                messages = self.gmail.search_messages(query=query, max_results=5000)

                # Convert and store
                archive_messages = [self._convert_message(msg) for msg in messages]
                if archive_messages:
                    if self._use_supabase:
                        self.supabase.store_emails_batch(self.owner_id, archive_messages)
                    else:
                        self.backend.store_messages_batch(archive_messages)

                # Get new history ID
                profile = self.gmail.service.users().getProfile(userId='me').execute()
                new_history_id = profile.get('historyId')

                return {
                    'messages_added': [msg['id'] for msg in archive_messages],
                    'messages_deleted': [],
                    'new_history_id': new_history_id
                }

            except Exception as e:
                logger.error(f"Fallback sync failed: {e}")
                raise

        raise ValueError("Cannot perform fallback sync: no last_sync timestamp")

    def _convert_message(self, gmail_msg: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Gmail message format to archive format.

        Args:
            gmail_msg: Message from GmailClient.search_messages()

        Returns:
            Message in archive format
        """
        # Parse date to timestamp
        date_timestamp = None
        if gmail_msg.get('date'):
            try:
                dt = parsedate_to_datetime(gmail_msg['date'])
                date_timestamp = int(dt.timestamp())
            except:
                # Fallback to current time if parsing fails
                date_timestamp = int(datetime.now(timezone.utc).timestamp())

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

        return {
            'id': gmail_msg['id'],
            'thread_id': gmail_msg['thread_id'],
            'from_email': from_email,
            'from_name': from_name,
            'to_emails': gmail_msg.get('to', ''),
            'cc_emails': gmail_msg.get('cc', ''),
            'subject': gmail_msg.get('subject', ''),
            'date': gmail_msg['date'],
            'date_timestamp': date_timestamp,
            'snippet': gmail_msg.get('snippet', ''),
            'body_plain': gmail_msg.get('body', ''),
            'body_html': None,  # Not extracted yet
            'labels': gmail_msg.get('labels', []),
            'message_id_header': gmail_msg.get('message_id', ''),
            'in_reply_to': gmail_msg.get('in_reply_to', ''),
            'references': gmail_msg.get('references', '')
        }

    def get_thread_messages(self, thread_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get all messages in a thread from archive.

        Args:
            thread_id: Gmail thread ID
            limit: Optional limit for recent messages only

        Returns:
            List of messages sorted by date
        """
        if self._use_supabase:
            messages = self.supabase.get_thread_emails(self.owner_id, thread_id)
            if limit:
                messages = messages[:limit]
            return messages
        return self.backend.get_thread_messages(thread_id, limit=limit)

    def get_threads_in_window(self, days_back: int = 30) -> List[str]:
        """Get all threads with activity in the last N days.

        Used by Intelligence Cache to analyze recent threads.

        Args:
            days_back: How many days to look back

        Returns:
            List of thread IDs with recent activity
        """
        if self._use_supabase:
            return self.supabase.get_threads_in_window(self.owner_id, days_back)
        return self.backend.get_threads_in_window(days_back=days_back)

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
            from_date: Optional start date filter
            to_date: Optional end date filter
            limit: Max results

        Returns:
            List of matching messages
        """
        if self._use_supabase:
            # Supabase search doesn't support date filters yet (uses search_emails RPC)
            return self.supabase.search_emails(self.owner_id, query, limit)
        return self.backend.search_messages(
            query=query,
            from_date=from_date,
            to_date=to_date,
            limit=limit
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get archive statistics.

        Returns:
            Dict with total messages, threads, date range, last sync
        """
        if self._use_supabase:
            return self.supabase.get_email_stats(self.owner_id)
        return self.backend.get_stats()
