"""Email and calendar sync service - business logic layer."""

from typing import Dict, Any, Optional, Union, TYPE_CHECKING
from pathlib import Path
import logging
from datetime import datetime, timedelta, timezone

from zylch.tools.gmail import GmailClient
from zylch.tools.outlook import OutlookClient
from zylch.tools.gcalendar import GoogleCalendarClient
from zylch.tools.email_archive import EmailArchiveManager
from zylch.tools.email_sync import EmailSyncManager
from zylch.tools.calendar_sync import CalendarSyncManager
from zylch.tools.config import ToolConfig
from zylch.tools.factory import ToolFactory
from zylch.config import settings

# Avoid circular imports
if TYPE_CHECKING:
    from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)


class SyncService:
    """Service for syncing emails and calendar events."""

    def __init__(
        self,
        email_client: Optional[Union[GmailClient, OutlookClient]] = None,
        calendar_client: Optional[GoogleCalendarClient] = None,
        email_archive: Optional[EmailArchiveManager] = None,
        anthropic_api_key: Optional[str] = None,
        owner_id: Optional[str] = None,
        supabase_storage: Optional['SupabaseStorage'] = None
    ):
        """Initialize sync service.

        Args:
            email_client: Email client (GmailClient or OutlookClient) - REQUIRED for sync
            calendar_client: Optional Calendar client (will create if not provided)
            email_archive: Optional EmailArchiveManager (will create if not provided)
            anthropic_api_key: Anthropic API key (BYOK - from Supabase, required)
            owner_id: Firebase UID for multi-tenant Supabase storage
            supabase_storage: SupabaseStorage instance for cloud storage
        """
        self.email_client = email_client
        self.calendar_client = calendar_client
        self.email_archive = email_archive
        self.anthropic_api_key = anthropic_api_key  # BYOK - no env var fallback

        # Multi-tenant Supabase support
        self.owner_id = owner_id
        self.supabase = supabase_storage
        self._use_supabase = bool(self.supabase and self.owner_id)

    async def _ensure_email_client(self):
        """Ensure email client is initialized.

        Email client must be provided to SyncService constructor.
        This method just validates it exists.
        """
        if not self.email_client:
            raise ValueError(
                "Email client is required for sync operations. "
                "SyncService must be initialized with email_client parameter."
            )
        return self.email_client

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

    async def _ensure_email_archive(self):
        """Ensure email archive is initialized."""
        if not self.email_archive:
            email_client = await self._ensure_email_client()
            self.email_archive = EmailArchiveManager(
                gmail_client=email_client,
                owner_id=self.owner_id,
                supabase_storage=self.supabase
            )
        return self.email_archive

    async def sync_emails(self, days_back: Optional[int] = None, force_full: bool = False) -> Dict[str, Any]:
        """Sync emails (provider-agnostic: Gmail or Outlook).

        This method ONLY fetches emails from provider into archive.
        AI analysis is done separately via /gaps command.

        NOTE: Currently only Gmail is supported for email archiving.
        Outlook email sync will be added in a future update.

        Args:
            days_back: Number of days to sync (default: 30 for first sync, incremental for subsequent)
            force_full: Force full sync ignoring history

        Returns:
            Sync results with stats
        """
        logger.info(f"[email_sync] Starting archive sync (days_back={days_back}, force_full={force_full})")

        # Check email client type
        email_client = await self._ensure_email_client()
        from zylch.tools.outlook import OutlookClient

        if isinstance(email_client, OutlookClient):
            # Outlook email archiving not yet implemented
            logger.info("[email_sync] Skipping - Outlook archiving not yet implemented")
            return {
                "success": True,
                "skipped": True,
                "reason": "Outlook email archiving not yet implemented",
                "new_messages": 0,
                "deleted_messages": 0
            }

        # Gmail email sync - ONLY archive, no AI analysis
        archive = await self._ensure_email_archive()
        archive_result = archive.incremental_sync(days_back=days_back, force_full=force_full)

        if not archive_result['success']:
            logger.error(f"Archive sync failed: {archive_result.get('error')}")
            return {
                "success": False,
                "error": f"Archive sync failed: {archive_result.get('error')}"
            }

        logger.info(
            f"[email_sync] Complete: +{archive_result['messages_added']} "
            f"-{archive_result['messages_deleted']} messages"
        )

        return {
            "success": True,
            "new_messages": archive_result['messages_added'],
            "deleted_messages": archive_result['messages_deleted'],
            "incremental": archive_result.get('incremental', False),
            "first_sync_date": archive_result.get('first_sync_date')
        }

    def sync_calendar(self) -> Dict[str, Any]:
        """Sync calendar events from Google Calendar.

        Returns:
            Sync results with stats
        """
        logger.info("[calendar_sync] Starting")

        # Skip calendar sync if no calendar client provided
        # (e.g., Microsoft users - calendar sync not yet implemented)
        if not self.calendar_client:
            logger.info("[calendar_sync] Skipping - no calendar client provided")
            return {
                "success": True,
                "new_events": 0,
                "updated_events": 0,
                "skipped": True,
                "reason": "Calendar client not provided (Microsoft Calendar sync not yet implemented)"
            }

        calendar = self._ensure_calendar_client()

        # Parse my_emails for external attendee detection
        my_emails_list = [email.strip() for email in settings.my_emails.split(',') if email.strip()]

        calendar_sync = CalendarSyncManager(
            calendar_client=calendar,
            api_key=self.anthropic_api_key,
            my_emails=my_emails_list,
            owner_id=self.owner_id,
            supabase_storage=self.supabase
        )

        results = calendar_sync.sync_events()
        logger.info(f"[calendar_sync] Complete: {results.get('new_events', 0)} new, {results.get('updated_events', 0)} updated events")

        return results

    async def sync_pipedrive(self) -> Dict[str, Any]:
        """Sync deals from Pipedrive to local table.

        Fetches all deals from Pipedrive and stores them in pipedrive_deals table.
        Use /memory process pipedrive to extract facts into blobs.

        Returns:
            Sync results with deal count
        """
        logger.info("[pipedrive_sync] Starting")

        # Check if Pipedrive is connected
        if not self.supabase or not self.owner_id:
            logger.info("[pipedrive_sync] Skipping - no Supabase/owner_id")
            return {
                "success": True,
                "skipped": True,
                "reason": "No storage configured",
                "deals_synced": 0
            }

        # Get Pipedrive credentials
        pipedrive_creds = self.supabase.get_provider_credentials(self.owner_id, 'pipedrive')
        if not pipedrive_creds or not pipedrive_creds.get('api_token'):
            logger.info("[pipedrive_sync] Skipping - Pipedrive not connected")
            return {
                "success": True,
                "skipped": True,
                "reason": "Pipedrive not connected",
                "deals_synced": 0
            }

        try:
            from zylch.tools.pipedrive import PipedriveClient

            # Initialize client
            pipedrive = PipedriveClient(api_token=pipedrive_creds['api_token'])

            # Fetch all deals
            deals = pipedrive.list_deals(status="all_not_deleted", limit=500)
            logger.info(f"[pipedrive_sync] Fetched {len(deals)} deals")

            # Store each deal in pipedrive_deals table
            deals_synced = 0
            for deal in deals:
                try:
                    deal_id = str(deal.get('id'))
                    person_name = deal.get('person_name') or (deal.get('person_id') or {}).get('name', '')
                    org_name = deal.get('org_name') or (deal.get('org_id') or {}).get('name', '')

                    # Log missing data - these are important for CRM sync
                    if not person_name:
                        logger.error(f"[pipedrive_sync] Missing person_name for deal {deal_id}")
                    if not org_name:
                        logger.error(f"[pipedrive_sync] Missing org_name for deal {deal_id}")

                    # Upsert deal into table
                    self.supabase.client.table('pipedrive_deals').upsert({
                        'owner_id': self.owner_id,
                        'deal_id': deal_id,
                        'title': deal.get('title', ''),
                        'person_name': person_name,
                        'org_name': org_name,
                        'value': deal.get('value', 0),
                        'currency': deal.get('currency', 'USD'),
                        'status': deal.get('status', 'open'),
                        'stage_name': str(deal.get('stage_id', '')),
                        'pipeline_name': str(deal.get('pipeline_id', '')),
                        'expected_close_date': deal.get('expected_close_date'),
                        'deal_data': deal,
                        'updated_at': datetime.now(timezone.utc).isoformat()
                    }, on_conflict='owner_id,deal_id').execute()

                    deals_synced += 1

                except Exception as e:
                    logger.error(f"[pipedrive_sync] Failed to store deal {deal.get('id')}: {e}")

            logger.info(f"[pipedrive_sync] Complete: {deals_synced} deals synced to table")
            return {
                "success": True,
                "deals_synced": deals_synced,
                "total_deals": len(deals)
            }

        except Exception as e:
            logger.error(f"[pipedrive_sync] Failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "deals_synced": 0
            }

    async def sync_mrcall(self, limit: int = 1, debug: bool = True, firebase_token: str = None, business_id: str = None) -> Dict[str, Any]:
        """Fetch conversations from MrCall for debugging/testing.

        This is a proof-of-concept to verify MrCall API integration works.
        No actual sync to database - just fetches and prints in DEBUG mode.

        Args:
            limit: Number of conversations to fetch (default: 1)
            debug: If True, print conversation data to stdout
            firebase_token: MrCall OAuth access token for authentication
            business_id: Optional business ID override (otherwise fetched from storage)

        Returns:
            Result dict with conversations fetched
        """
        import json
        import httpx

        logger.info(f"[mrcall_sync] Starting (limit={limit}, debug={debug})")

        # Check if storage is configured
        if not self.supabase or not self.owner_id:
            logger.info("[mrcall_sync] Skipping - no Supabase/owner_id")
            return {
                "success": True,
                "skipped": True,
                "reason": "No storage configured",
                "conversations_fetched": 0
            }

        # Get MrCall business ID from credentials or simple link
        if not business_id:
            # Try to get from OAuth credentials first
            mrcall_creds = self.supabase.get_provider_credentials(self.owner_id, 'mrcall')
            if mrcall_creds and mrcall_creds.get('business_id'):
                business_id = mrcall_creds.get('business_id')
            else:
                # Fall back to simple link (legacy)
                business_id = self.supabase.get_mrcall_link(self.owner_id)

        if not business_id:
            logger.info("[mrcall_sync] Skipping - MrCall not linked")
            return {
                "success": True,
                "skipped": True,
                "reason": "MrCall not linked. Use /mrcall <business_id> to link.",
                "conversations_fetched": 0
            }

        # Require access token for API auth
        if not firebase_token:
            logger.error("[mrcall_sync] No access token provided")
            return {
                "success": False,
                "error": "MrCall access token required. Run /connect mrcall to authenticate.",
                "conversations_fetched": 0
            }

        try:
            # Call MrCall conversation search API
            url = "https://api.mrcall.ai/mrcall/v1/mrcall/customer/conversation/search"
            headers = {
                "auth": firebase_token,
                "Content-Type": "application/json"
            }
            body = {
                "businessId": business_id,
                "from": 0,
                "size": limit,
                "lightweight": True,  # Don't include audio
                "asc": False  # Most recent first
            }

            logger.info(f"[mrcall_sync] Calling API: {url}")
            logger.debug(f"[mrcall_sync] Request body: {json.dumps(body)}")

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, json=body)
                response.raise_for_status()
                data = response.json()

            # Parse response - it should be SearchResults with 'items' array
            conversations = data.get('items', []) if isinstance(data, dict) else data
            total = data.get('total', len(conversations)) if isinstance(data, dict) else len(conversations)

            logger.info(f"[mrcall_sync] Fetched {len(conversations)} conversation(s) (total: {total})")

            # DEBUG: Print the conversation data
            if debug and conversations:
                print(f"\n{'='*60}")
                print(f"MrCall DEBUG: Retrieved {len(conversations)} conversation(s)")
                print(f"Business ID: {business_id}")
                print(f"{'='*60}")
                for i, conv in enumerate(conversations):
                    print(f"\n--- Conversation {i+1} ---")
                    print(f"ID: {conv.get('id')}")
                    print(f"Timestamp: {conv.get('startTimestamp')}")
                    print(f"Contact: {conv.get('contactName', 'Unknown')} ({conv.get('contactNumber', 'N/A')})")
                    print(f"Duration: {conv.get('duration', 0) / 1000:.1f}s")
                    print(f"Subject: {conv.get('subject', 'N/A')}")
                    print(f"Body: {conv.get('body', 'N/A')[:200]}...")
                    if conv.get('values'):
                        print(f"Values: {json.dumps(conv.get('values'), indent=2, default=str)}")
                print(f"\n{'='*60}\n")

            return {
                "success": True,
                "conversations_fetched": len(conversations),
                "total_available": total,
                "business_id": business_id,
                "debug": debug
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"[mrcall_sync] HTTP error: {e.response.status_code} - {e.response.text}")
            return {
                "success": False,
                "error": f"MrCall API error: {e.response.status_code}",
                "conversations_fetched": 0
            }
        except Exception as e:
            logger.error(f"[mrcall_sync] Failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "conversations_fetched": 0
            }

    async def run_full_sync(self, days_back: Optional[int] = None) -> Dict[str, Any]:
        """Run full sync workflow: emails + calendar + Pipedrive.

        Syncs data from connected services to local database.
        Does NOT process memory or run analysis - use /memory for that.

        Args:
            days_back: Optional number of days to sync emails

        Returns:
            Combined sync results
        """
        logger.info(f"[full_sync] Starting (days_back={days_back})")

        results = {
            "email_sync": {"success": False, "error": "Not started"},
            "calendar_sync": {"success": False, "error": "Not started"},
            "pipedrive_sync": {"success": False, "error": "Not started"},
            "success": True,
            "errors": []
        }

        # Sync emails
        try:
            email_result = await self.sync_emails(days_back=days_back)
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

        # Sync Pipedrive (if connected)
        try:
            pipedrive_result = await self.sync_pipedrive()
            results["pipedrive_sync"] = pipedrive_result
            if not pipedrive_result.get("success"):
                results["errors"].append(f"Pipedrive sync: {pipedrive_result.get('error', 'Unknown error')}")
        except Exception as e:
            logger.error(f"Pipedrive sync failed: {e}")
            results["pipedrive_sync"] = {
                "success": False,
                "error": str(e)
            }
            results["errors"].append(f"Pipedrive sync: {str(e)}")
            # Don't fail entire sync if Pipedrive fails

        return results
