"""Email archive service - business logic layer for archive management."""

from typing import Dict, Any, Optional, List
from pathlib import Path
import logging

from zylch.tools.gmail import GmailClient
from zylch.tools.email_archive import EmailArchiveManager
from zylch.config import settings

logger = logging.getLogger(__name__)


class ArchiveService:
    """Service for managing email archive operations."""

    def __init__(
        self,
        gmail_client: Optional[GmailClient] = None,
        email_archive: Optional[EmailArchiveManager] = None
    ):
        """Initialize archive service.

        Args:
            gmail_client: Optional Gmail client (will create if not provided)
            email_archive: Optional EmailArchiveManager (will create if not provided)
        """
        self.gmail_client = gmail_client
        self.email_archive = email_archive

    def _ensure_gmail_client(self) -> GmailClient:
        """Ensure Gmail client is initialized."""
        if not self.gmail_client:
            self.gmail_client = GmailClient(
                credentials_path=settings.google_credentials_path,
                token_dir=settings.google_token_path
            )
            self.gmail_client.authenticate()
        return self.gmail_client

    def _ensure_archive(self) -> EmailArchiveManager:
        """Ensure email archive is initialized."""
        if not self.email_archive:
            gmail = self._ensure_gmail_client()
            self.email_archive = EmailArchiveManager(gmail_client=gmail)
        return self.email_archive

    def initialize_archive(self, months_back: Optional[int] = None) -> Dict[str, Any]:
        """Initialize email archive with full sync.

        Args:
            months_back: Number of months to sync (default: from settings)

        Returns:
            Result dictionary with success status and stats
        """
        months = months_back or settings.email_archive_initial_months
        logger.info(f"Initializing email archive ({months} months)...")

        try:
            archive = self._ensure_archive()
            result = archive.initial_full_sync(months_back=months)

            if result['success']:
                logger.info(f"Archive initialized: {result['total_stored']} messages, {result['date_range']}")
                return {
                    "success": True,
                    "messages": result['total_stored'],
                    "date_range": result['date_range'],
                    "location": str(settings.get_email_archive_path())
                }
            else:
                logger.error(f"Archive initialization failed: {result.get('error')}")
                return {
                    "success": False,
                    "error": result.get('error')
                }

        except Exception as e:
            logger.error(f"Archive initialization error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def incremental_sync(self) -> Dict[str, Any]:
        """Run incremental archive sync.

        Returns:
            Result dictionary with success status and sync stats
        """
        logger.info("Running incremental archive sync...")

        try:
            archive = self._ensure_archive()
            result = archive.incremental_sync()

            if result['success']:
                logger.info(
                    f"Archive sync complete: +{result['messages_added']} "
                    f"-{result['messages_deleted']}"
                )
                return {
                    "success": True,
                    "messages_added": result['messages_added'],
                    "messages_deleted": result['messages_deleted'],
                    "no_changes": result['messages_added'] == 0 and result['messages_deleted'] == 0
                }
            else:
                logger.error(f"Archive sync failed: {result.get('error')}")
                return {
                    "success": False,
                    "error": result.get('error')
                }

        except Exception as e:
            logger.error(f"Archive sync error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def get_statistics(self) -> Dict[str, Any]:
        """Get archive statistics.

        Returns:
            Statistics dictionary with message counts, date ranges, etc.
        """
        logger.info("Fetching archive statistics...")

        try:
            archive = self._ensure_archive()
            stats = archive.get_stats()

            logger.info(
                f"Archive stats: {stats['total_messages']} messages, "
                f"{stats['total_threads']} threads"
            )

            return {
                "success": True,
                "stats": stats
            }

        except Exception as e:
            logger.error(f"Failed to get archive stats: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def search_messages(
        self,
        query: str,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """Search archived emails.

        Args:
            query: Search query string
            limit: Maximum number of results (default: 10)

        Returns:
            Search results dictionary with messages list
        """
        limit = limit or 10
        logger.info(f"Searching archive: '{query}' (limit: {limit})")

        try:
            archive = self._ensure_archive()
            results = archive.search_messages(query=query, limit=limit)

            logger.info(f"Search complete: {len(results)} results")

            return {
                "success": True,
                "query": query,
                "count": len(results),
                "limit": limit,
                "messages": results
            }

        except Exception as e:
            logger.error(f"Archive search error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def get_thread_messages(self, thread_id: str) -> Dict[str, Any]:
        """Get all messages in a thread.

        Args:
            thread_id: Gmail thread ID

        Returns:
            Thread messages dictionary
        """
        logger.info(f"Fetching thread: {thread_id}")

        try:
            archive = self._ensure_archive()
            messages = archive.get_thread_messages(thread_id)

            if messages:
                logger.info(f"Thread {thread_id}: {len(messages)} messages")
                return {
                    "success": True,
                    "thread_id": thread_id,
                    "message_count": len(messages),
                    "messages": messages
                }
            else:
                logger.warning(f"Thread {thread_id} not found")
                return {
                    "success": False,
                    "error": "Thread not found"
                }

        except Exception as e:
            logger.error(f"Failed to fetch thread {thread_id}: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def get_threads_in_window(self, days_back: int = 30) -> Dict[str, Any]:
        """Get thread IDs within a time window.

        Args:
            days_back: Number of days to look back (default: 30)

        Returns:
            Thread IDs list
        """
        logger.info(f"Fetching threads in {days_back}-day window")

        try:
            archive = self._ensure_archive()
            thread_ids = archive.get_threads_in_window(days_back=days_back)

            logger.info(f"Found {len(thread_ids)} threads in {days_back}-day window")

            return {
                "success": True,
                "days_back": days_back,
                "count": len(thread_ids),
                "thread_ids": thread_ids
            }

        except Exception as e:
            logger.error(f"Failed to fetch threads: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }
