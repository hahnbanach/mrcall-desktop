"""Email and calendar sync service - business logic layer.

Uses IMAPClient for email sync (replaces Gmail/Outlook OAuth). Without an
explicit client, :meth:`SyncService.sync_emails` syncs every non-removed
mailbox of the owner in turn — one client and one archive manager per
mailbox, one mailbox's failure never stopping the others.
"""

from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
import logging

from zylch.email.imap_client import IMAPClient
from zylch.tools.email_archive import EmailArchiveManager

# Avoid circular imports
if TYPE_CHECKING:
    from zylch.storage import Storage

logger = logging.getLogger(__name__)


class MailboxSyncFailed(RuntimeError):
    """No mailbox synced. Carries the per-mailbox ``result`` of ``sync_emails``.

    Chained ``from`` the first mailbox's exception, so an error classifier
    walking ``__cause__`` still sees the IMAP, DNS, TLS or timeout error
    a single-mailbox profile hit; ``result["errors"]`` has every mailbox.
    """

    def __init__(self, result: Dict[str, Any]):
        super().__init__(result.get("error") or "Sync failed")
        self.result = result
        first = next(
            (e.get("exception") for e in result.get("errors", []) if e.get("exception")), None
        )
        if first is not None:
            self.__cause__ = first


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
        """Sync emails via IMAP into the archive, one mailbox at a time.

        This method ONLY fetches emails into archive. AI analysis is done
        separately via /tasks.

        With an explicit ``email_client`` / ``email_archive`` the service
        syncs that one archive (its mailbox, or the primary). Otherwise it
        iterates the owner's non-removed mailboxes, builds one client and
        one ``EmailArchiveManager`` per mailbox, and aggregates. A mailbox
        that fails is reported in ``errors`` with its address and never
        stops the others; ``success`` is False only when no mailbox
        synced. ``last_sync_at`` / ``last_error`` are written per mailbox.

        Args:
            days_back: Days to sync (default: 30)
            force_full: Force full sync
            on_progress: ``(pct, message)`` callback; messages carry the
                mailbox address.

        Returns:
            ``success``, ``new_messages``, ``deleted_messages``,
            ``mailboxes`` (one entry per mailbox), ``errors`` (one entry
            per failed mailbox: ``mailbox_id``, ``address``, ``error``,
            and the ``exception`` for classification — strip it before
            serialising), ``error`` when nothing synced.
        """
        logger.info(
            f"[email_sync] Starting archive sync"
            f" (days_back={days_back},"
            f" force_full={force_full})"
        )
        if self.email_archive is not None or self.email_client is not None:
            archive = await self._ensure_email_archive()
            address = getattr(getattr(archive, "mailbox", None), "address", None) or getattr(
                self.email_client, "email_addr", "primary"
            )
            entry = self._sync_archive(archive, address, days_back, force_full, on_progress)
            return self._aggregate([entry])

        from zylch.email import mailboxes as mailbox_rows

        boxes = mailbox_rows.for_owner(self.owner_id)
        if not boxes:
            return {"success": False, "error": "No mailbox configured.", "new_messages": 0}
        entries: List[Dict[str, Any]] = []
        span = 100.0 / len(boxes)
        for index, box in enumerate(boxes):
            base = span * index

            def scaled(pct: int, message: str, _base=base, _address=box.address) -> None:
                # A raising callback is the caller's bug, never a reason to
                # leave the remaining mailboxes unsynced.
                if on_progress is None:
                    return
                try:
                    on_progress(int(_base + pct * span / 100), f"{_address}: {message}")
                except Exception as e:
                    logger.warning(f"[email_sync] {_address}: progress callback failed: {e}")

            client = None
            entry: Optional[Dict[str, Any]] = None
            try:
                client = mailbox_rows.build_imap_client(box)
                archive = EmailArchiveManager(
                    gmail_client=client,
                    owner_id=self.owner_id,
                    supabase_storage=self.supabase,
                    mailbox=box,
                )
                entry = self._sync_archive(archive, box.address, days_back, force_full, scaled)
            except Exception as e:
                logger.error(f"[email_sync] {box.address}: cannot open mailbox: {e}")
                entry = self._failed(box.id, box.address, e)
                scaled(100, f"failed: {e}")
            finally:
                if entry is None:  # only when the body was interrupted before it produced one
                    entry = self._failed(box.id, box.address, RuntimeError("sync interrupted"))
                entry["mailbox_id"] = box.id
                entries.append(entry)
                mailbox_rows.record_sync_result(self.owner_id, box.id, entry.get("error"))
                if client is not None and hasattr(client, "disconnect"):
                    try:
                        client.disconnect()
                    except Exception as e:
                        logger.debug(f"[email_sync] {box.address}: disconnect failed: {e}")
        return self._aggregate(entries)

    @staticmethod
    def _failed(mailbox_id: Optional[str], address: str, exc: BaseException) -> Dict[str, Any]:
        return {
            "mailbox_id": mailbox_id,
            "address": address,
            "success": False,
            "new_messages": 0,
            "error": str(exc),
            "exception": exc,
        }

    def _sync_archive(
        self,
        archive: EmailArchiveManager,
        address: str,
        days_back: Optional[int],
        force_full: bool,
        on_progress: Optional[Callable[[int, str], None]],
    ) -> Dict[str, Any]:
        """One mailbox's sync as an entry; never raises."""
        mailbox_id = getattr(getattr(archive, "mailbox", None), "id", None)
        try:
            result = archive.incremental_sync(
                days_back=days_back, force_full=force_full, on_progress=on_progress
            )
        except Exception as e:
            logger.error(f"[email_sync] {address}: sync failed: {e}", exc_info=True)
            if on_progress:
                on_progress(100, f"failed: {e}")
            return self._failed(mailbox_id, address, e)
        if not result.get("success"):
            detail = result.get("error") or "; ".join(
                f"{f['folder']}: {f['error']}" for f in result.get("folder_errors", [])
            )
            logger.error(f"[email_sync] {address}: archive sync failed: {detail}")
            entry = self._failed(
                mailbox_id, address, RuntimeError(f"Archive sync failed: {detail}")
            )
            entry["new_messages"] = int(result.get("messages_added", 0) or 0)
            return entry
        logger.info(f"[email_sync] {address}: +{result['messages_added']} messages")
        return {
            "mailbox_id": mailbox_id,
            "address": address,
            "success": True,
            "new_messages": int(result.get("messages_added", 0) or 0),
            "deleted_messages": int(result.get("messages_deleted", 0) or 0),
            "error": None,
        }

    @staticmethod
    def _aggregate(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        errors = [
            {
                "mailbox_id": e.get("mailbox_id"),
                "address": e["address"],
                "error": e["error"],
                "exception": e.get("exception"),
            }
            for e in entries
            if not e["success"]
        ]
        ok = [e for e in entries if e["success"]]
        out: Dict[str, Any] = {
            "success": bool(ok),
            "new_messages": sum(e["new_messages"] for e in entries),
            "deleted_messages": sum(e.get("deleted_messages", 0) for e in entries),
            "incremental": False,
            "first_sync_date": None,
            "mailboxes": [{k: v for k, v in e.items() if k != "exception"} for e in entries],
            "errors": errors,
        }
        if not ok:
            out["error"] = "; ".join(f"{e['address']}: {e['error']}" for e in errors) or (
                "Sync failed"
            )
        return out

    @staticmethod
    def serialisable(result: Dict[str, Any]) -> Dict[str, Any]:
        """``sync_emails``'s result without the exception objects."""
        out = dict(result)
        out["errors"] = [
            {k: v for k, v in e.items() if k != "exception"} for e in result.get("errors", [])
        ]
        return out

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
            email_result = self.serialisable(
                await self.sync_emails(days_back=days_back, on_progress=on_progress)
            )
            results["email_sync"] = {**email_result, "success": bool(email_result["success"])}
            for entry in email_result.get("errors", []):
                results["errors"].append(f"Email sync ({entry['address']}): {entry['error']}")
            if not email_result["success"]:
                results["success"] = False
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
