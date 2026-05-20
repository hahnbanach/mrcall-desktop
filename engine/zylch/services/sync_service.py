"""Email and calendar sync service - business logic layer.

Uses IMAPClient for email sync (replaces Gmail/Outlook OAuth).
"""

from typing import Dict, Any, Optional, TYPE_CHECKING
import logging

from zylch.email.imap_client import IMAPClient
from zylch.tools.email_archive import EmailArchiveManager
from zylch.config import settings

# Avoid circular imports
if TYPE_CHECKING:
    from zylch.storage import Storage

logger = logging.getLogger(__name__)


class SyncService:
    """Service for syncing emails and calendar events.

    Uses IMAPClient for email access instead of OAuth APIs.
    """

    def __init__(
        self,
        email_client: Optional[IMAPClient] = None,
        email_archive: Optional[EmailArchiveManager] = None,
        owner_id: Optional[str] = None,
        supabase_storage: Optional["Storage"] = None,
    ):
        """Initialize sync service.

        Args:
            email_client: IMAPClient instance
            email_archive: Optional EmailArchiveManager
            owner_id: User ID for multi-tenant storage
            supabase_storage: Storage instance
        """
        self.email_client = email_client
        self.email_archive = email_archive

        self.owner_id = owner_id
        self.supabase = supabase_storage
        self._use_supabase = bool(self.supabase and self.owner_id)

        logger.debug(
            f"[SyncService] init owner_id={owner_id},"
            f" email_client="
            f"{'present' if email_client else 'absent'}"
        )

    async def _ensure_email_client(self) -> IMAPClient:
        """Ensure email client is initialized.

        Returns:
            Active IMAPClient

        Raises:
            ValueError: If no email client configured
        """
        if not self.email_client:
            raise ValueError(
                "Email client is required for sync."
                " SyncService must be initialized"
                " with email_client parameter."
            )
        return self.email_client

    async def _ensure_email_archive(
        self,
    ) -> EmailArchiveManager:
        """Ensure email archive is initialized.

        Returns:
            Active EmailArchiveManager
        """
        if not self.email_archive:
            email_client = await self._ensure_email_client()
            self.email_archive = EmailArchiveManager(
                gmail_client=email_client,
                owner_id=self.owner_id,
                supabase_storage=self.supabase,
            )
        return self.email_archive

    async def sync_emails(
        self,
        days_back: Optional[int] = None,
        force_full: bool = False,
        on_progress=None,
    ) -> Dict[str, Any]:
        """Sync emails via IMAP into archive.

        This method ONLY fetches emails into archive.
        AI analysis is done separately via /tasks.

        Args:
            days_back: Days to sync (default: 30)
            force_full: Force full sync

        Returns:
            Sync results with stats
        """
        logger.info(
            f"[email_sync] Starting archive sync"
            f" (days_back={days_back},"
            f" force_full={force_full})"
        )

        archive = await self._ensure_email_archive()
        archive_result = archive.incremental_sync(
            days_back=days_back,
            force_full=force_full,
            on_progress=on_progress,
        )

        if not archive_result["success"]:
            logger.error(f"Archive sync failed:" f" {archive_result.get('error')}")
            return {
                "success": False,
                "error": (f"Archive sync failed:" f" {archive_result.get('error')}"),
            }

        logger.info(
            f"[email_sync] Complete:"
            f" +{archive_result['messages_added']}"
            f" -{archive_result['messages_deleted']}"
            f" messages"
        )

        return {
            "success": True,
            "new_messages": archive_result["messages_added"],
            "deleted_messages": archive_result["messages_deleted"],
            "incremental": archive_result.get("incremental", False),
            "first_sync_date": archive_result.get("first_sync_date"),
        }

    async def sync_mrcall(
        self,
        days_back: int = 30,
        limit: int = 100,
        debug: bool = False,
        firebase_token: str = None,
        business_id: str = None,
        realm: str = None,
    ) -> Dict[str, Any]:
        """Sync MrCall phone call conversations to DB.

        NEUTRALIZED (2026-05): the previous implementation fetched
        conversations over the legacy delegated OAuth2 path
        (``/mrcall/v1/delegated_{realm}/customer/conversation/search``
        with a MrCall OAuth access token). That whole auth mechanism was
        removed. This method is now a graceful no-op so the ``update``
        pipeline (:meth:`run_full_sync`) always completes cleanly.

        The downstream consumers — the ``mrcall_conversations`` table,
        the memory worker, and ``/agent memory ... mrcall`` — are left
        intact; they simply have nothing new to process until fetch is
        reimplemented.

        # TODO(Livello B): reimplement MrCall sync over the Firebase JWT
        #   path ({realm}/customer/conversation/search, no "delegated_"
        #   prefix), using zylch.tools.mrcall.starchat_firebase. Needs
        #   its own design + live testing; see engine/docs.

        Args:
            days_back: Days to sync (default: 30) — currently ignored.
            limit: Max conversations per request — currently ignored.
            debug: Print conversation data — currently ignored.
            firebase_token: Legacy MrCall OAuth token — ignored.
            business_id: Optional business ID override — ignored.
            realm: Optional realm override — ignored.

        Returns:
            A "skipped" result; never raises.
        """
        logger.info(
            "[mrcall_sync] Skipping — legacy delegated MrCall sync was removed; "
            "Firebase-path reimplementation pending (Livello B)."
        )
        return {
            "success": True,
            "skipped": True,
            "reason": "MrCall sync disabled (legacy delegated path removed)",
            "synced": 0,
        }

    async def run_full_sync(
        self,
        days_back: Optional[int] = None,
        on_progress=None,
    ) -> Dict[str, Any]:
        """Run full sync: emails + Pipedrive + MrCall.

        Calendar sync removed (pending CalDAV impl).

        Args:
            days_back: Optional days to sync emails

        Returns:
            Combined sync results
        """
        logger.info(f"[full_sync] Starting" f" (days_back={days_back})")

        results = {
            "email_sync": {
                "success": False,
                "error": "Not started",
            },
            "pipedrive_sync": {
                "success": True,
                "skipped": True,
            },
            "mrcall_sync": {
                "success": False,
                "error": "Not started",
            },
            "success": True,
            "errors": [],
        }

        # Sync emails via IMAP
        try:
            email_result = await self.sync_emails(
                days_back=days_back,
                on_progress=on_progress,
            )
            results["email_sync"] = {
                "success": True,
                **email_result,
            }
        except Exception as e:
            logger.error(f"Email sync failed: {e}")
            results["email_sync"] = {
                "success": False,
                "error": str(e),
            }
            results["errors"].append(f"Email sync: {str(e)}")
            results["success"] = False

        # Pipedrive removed in standalone
        results["pipedrive_sync"] = {
            "success": True,
            "skipped": True,
        }

        # Sync MrCall (if connected)
        try:
            mrcall_result = await self._sync_mrcall_if_connected(
                days_back=(days_back if days_back is not None else 30)
            )
            results["mrcall_sync"] = mrcall_result
            if not mrcall_result.get("success") and not mrcall_result.get("skipped"):
                results["errors"].append(
                    f"MrCall sync:" f" {mrcall_result.get('error', 'Unknown')}"
                )
        except Exception as e:
            logger.error(f"MrCall sync failed: {e}")
            results["mrcall_sync"] = {
                "success": False,
                "error": str(e),
            }
            results["errors"].append(f"MrCall sync: {str(e)}")

        return results

    async def _sync_mrcall_if_connected(self, days_back: int = 30) -> Dict[str, Any]:
        """No-op wrapper kept for the :meth:`run_full_sync` call site.

        The legacy delegated OAuth2 MrCall sync was removed (2026-05).
        Delegates to :meth:`sync_mrcall`, which returns a clean
        "skipped" result so the pipeline never breaks. See the TODO on
        :meth:`sync_mrcall` for the Livello B Firebase-path plan.
        """
        return await self.sync_mrcall(days_back=days_back)
