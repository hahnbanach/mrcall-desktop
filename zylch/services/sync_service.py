"""Email and calendar sync service - business logic layer."""

from typing import Dict, Any, Optional
from pathlib import Path
import logging

from zylch.tools.gmail import GmailClient
from zylch.tools.gcalendar import GoogleCalendarClient
from zylch.tools.email_archive import EmailArchiveManager
from zylch.tools.email_sync import EmailSyncManager
from zylch.tools.calendar_sync import CalendarSyncManager
from zylch.config import settings

logger = logging.getLogger(__name__)


class SyncService:
    """Service for syncing emails and calendar events."""

    def __init__(
        self,
        gmail_client: Optional[GmailClient] = None,
        calendar_client: Optional[GoogleCalendarClient] = None,
        email_archive: Optional[EmailArchiveManager] = None,
        anthropic_api_key: Optional[str] = None
    ):
        """Initialize sync service.

        Args:
            gmail_client: Optional Gmail client (will create if not provided)
            calendar_client: Optional Calendar client (will create if not provided)
            email_archive: Optional EmailArchiveManager (will create if not provided)
            anthropic_api_key: Anthropic API key (uses settings if not provided)
        """
        self.gmail_client = gmail_client
        self.calendar_client = calendar_client
        self.email_archive = email_archive
        self.anthropic_api_key = anthropic_api_key or settings.anthropic_api_key

    def _ensure_gmail_client(self):
        """Ensure Gmail client is initialized."""
        if not self.gmail_client:
            self.gmail_client = GmailClient(
                credentials_path=settings.google_credentials_path,
                token_dir=settings.google_token_path
            )
            self.gmail_client.authenticate()
        return self.gmail_client

    def _ensure_calendar_client(self):
        """Ensure Calendar client is initialized."""
        if not self.calendar_client:
            self.calendar_client = GoogleCalendarClient(
                credentials_path=settings.google_credentials_path,
                token_dir=settings.google_token_path,
                calendar_id=settings.calendar_id
            )
            self.calendar_client.authenticate()
        return self.calendar_client

    def _ensure_email_archive(self):
        """Ensure email archive is initialized."""
        if not self.email_archive:
            gmail = self._ensure_gmail_client()
            self.email_archive = EmailArchiveManager(gmail_client=gmail)
        return self.email_archive

    def sync_emails(self, days_back: Optional[int] = None, force_full: bool = False) -> Dict[str, Any]:
        """Sync emails from Gmail (via archive).

        This method:
        1. Runs incremental archive sync (fetches new emails from Gmail)
        2. Builds intelligence cache from archive

        Args:
            days_back: Number of days to sync for intelligence cache (default: 30)
            force_full: Force full cache rebuild ignoring existing cache

        Returns:
            Sync results with stats
        """
        logger.info(f"Starting email sync (days_back={days_back}, force_full={force_full})")

        # Step 1: Ensure archive is synced
        archive = self._ensure_email_archive()
        archive_result = archive.incremental_sync()

        if not archive_result['success']:
            logger.error(f"Archive sync failed: {archive_result.get('error')}")
            return {
                "success": False,
                "error": f"Archive sync failed: {archive_result.get('error')}"
            }

        logger.info(
            f"Archive sync: +{archive_result['messages_added']} "
            f"-{archive_result['messages_deleted']}"
        )

        # Step 2: Build intelligence cache from archive
        email_sync = EmailSyncManager(
            email_archive=archive,
            cache_dir=settings.cache_dir + "/emails",
            anthropic_api_key=self.anthropic_api_key,
            days_back=days_back or 30
        )

        results = email_sync.sync_emails(force_full=force_full, days_back=days_back)
        logger.info(
            f"Email sync complete: {results.get('new_threads', 0)} new, "
            f"{results.get('updated_threads', 0)} updated"
        )

        # Add archive sync results to return value
        results['archive_sync'] = {
            "messages_added": archive_result['messages_added'],
            "messages_deleted": archive_result['messages_deleted']
        }

        return results

    def sync_calendar(self) -> Dict[str, Any]:
        """Sync calendar events from Google Calendar.

        Returns:
            Sync results with stats
        """
        logger.info("Starting calendar sync")

        calendar = self._ensure_calendar_client()

        # Parse my_emails for external attendee detection
        my_emails_list = [email.strip() for email in settings.my_emails.split(',') if email.strip()]

        calendar_sync = CalendarSyncManager(
            calendar_client=calendar,
            anthropic_api_key=self.anthropic_api_key,
            my_emails=my_emails_list
        )

        results = calendar_sync.sync_events()
        logger.info(f"Calendar sync complete: {results.get('new_events', 0)} new, {results.get('updated_events', 0)} updated")

        return results

    def run_full_sync(self, days_back: Optional[int] = None) -> Dict[str, Any]:
        """Run full sync workflow: emails + calendar + gap analysis.

        Args:
            days_back: Optional number of days to sync emails (also used for gap analysis window)

        Returns:
            Combined sync results
        """
        logger.info(f"Starting full sync workflow (days_back={days_back})")

        results = {
            "email_sync": {"success": False, "error": "Not started"},
            "calendar_sync": {"success": False, "error": "Not started"},
            "gap_analysis": {"success": False, "error": "Not started"},
            "success": True,
            "errors": []
        }

        # Sync emails
        try:
            email_result = self.sync_emails(days_back=days_back)
            results["email_sync"] = {
                "success": True,
                **email_result
            }
        except Exception as e:
            logger.error(f"Email sync failed: {e}")
            results["email_sync"] = {
                "success": False,
                "error": str(e)
            }
            results["errors"].append(f"Email sync: {str(e)}")
            results["success"] = False

        # Sync calendar
        try:
            calendar_result = self.sync_calendar()
            results["calendar_sync"] = {
                "success": True,
                **calendar_result
            }
        except Exception as e:
            logger.error(f"Calendar sync failed: {e}")
            results["calendar_sync"] = {
                "success": False,
                "error": str(e)
            }
            results["errors"].append(f"Calendar sync: {str(e)}")
            results["success"] = False

        # Run gap analysis
        try:
            from zylch.services.gap_service import GapService

            logger.info("Starting gap analysis")
            gap_service = GapService()
            gap_result = gap_service.analyze_gaps(days_back=days_back or 7)

            # Count tasks from results
            email_tasks_count = len(gap_result.get('email_tasks', []))
            meeting_tasks_count = len(gap_result.get('meeting_followup_tasks', []))
            silent_contacts_count = len(gap_result.get('silent_contacts', []))
            total_tasks = email_tasks_count + meeting_tasks_count + silent_contacts_count

            results["gap_analysis"] = {
                "success": True,
                "total_tasks": total_tasks,
                "email_tasks": email_tasks_count,
                "meeting_tasks": meeting_tasks_count,
                "silent_contacts": silent_contacts_count,
                "analyzed_at": gap_result.get('analyzed_at')
            }
            logger.info(f"Gap analysis complete: {total_tasks} tasks found")
        except Exception as e:
            logger.error(f"Gap analysis failed: {e}")
            results["gap_analysis"] = {
                "success": False,
                "error": str(e)
            }
            results["errors"].append(f"Gap analysis: {str(e)}")
            # Note: Don't mark overall sync as failed if only gap analysis fails

        return results
