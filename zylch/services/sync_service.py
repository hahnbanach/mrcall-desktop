"""Email and calendar sync service - business logic layer."""

from typing import Dict, Any, Optional, Union, TYPE_CHECKING
from pathlib import Path
import logging
import hashlib
import re
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


# Email filtering patterns
BLACKLIST_PATTERNS = [
    r'^noreply',
    r'^no-reply',
    r'^do-not-reply',
    r'^donotreply',
    r'mailer-daemon',
    r'^bounce',
    r'^postmaster',
    r'^notifications?',
    r'^automated',
    r'^auto-reply',
    r'^autoreply',
]

SUSPICIOUS_PATTERNS = [
    r'^info@',
    r'^hello@',
    r'^hi@',
    r'^support@',
    r'^help@',
    r'^contact@',
    r'^admin@',
    r'^webmaster@',
    r'^sales@',
    r'^marketing@',
]


def is_blacklisted_email(email: str) -> bool:
    """Check if email is automated/system address.

    Args:
        email: Email address to check

    Returns:
        True if email should be filtered out entirely
    """
    email_lower = email.lower()
    local_part = email_lower.split('@')[0] if '@' in email_lower else email_lower

    for pattern in BLACKLIST_PATTERNS:
        if re.search(pattern, local_part):
            return True
    return False


def calculate_email_confidence(email: str, owner_domain: Optional[str] = None) -> float:
    """Calculate confidence score for email address.

    Args:
        email: Email address to score
        owner_domain: Optional owner's domain for business email detection

    Returns:
        Confidence score: 0.0 (blacklisted), 0.5 (suspicious), 0.8 (business), 1.0 (personal)
    """
    email_lower = email.lower()
    local_part = email_lower.split('@')[0] if '@' in email_lower else ''
    domain = email_lower.split('@')[1] if '@' in email_lower else ''

    # Blacklisted
    if is_blacklisted_email(email):
        return 0.0

    # Suspicious generic
    for pattern in SUSPICIOUS_PATTERNS:
        if re.search(pattern, email_lower):
            return 0.5

    # Trusted personal domains
    TRUSTED_DOMAINS = ['gmail.com', 'outlook.com', 'hotmail.com', 'yahoo.com',
                       'icloud.com', 'me.com', 'mac.com']
    if domain in TRUSTED_DOMAINS:
        return 1.0

    # Owner's organization (high confidence)
    if owner_domain and domain == owner_domain:
        return 0.9

    # Default business email
    return 0.8


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

        # Queue avatar computation for affected contacts
        avatars_queued = 0
        if archive_result['messages_added'] > 0 and self.supabase:
            logger.info(f"[email_sync] Queueing avatar computation for affected contacts...")
            try:
                # Get unique contact IDs from recent emails
                cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days_back or 30)).isoformat()

                # Query emails to get unique senders/recipients
                recent_emails = self.supabase.client.table('emails')\
                    .select('from_email,to_emails,cc_emails')\
                    .eq('owner_id', self.owner_id)\
                    .gte('date', cutoff_date)\
                    .execute()

                # Helper to extract clean email from "Name <email@domain.com>" format
                def extract_email(raw: str) -> tuple:
                    """Extract email and calculate confidence.

                    Returns:
                        (email, confidence) or (None, 0.0) if invalid
                    """
                    raw = raw.strip()
                    # Match email in angle brackets: "Name <email@domain.com>" or "<email@domain.com>"
                    match = re.search(r'<([^>]+@[^>]+)>', raw)
                    if match:
                        email = match.group(1).strip().lower()
                    elif '@' in raw:
                        email = raw.lower()
                    else:
                        return None, 0.0

                    confidence = calculate_email_confidence(email)
                    return email, confidence

                # Extract unique email addresses with confidence
                contact_emails = {}  # {email: confidence}
                for email in recent_emails.data or []:
                    # From address
                    if email.get('from_email'):
                        addr, conf = extract_email(email['from_email'])
                        if addr and conf > 0.0:  # Skip blacklisted
                            contact_emails[addr] = max(contact_emails.get(addr, 0), conf)

                    # To addresses (comma-separated string)
                    if email.get('to_emails'):
                        for raw_addr in email['to_emails'].split(','):
                            addr, conf = extract_email(raw_addr)
                            if addr and conf > 0.0:
                                contact_emails[addr] = max(contact_emails.get(addr, 0), conf)

                    # CC addresses (comma-separated string)
                    if email.get('cc_emails'):
                        for raw_addr in email['cc_emails'].split(','):
                            addr, conf = extract_email(raw_addr)
                            if addr and conf > 0.0:
                                contact_emails[addr] = max(contact_emails.get(addr, 0), conf)

                # Create/update identifier_map entries and queue avatars
                for email_addr, confidence in contact_emails.items():
                    try:
                        # Generate stable contact_id (MD5 of lowercase email)
                        contact_id = hashlib.md5(email_addr.encode()).hexdigest()

                        # Upsert identifier_map entry with calculated confidence
                        self.supabase.client.table('identifier_map').upsert({
                            'owner_id': self.owner_id,
                            'identifier': email_addr,
                            'identifier_type': 'email',
                            'contact_id': contact_id,
                            'confidence': confidence,
                            'source': 'email_sync',
                            'updated_at': datetime.now(timezone.utc).isoformat()
                        }, on_conflict='owner_id,identifier').execute()

                        # Queue avatar computation
                        self.supabase.queue_avatar_compute(
                            owner_id=self.owner_id,
                            contact_id=contact_id,
                            trigger_type='email_sync',
                            priority=7
                        )
                        avatars_queued += 1
                    except Exception as e:
                        logger.warning(f"Failed to queue avatar for {email_addr}: {e}")

                logger.info(f"[email_sync] Queued {avatars_queued} avatars for computation")

            except Exception as e:
                logger.error(f"Failed to queue avatar computation: {e}")

        return {
            "success": True,
            "new_messages": archive_result['messages_added'],
            "deleted_messages": archive_result['messages_deleted'],
            "incremental": archive_result.get('incremental', False),
            "first_sync_date": archive_result.get('first_sync_date'),
            "avatars_queued": avatars_queued
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
            anthropic_api_key=self.anthropic_api_key,
            my_emails=my_emails_list,
            owner_id=self.owner_id,
            supabase_storage=self.supabase
        )

        results = calendar_sync.sync_events()
        logger.info(f"[calendar_sync] Complete: {results.get('new_events', 0)} new, {results.get('updated_events', 0)} updated events")

        return results

    async def sync_pipedrive(self) -> Dict[str, Any]:
        """Sync deals from Pipedrive to memory.

        Fetches all deals from Pipedrive and stores them in the
        unstructured memory system for AI context.

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
            from zylch.memory import ZylchMemory

            # Initialize clients
            pipedrive = PipedriveClient(api_token=pipedrive_creds['api_token'])
            memory = ZylchMemory()  # Uses default local config

            # Fetch all deals
            deals = pipedrive.list_deals(status="all_not_deleted", limit=500)
            logger.info(f"[pipedrive_sync] Fetched {len(deals)} deals")

            # Store each deal in memory
            deals_synced = 0
            for deal in deals:
                try:
                    # Build a human-readable summary
                    person_name = deal.get('person_name') or deal.get('person_id', {}).get('name', 'Unknown')
                    org_name = deal.get('org_name') or deal.get('org_id', {}).get('name', '')
                    stage_name = deal.get('stage_id', 'Unknown stage')
                    value = deal.get('value', 0)
                    currency = deal.get('currency', 'USD')
                    status = deal.get('status', 'open')

                    # Create pattern (human-readable summary)
                    pattern = f"Deal: {deal.get('title', 'Untitled')} | {person_name}"
                    if org_name:
                        pattern += f" ({org_name})"
                    pattern += f" | Value: {value} {currency} | Status: {status}"

                    # Store in memory
                    memory.store_memory(
                        namespace="pipedrive:deals",
                        category="crm",
                        context=f"Pipedrive deal ID {deal.get('id')}: {deal.get('title', 'Untitled')}",
                        pattern=pattern,
                        examples=[f"pipedrive_deal_{deal.get('id')}"],
                        confidence=1.0
                    )
                    deals_synced += 1

                except Exception as e:
                    logger.warning(f"[pipedrive_sync] Failed to store deal {deal.get('id')}: {e}")

            logger.info(f"[pipedrive_sync] Complete: {deals_synced} deals synced to memory")
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

    async def run_full_sync(self, days_back: Optional[int] = None, skip_gap_analysis: bool = False) -> Dict[str, Any]:
        """Run full sync workflow: emails + calendar + Pipedrive + gap analysis.

        Args:
            days_back: Optional number of days to sync emails (also used for gap analysis window)
            skip_gap_analysis: If True, skip gap analysis (avoids Anthropic API calls)

        Returns:
            Combined sync results
        """
        logger.info(f"[full_sync] Starting (days_back={days_back}, skip_gap_analysis={skip_gap_analysis})")

        results = {
            "email_sync": {"success": False, "error": "Not started"},
            "memory_agent": {"success": False, "error": "Not started"},
            "crm_agent": {"success": False, "error": "Not started"},
            "calendar_sync": {"success": False, "error": "Not started"},
            "pipedrive_sync": {"success": False, "error": "Not started"},
            "gap_analysis": {"success": False, "error": "Not started"},
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

        # Memory Agent phase - Process unprocessed emails into structured memory
        try:
            from zylch.workers.memory_worker import MemoryWorker
            from zylch.memory import ZylchMemory

            logger.info("[memory_agent] Starting email processing")
            start_time = datetime.now()

            # Initialize memory system
            memory = ZylchMemory()  # Uses default local config

            # Get unprocessed emails from storage (not memory)
            unprocessed_emails = self.supabase.get_unprocessed_emails(self.owner_id, limit=100)
            email_count = len(unprocessed_emails)

            if email_count > 0:
                # Process batch
                worker = MemoryWorker(memory=memory)
                processed = await worker.process_batch(unprocessed_emails)

                duration = (datetime.now() - start_time).total_seconds()
                logger.info(f"Memory Agent: Processed {processed} emails in {duration:.1f}s")

                results["memory_agent"] = {
                    "success": True,
                    "processed": processed,
                    "duration_seconds": round(duration, 1)
                }
            else:
                logger.info("[memory_agent] No unprocessed emails found")
                results["memory_agent"] = {
                    "success": True,
                    "processed": 0,
                    "duration_seconds": 0.0
                }

        except Exception as e:
            logger.error(f"Memory Agent failed: {e}", exc_info=True)
            results["memory_agent"] = {
                "success": False,
                "error": str(e)
            }
            results["errors"].append(f"Memory Agent: {str(e)}")
            # Continue to CRM phase even if memory agent fails

        # CRM Agent phase - Compute avatars for affected contacts
        try:
            from zylch.workers.crm_worker import CRMWorker
            from zylch.memory import ZylchMemory

            logger.info("[crm_agent] Starting avatar computation")
            start_time = datetime.now()

            # Get affected contacts from recent emails
            affected_contacts = []
            if self.supabase and self.owner_id:
                cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days_back or 30)).isoformat()

                # Query unique contact IDs from recent emails via identifier_map
                recent_identifiers = self.supabase.client.table('identifier_map')\
                    .select('contact_id')\
                    .eq('owner_id', self.owner_id)\
                    .eq('identifier_type', 'email')\
                    .gte('updated_at', cutoff_date)\
                    .execute()

                # Extract unique contact_ids
                affected_contacts = list(set(
                    item['contact_id'] for item in (recent_identifiers.data or [])
                    if item.get('contact_id')
                ))

            contact_count = len(affected_contacts)
            if contact_count > 0:
                # Compute avatars
                from anthropic import Anthropic
                worker = CRMWorker(
                    storage=self.supabase,
                    memory=ZylchMemory(),
                    anthropic=Anthropic()
                )
                await worker.compute_batch(affected_contacts, self.owner_id)
                computed = contact_count

                duration = (datetime.now() - start_time).total_seconds()
                logger.info(f"CRM Agent: Computed {computed} avatars in {duration:.1f}s")

                results["crm_agent"] = {
                    "success": True,
                    "computed": computed,
                    "duration_seconds": round(duration, 1)
                }
            else:
                logger.info("[crm_agent] No affected contacts found")
                results["crm_agent"] = {
                    "success": True,
                    "computed": 0,
                    "duration_seconds": 0.0
                }

        except Exception as e:
            logger.error(f"CRM Agent failed: {e}", exc_info=True)
            results["crm_agent"] = {
                "success": False,
                "error": str(e)
            }
            results["errors"].append(f"CRM Agent: {str(e)}")
            # Don't fail entire sync if CRM agent fails

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

        # Run gap analysis (unless skipped)
        if skip_gap_analysis:
            logger.info("[full_sync] Skipping gap analysis (skip_gap_analysis=True)")
            results["gap_analysis"] = {
                "success": True,
                "total_tasks": 0,
                "email_tasks": 0,
                "meeting_tasks": 0,
                "silent_contacts": 0,
                "skipped": True
            }
        else:
            try:
                from zylch.services.gap_service import GapService

                logger.info("[gap_analysis] Starting")
                gap_service = GapService(
                    owner_id=self.owner_id,
                    supabase_storage=self.supabase
                )
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
                logger.info(f"[gap_analysis] Complete: {total_tasks} tasks found")
            except Exception as e:
                logger.error(f"Gap analysis failed: {e}")
                results["gap_analysis"] = {
                    "success": False,
                    "error": str(e)
                }
                results["errors"].append(f"Gap analysis: {str(e)}")
                # Note: Don't mark overall sync as failed if only gap analysis fails

        return results
